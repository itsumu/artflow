"""Configuration-only adapters: roots, JSON pointers, templates and executors."""
from __future__ import annotations

import copy
import os
import re
import shutil
import sys
from pathlib import Path

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
            if not isinstance(prefix, list) or not prefix or not all(isinstance(t, str) for t in prefix):
                raise ProjectError(f"executors.{eid}.argv: expected string array")
            executor["cwd"] = str(absolute(executor.get("cwd", "."), self.base))
            response = executor.get("response", {})
            if response.get("format", "exit_code") not in {"exit_code", "json"}:
                raise ProjectError(f"executors.{eid}: unsupported response format")
            if not isinstance(executor.get("allowed_commands"), list):
                raise ProjectError(f"executors.{eid}: allowed_commands required")
            for path in executor.get("version_files", []):
                if not isinstance(path, str):
                    raise ProjectError(f"executors.{eid}: version_files must be paths")
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
        for aid in self.config["assets"]:
            try:
                asset = self.resolve(aid)
                errors.extend({"asset_id": aid, **error} for error in asset["validation"]["errors"])
                checks = []
                for eid, executor in asset["executors"].items():
                    executable = executor["argv"][0]
                    found = shutil.which(executable)
                    ok = bool(found) and Path(executor["cwd"]).is_dir()
                    checks.append({"id": eid, "ok": ok, "executable": executable, "cwd": executor["cwd"]})
                    if not ok:
                        errors.append({"asset_id": aid, "path": f"executors.{eid}", "message": "Executable or working directory unavailable"})
                assets.append({"id": aid, "label": asset["label"], "kind": asset["kind"],
                               "steps": len(asset["pipeline"]["steps"]), "executors": checks})
            except (ProjectError, KeyError, TypeError, OSError) as error:
                errors.append({"asset_id": aid, "path": "adapter", "message": str(error)})
        return {"ok": not errors, "project_id": self.config["project_id"], "assets": assets,
                "errors": errors, "storage": str(self.storage)}
