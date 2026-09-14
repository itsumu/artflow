"""Configuration-only adapters: roots, JSON pointers, templates and executors."""
from __future__ import annotations

import copy
import os
import re
import shutil
import sys
from pathlib import Path

from . import __version__
from .model import ProjectError, digest, file_hash, read_json
from .pipeline import ID, validate_pipeline_definition

TOKEN = re.compile(r"\{([a-zA-Z0-9_.-]+)\}")


def lookup(context, key):
    value = context
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise ProjectError(f"Unknown reference: {key}")
        value = value[part]
    return value


def render(value, context):
    if isinstance(value, dict):
        if "$ref" in value:
            result = lookup(context, value["$ref"])
            prefix = value.get("strip_prefix")
            if prefix:
                result = str(result).removeprefix(prefix)
            return copy.deepcopy(result)
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if not isinstance(value, str):
        return value
    return TOKEN.sub(lambda match: str(lookup(context, match[1])), value)


def merge(base, overrides):
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def absolute(value, base):
    return (base / value).resolve()


def find_executable(executable, cwd, executor):
    """Resolve argv[0] using the same cwd and PATH semantics as execution."""
    if os.sep in executable or (os.altsep and os.altsep in executable):
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = cwd / candidate
        return str(candidate.resolve()) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    environment = {
        key: os.environ[key]
        for key in executor.get("inherit_env", ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"])
        if key in os.environ
    }
    environment.update(executor.get("env", {}))
    search_path = os.pathsep.join(os.get_exec_path(environment))
    return shutil.which(executable, path=search_path)


class Adapter:
    """One trusted local manifest; loading never executes adapter code."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.base = self.path.parent
        self.config = read_json(self.path)
        if self.config.get("schema_version") != 2:
            raise ProjectError("Expected project schema_version=2; see docs/adapter.md")
        for field in ("project_id", "label", "assets", "executors", "pipelines"):
            if field not in self.config:
                raise ProjectError(f"project.{field}: required")
        for field in ("assets", "executors", "templates", "roots"):
            if field in self.config and not isinstance(self.config[field], dict):
                raise ProjectError(f"project.{field}: expected an object")
        for field in ("label", "pipelines", "storage"):
            if field in self.config and not isinstance(self.config[field], str):
                raise ProjectError(f"project.{field}: expected a string")
        if any(not isinstance(value, str) for value in self.config.get("roots", {}).values()):
            raise ProjectError("roots must map names to path strings")
        if not isinstance(self.config["project_id"], str) or not ID.fullmatch(self.config["project_id"]):
            raise ProjectError("project_id must be a lowercase identifier")
        self.roots = {key: str(absolute(value, self.base)) for key, value in self.config.get("roots", { "project": "." }).items()}
        self.context = {"root": self.roots, "python": sys.executable, "project_id": self.config["project_id"]}
        self.pipeline_path = absolute(self.config["pipelines"], self.base)
        self.pipeline_config = read_json(self.pipeline_path)
        if self.pipeline_config.get("schema_version") != 2:
            raise ProjectError("Expected pipeline schema_version=2")
        if not isinstance(self.pipeline_config.get("pipelines"), dict):
            raise ProjectError("pipelines must be an object")
        storage = self.config.get("storage", ".artflow-state")
        self.storage = absolute(render(storage, self.context), self.base)
        if not isinstance(self.config["assets"], dict) or not self.config["assets"]:
            raise ProjectError("assets must contain at least one asset")
        for aid in self.config["assets"]:
            if not ID.fullmatch(aid):
                raise ProjectError(f"Invalid asset id: {aid}")

    def resolve(self, aid):
        raw = self.config["assets"].get(aid)
        if not isinstance(raw, dict):
            raise ProjectError(f"Unknown asset: {aid}")
        template = self.config.get("templates", {}).get(raw.get("template"), {})
        if raw.get("template") and not template:
            raise ProjectError(f"{aid}: unknown template")
        spec = merge(template, raw)
        if not isinstance(spec.get("artifacts"), dict) or not isinstance(spec.get("metadata", {}), dict):
            raise ProjectError(f"{aid}: artifacts and metadata must be objects")
        context = {**self.context, "asset_id": aid}
        contract_file = None
        if "data" in spec:
            data = render(spec["data"], context)
            contract_file = absolute(data["file"], self.base)
            contract = read_json(contract_file)
            pointer = data.get("pointer", "")
            if pointer and not pointer.startswith("/"):
                raise ProjectError(f"{aid}.data.pointer: expected JSON Pointer")
            try:
                for segment in pointer.split("/")[1:] if pointer else []:
                    contract = contract[segment.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError) as error:
                raise ProjectError(f"{aid}: JSON pointer not found: {pointer}") from error
            context["data"] = contract
        else:
            context["data"] = {}
        spec = render(spec, context)
        artifacts = {}
        for artifact_id, artifact in spec.get("artifacts", {}).items():
            if not ID.fullmatch(artifact_id) or not isinstance(artifact, dict):
                raise ProjectError(f"{aid}.artifacts: invalid definition")
            root = artifact.get("root")
            if root and root not in self.roots:
                raise ProjectError(f"{aid}.{artifact_id}: unknown root {root}")
            base = Path(self.roots[root]) if root else self.base
            if not isinstance(artifact.get("path"), str):
                raise ProjectError(f"{aid}.{artifact_id}: path must resolve to a string")
            artifacts[artifact_id] = {**artifact, "id": artifact_id,
                "label": artifact.get("label", artifact_id), "kind": artifact.get("kind", "file"),
                "path": str(absolute(artifact["path"], base))}
        if not artifacts:
            raise ProjectError(f"{aid}: declare artifacts")
        context["artifact"] = {key: value["path"] for key, value in artifacts.items()}
        executors = render(self.config["executors"], context)
        for eid, executor in executors.items():
            if not isinstance(executor, dict):
                raise ProjectError(f"executors.{eid}: expected an object")
            prefix = executor.get("argv")
            if (not isinstance(prefix, list) or not prefix
                    or not all(isinstance(token, str) for token in prefix) or not prefix[0]):
                raise ProjectError(f"executors.{eid}.argv: expected a nonempty string array")
            cwd = executor.get("cwd", ".")
            if not isinstance(cwd, str):
                raise ProjectError(f"executors.{eid}.cwd: expected a path string")
            executor["cwd"] = str(absolute(cwd, self.base))
            response = executor.get("response", {})
            if not isinstance(response, dict):
                raise ProjectError(f"executors.{eid}.response: expected an object")
            if response.get("format", "exit_code") not in {"exit_code", "json"}:
                raise ProjectError(f"executors.{eid}: unsupported response format")
            if not isinstance(response.get("success_field", "ok"), str):
                raise ProjectError(f"executors.{eid}.response.success_field: expected a string")
            required = response.get("required", {})
            if not isinstance(required, dict) or any(not isinstance(key, str) for key in required):
                raise ProjectError(f"executors.{eid}.response.required: expected an object")
            allowed = executor.get("allowed_commands")
            if (not isinstance(allowed, list)
                    or any(not isinstance(command, list) or not command
                           or not all(isinstance(token, str) for token in command)
                           for command in allowed)):
                raise ProjectError(f"executors.{eid}.allowed_commands: expected command arrays")
            version_files = executor.get("version_files", [])
            if not isinstance(version_files, list) or not all(isinstance(path, str) for path in version_files):
                raise ProjectError(f"executors.{eid}.version_files: expected path strings")
            inherit_env = executor.get("inherit_env", ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"])
            if not isinstance(inherit_env, list) or not all(isinstance(key, str) for key in inherit_env):
                raise ProjectError(f"executors.{eid}.inherit_env: expected environment variable names")
            environment = executor.get("env", {})
            if (not isinstance(environment, dict)
                    or any(not isinstance(key, str) or not isinstance(value, str)
                           for key, value in environment.items())):
                raise ProjectError(f"executors.{eid}.env: expected string values")
        pid = spec.get("pipeline")
        if pid not in self.pipeline_config.get("pipelines", {}):
            raise ProjectError(f"{aid}: unknown pipeline {pid}")
        pipeline = render(self.pipeline_config["pipelines"][pid], context)
        if not isinstance(pipeline, dict):
            raise ProjectError(f"{aid}: pipeline must be an object")
        preview = spec.get("preview", [])
        if not isinstance(preview, list) or any(not isinstance(key, str) or key not in artifacts for key in preview):
            raise ProjectError(f"{aid}.preview: references an unknown artifact")
        result = {"id": aid, "label": spec.get("label", aid), "kind": spec.get("kind", "asset"),
                  "metadata": spec.get("metadata", {}), "preview": preview,
                  "artifacts": artifacts, "executors": executors, "pipeline": pipeline, "pipeline_id": pid}
        # Definitions and actual tool contents both participate in invalidation.
        result["definition_hash"] = digest({
            "asset": result, "manifest": file_hash(self.path), "pipeline": file_hash(self.pipeline_path),
            "data": file_hash(contract_file) if contract_file else None,
            "tools": {p: file_hash(absolute(p, self.base)) for e in executors.values() for p in e.get("version_files", [])},
        })
        result["validation"] = validate_pipeline_definition(pipeline, artifacts, executors)
        return result

    def check(self):
        assets, errors = [], []

        def issue(asset_id, code, path, message, hint, resolved_path=None):
            error = {"asset_id": asset_id, "code": code, "path": path,
                     "message": message, "hint": hint}
            if resolved_path is not None:
                error["resolved_path"] = str(resolved_path)
            errors.append(error)

        for aid in self.config["assets"]:
            try:
                asset = self.resolve(aid)
                for error in asset["validation"]["errors"]:
                    issue(aid, "invalid_pipeline", error["path"], error["message"],
                          "Fix the pipeline definition, then run check again.")
                checks = []
                for eid, executor in asset["executors"].items():
                    executable = executor["argv"][0]
                    cwd = Path(executor["cwd"])
                    found = find_executable(executable, cwd, executor)
                    version_files = []
                    for value in executor.get("version_files", []):
                        path = absolute(value, self.base)
                        exists = path.is_file()
                        version_files.append({"path": str(path), "ok": exists})
                        if not exists:
                            issue(aid, "missing_version_file", f"executors.{eid}.version_files",
                                  f"Tool version file does not exist: {path}",
                                  "Create the file or remove the stale version_files entry.", path)
                    if not found:
                        issue(aid, "missing_executable", f"executors.{eid}.argv",
                              f"Executable is unavailable: {executable}",
                              "Install the tool or correct executors.argv.", executable)
                    if not cwd.is_dir():
                        issue(aid, "missing_working_directory", f"executors.{eid}.cwd",
                              f"Working directory does not exist: {cwd}",
                              "Create the directory or correct executors.cwd.", cwd)
                    checks.append({"id": eid, "ok": bool(found) and cwd.is_dir()
                                   and all(item["ok"] for item in version_files),
                                   "executable": executable, "resolved_executable": found,
                                   "cwd": str(cwd), "version_files": version_files})
                if asset["validation"]["ok"]:
                    by_id = {step["id"]: step for step in asset["pipeline"]["steps"]}
                    produced = set()
                    external = set()
                    for step_id in asset["validation"]["execution_order"]:
                        step = by_id[step_id]
                        external.update(set(step.get("inputs", [])) - produced)
                        produced.update(step.get("outputs", []))
                    for artifact_id in sorted(external):
                        path = Path(asset["artifacts"][artifact_id]["path"])
                        if not path.is_file():
                            issue(aid, "missing_input", f"artifacts.{artifact_id}.path",
                                  f"Required input does not exist: {path}",
                                  "Create the input file or correct the artifact path.", path)
                assets.append({"id": aid, "label": asset["label"], "kind": asset["kind"],
                               "steps": len(asset["pipeline"]["steps"]), "executors": checks})
            except (ProjectError, KeyError, TypeError, OSError) as error:
                issue(aid, "invalid_adapter", "adapter", str(error),
                      "Fix the project or pipeline JSON, then run check again.")
        return {"ok": not errors, "artflow_version": __version__,
                "project_id": self.config["project_id"], "project_label": self.config["label"],
                "assets": assets,
                "errors": errors, "storage": str(self.storage), "restart_required": False}


def check_project(path, *, expected_project_id=None, expected_storage=None):
    """Return a stable check report even when the adapter cannot be loaded."""
    manifest = Path(path).resolve()
    try:
        adapter = Adapter(manifest)
        result = adapter.check()
    except (ProjectError, KeyError, TypeError, OSError) as error:
        return {"ok": False, "artflow_version": __version__, "project_id": None,
                "project_label": None, "assets": [], "storage": None, "restart_required": False,
                "errors": [{"asset_id": None, "code": "invalid_adapter", "path": "adapter",
                            "message": str(error),
                            "hint": "Fix the project JSON, then run check again.",
                            "resolved_path": str(manifest)}]}

    identity_changed = ((expected_project_id is not None
                         and adapter.config["project_id"] != expected_project_id)
                        or (expected_storage is not None
                            and adapter.storage != Path(expected_storage).resolve()))
    if identity_changed:
        result["restart_required"] = True
        result["ok"] = False
        result["errors"].append({
            "asset_id": None,
            "code": "restart_required",
            "path": "project.identity",
            "message": "Project ID or storage changed while Artflow was running.",
            "hint": "Restart Artflow before using the updated project configuration.",
            "resolved_path": str(manifest),
        })
    return result
