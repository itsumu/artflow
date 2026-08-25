from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .ledger import RunBusyError, RunLedger
from .model import Artifact
from .pipeline import validate_pipeline_definition


class ProjectError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectError(f"Cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ProjectError(f"Expected object in {path}.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_record(artifact: Artifact) -> dict[str, Any]:
    exists = artifact.path.is_file()
    return artifact.to_dict(
        exists=exists,
        sha256=_sha256(artifact.path) if exists else None,
        size=artifact.path.stat().st_size if exists else None,
    )


class UnamedTacticsProject:
    """Project adapter. The core never knows these paths or asset properties."""

    def __init__(self, config_path: Path, *, ledger_directory: Path | None = None) -> None:
        self.config_path = config_path.resolve()
        self.source_root = self.config_path.parent.parent.resolve()
        self.workspace_root = self.source_root.parent.resolve()
        self.config = _read_json(self.config_path)
        if self.config.get("schema_version") != 1:
            raise ProjectError("Unsupported project configuration schema.")
        self.pipelines = _read_json(self.config_path.parent / "pipelines.json")
        if self.pipelines.get("schema_version") != 1:
            raise ProjectError("Unsupported pipeline configuration schema.")
        self.ledger = RunLedger(ledger_directory or self.workspace_root / ".artflow-runs" / self.project_id)
        self.recovered_runs = self.ledger.recover_interrupted()

    @property
    def label(self) -> str:
        return str(self.config["label"])

    @property
    def project_id(self) -> str:
        return str(self.config["project_id"])

    @property
    def godot_root(self) -> Path:
        return (self.source_root / self.config["paths"]["godot_project"]).resolve()

    @property
    def docs_root(self) -> Path:
        return (self.source_root / self.config["paths"]["docs"]).resolve()

    @property
    def artctl_path(self) -> Path:
        return self.source_root / self.config["executors"]["artctl"]["command"]

    def _is_allowed_artctl_command(self, command: list[str]) -> bool:
        allowed_commands = self.allowed_artctl_commands
        return any(
            isinstance(allowed, list)
            and len(command) == len(allowed)
            and all(expected == actual or expected == "{asset_id}" for expected, actual in zip(allowed, command, strict=True))
            for allowed in allowed_commands
        )

    @property
    def allowed_artctl_commands(self) -> list[Any]:
        allowed_commands = self.config["executors"]["artctl"].get("allowed_commands", [])
        return allowed_commands if isinstance(allowed_commands, list) else []

    def asset_contract(self, asset_id: str) -> dict[str, Any]:
        asset_config = self.config.get("assets", {}).get(asset_id)
        if not isinstance(asset_config, dict):
            raise ProjectError(f"Unknown asset: {asset_id}")
        contract_path = self.source_root / asset_config["contract"]
        contracts = _read_json(contract_path).get("static_buildings", {})
        asset = contracts.get(asset_id)
        if not isinstance(asset, dict):
            raise ProjectError(f"Missing {asset_id} in {contract_path}")
        return asset

    def artifacts(self, asset_id: str) -> list[Artifact]:
        asset = self.asset_contract(asset_id)
        candidate = asset["candidate_pipeline"]
        candidate_previews = candidate["previews"]
        building_root = self.source_root / "demo/buildings" / asset_id
        return [
            Artifact("contract", "建筑合同", "contract", self.source_root / "demo/static_building_contracts.json"),
            Artifact("source", "Aseprite 正式源", "aseprite", self.source_root / asset["source"]),
            Artifact("runtime", "运行时 PNG", "image", self.godot_root / asset["runtime_path"].removeprefix("res://")),
            Artifact("pose_board", "3×3 草图", "image", building_root / "references/pose_board/fire_tower_v2_pose_board_raw.png"),
            Artifact("cutout", "切图原图", "image", building_root / "references/raw/fire_tower_v2_cutout_raw.png"),
            Artifact("hard_alpha_1x", "硬 Alpha 候选 1×", "image", self.source_root / candidate["normalized_1x"], required=False),
            Artifact("hard_alpha_8x", "硬 Alpha 候选 8×", "image", self.source_root / candidate["normalized_8x"], required=False),
            Artifact("source_candidate", "Aseprite 候选源", "aseprite", self.source_root / candidate["source_candidate"], required=False),
            Artifact("candidate_1x", "候选源审阅 1×", "image", self.workspace_root / candidate_previews["1x"], required=False),
            Artifact("candidate_2x", "候选源审阅 2×", "image", self.workspace_root / candidate_previews["2x"], required=False),
            Artifact("candidate_gray_2x", "候选源灰度 2×", "image", self.workspace_root / candidate_previews["gray_2x"], required=False),
            Artifact("candidate_board_1x", "候选源棋盘预览", "image", self.workspace_root / candidate_previews["board_1x"], required=False),
            Artifact("record", "生成记录", "record", self.docs_root / "demo/art/generation_records/fire_tower_v2_cutout_raw.md"),
            Artifact("catalog", "Godot 视觉目录", "catalog", self.godot_root / "game/resources/visuals/demo_visual_catalog.tres"),
            Artifact("visual_test", "Godot 严格测试", "test", self.godot_root / "tools/validate_demo_visual_assets.gd"),
        ]

    def pipeline_definition(self, asset_id: str) -> tuple[str, dict[str, Any]]:
        config = self.config["assets"][asset_id]
        pipeline_id = config["pipeline"]
        pipeline = self.pipelines["pipelines"].get(pipeline_id)
        if not isinstance(pipeline, dict):
            raise ProjectError(f"Unknown pipeline for {asset_id}")
        return str(pipeline_id), pipeline

    def pipeline(self, asset_id: str) -> list[dict[str, Any]]:
        _pipeline_id, pipeline = self.pipeline_definition(asset_id)
        steps = pipeline.get("steps")
        if not isinstance(steps, list):
            raise ProjectError("Pipeline steps must be a list.")
        return steps

    def _resource_locks_for_step(self, asset_id: str, step_id: str) -> list[str]:
        step = next((candidate for candidate in self.pipeline(asset_id) if candidate.get("id") == step_id), None)
        if not isinstance(step, dict):
            raise ProjectError(f"Unknown pipeline step {step_id} for {asset_id}.")
        locks = step.get("locks", [])
        if not isinstance(locks, list) or not all(isinstance(lock, str) and lock for lock in locks):
            raise ProjectError(f"Pipeline step {step_id} has invalid resource locks.")
        return sorted({lock.replace("{asset_id}", asset_id) for lock in locks})

    def validate_pipeline(self, asset_id: str) -> dict[str, Any]:
        pipeline_id, pipeline = self.pipeline_definition(asset_id)
        capabilities, capabilities_error = self._artctl_capabilities()
        return validate_pipeline_definition(
            pipeline_id,
            pipeline,
            asset_id=asset_id,
            artifact_ids={artifact.id for artifact in self.artifacts(asset_id)},
            allowed_commands=self.allowed_artctl_commands,
            capabilities=capabilities,
            capabilities_error=capabilities_error,
        )

    def read_asset(self, asset_id: str) -> dict[str, Any]:
        asset = self.asset_contract(asset_id)
        artifact_records = [_file_record(artifact) for artifact in self.artifacts(asset_id)]
        missing = [record["label"] for record in artifact_records if record["required"] and not record["exists"]]
        fingerprint = self.fingerprint(asset_id)
        run_state = self.ledger.asset_state(asset_id, fingerprint)
        return {
            "project": {"id": self.project_id, "label": self.label},
            "asset": {
                "id": asset_id,
                "label": asset["label"],
                "kind": asset["kind"],
                "production_state": asset["production_state"],
                "canvas": asset["canvas"],
                "foot_anchor": asset["foot_anchor"],
                "alpha_bounds": asset["alpha_bounds"],
                "runtime_path": asset["runtime_path"],
            },
            "artifacts": artifact_records,
            "pipeline": self.pipeline(asset_id),
            "health": {"ok": not missing, "missing_artifacts": missing},
            "run_state": run_state,
            "read_at": datetime.now(UTC).isoformat(),
        }

    def fingerprint(self, asset_id: str) -> dict[str, str | None]:
        records = {record["id"]: record for record in [_file_record(artifact) for artifact in self.artifacts(asset_id)]}
        return {
            "contract_sha256": records["contract"]["sha256"],
            "source_sha256": records["source"]["sha256"],
            "runtime_sha256": records["runtime"]["sha256"],
            "catalog_sha256": records["catalog"]["sha256"],
        }

    def dry_run(self, asset_id: str) -> dict[str, Any]:
        asset = self.read_asset(asset_id)
        pipeline_validation = self.validate_pipeline(asset_id)
        environment = self.diagnose_environment(asset_id)
        steps = []
        for step in asset["pipeline"]:
            command = step.get("command")
            resolved_command = [str(token).replace("{asset_id}", asset_id) for token in command] if isinstance(command, list) else None
            argv = [
                str(self.artctl_path),
                "--project-root",
                str(self.godot_root),
                "--json",
                *resolved_command,
            ] if resolved_command else None
            steps.append({
                "id": step["id"],
                "label": step["label"],
                "kind": step["kind"],
                "requires_approval": bool(step.get("requires_approval", False)),
                "argv": argv,
                "locks": self._resource_locks_for_step(asset_id, str(step["id"])) if resolved_command else [],
                "will_run": bool(
                    pipeline_validation["ok"]
                    and environment["ok"]
                    and
                    step["id"] == "contract_verify"
                    and resolved_command
                    and self._is_allowed_artctl_command(resolved_command)
                    and not step.get("requires_approval", False)
                ),
                "blocked": bool(step.get("requires_approval", False)),
            })
        return {
            "asset_id": asset_id,
            "mode": "dry_run",
            "safe": pipeline_validation["ok"] and environment["ok"],
            "writes_files": False,
            "steps": steps,
            "pipeline_validation": pipeline_validation,
            "environment": environment,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def diagnose_environment(self, asset_id: str) -> dict[str, Any]:
        """Check the local adapter prerequisites without launching creative tools."""
        machine_report = self._run_artctl(["diagnose"], timeout=30)
        diagnostics = machine_report.get("diagnostics")
        checks: list[dict[str, Any]] = []
        if isinstance(diagnostics, dict):
            diagnostic_checks = diagnostics.get("checks")
            if isinstance(diagnostic_checks, list):
                checks.extend(check for check in diagnostic_checks if isinstance(check, dict))
        if not checks:
            checks.append({
                "id": "artctl_diagnostics_report",
                "label": "artctl 环境诊断报告",
                "ok": False,
                "blocking": True,
                "detail": "artctl 没有返回兼容的环境诊断结果。",
            })

        docs_ok = self.docs_root.is_dir() and os.access(self.docs_root, os.R_OK | os.X_OK)
        checks.append({
            "id": "docs_repository",
            "label": "文档仓库位置",
            "ok": docs_ok,
            "blocking": True,
            "status": "passed" if docs_ok else "failed",
            "detail": "目录可读取。" if docs_ok else f"目录不存在或不可读：{self.docs_root}",
            "path": str(self.docs_root),
        })
        config_ok = self.config_path.is_file() and os.access(self.config_path, os.R_OK)
        checks.append({
            "id": "project_adapter_config",
            "label": "Artflow 项目适配配置",
            "ok": config_ok,
            "blocking": True,
            "status": "passed" if config_ok else "failed",
            "detail": "project.json 可读取。" if config_ok else f"无法读取：{self.config_path}",
            "path": str(self.config_path),
        })
        ok = machine_report.get("ok") is True and all(
            check.get("ok") is True for check in checks if check.get("blocking", True)
        )
        return {
            "schema_version": 1,
            "kind": "environment_diagnostics",
            "asset_id": asset_id,
            "checked_at": datetime.now(UTC).isoformat(),
            "status": "passed" if ok else "failed",
            "ok": ok,
            "checks": checks,
            "artctl_report": machine_report,
        }

    def verify_buildings(self) -> dict[str, Any]:
        return self._run_artctl(["verify", "buildings"], timeout=60)

    def verify_building_export(self, asset_id: str) -> dict[str, Any]:
        return self._run_artctl(["verify", "building-export", asset_id], timeout=60)

    def normalize_building_candidate(self, asset_id: str, expected_raw_sha256: str) -> dict[str, Any]:
        self._require_artifact_hash(asset_id, "cutout", expected_raw_sha256)
        return self._run_candidate_step(
            asset_id, "normalize_candidate", ["candidate", "normalize", "building", asset_id], timeout=180
        )

    def build_building_source_candidate(self, asset_id: str, expected_hard_alpha_sha256: str) -> dict[str, Any]:
        self._require_artifact_hash(asset_id, "hard_alpha_1x", expected_hard_alpha_sha256)
        return self._run_candidate_step(
            asset_id, "build_source_candidate", ["candidate", "source", "building", asset_id], timeout=180
        )

    def promote_building_source_candidate(self, asset_id: str, expected_candidate_sha256: str) -> dict[str, Any]:
        self._require_artifact_hash(asset_id, "source_candidate", expected_candidate_sha256)
        return self._run_candidate_step(
            asset_id, "promote_source", ["candidate", "promote", "building", asset_id], timeout=120
        )

    def _require_artifact_hash(self, asset_id: str, artifact_id: str, expected_sha256: str) -> None:
        artifact = next((item for item in self.artifacts(asset_id) if item.id == artifact_id), None)
        if artifact is None or not artifact.path.is_file():
            raise ProjectError(f"审批产物不存在：{artifact_id}")
        actual = _sha256(artifact.path)
        if not expected_sha256 or actual != expected_sha256:
            raise ProjectError(f"审批产物已变化：{artifact_id}；请刷新页面后重新审阅。")

    def _run_candidate_step(
        self,
        asset_id: str,
        step_id: str,
        command: list[str],
        *,
        timeout: int,
    ) -> dict[str, Any]:
        pipeline_validation = self.validate_pipeline(asset_id)
        environment = self.diagnose_environment(asset_id)
        if not pipeline_validation["ok"] or not environment["ok"]:
            return {
                "ok": False,
                "pipeline_validation": pipeline_validation,
                "environment": environment,
                "result": None,
            }
        resource_locks = self._resource_locks_for_step(asset_id, step_id)
        lock_owner = f"candidate-{asset_id}-{step_id}-{datetime.now(UTC).timestamp()}"
        try:
            with self.ledger.resource_locks(resource_locks, lock_owner):
                result = self._run_artctl(command, timeout=timeout)
        except RunBusyError as error:
            raise ProjectError(str(error)) from error
        return {
            "ok": result["ok"],
            "pipeline_validation": pipeline_validation,
            "environment": environment,
            "result": result,
        }

    def verify_visuals(self) -> dict[str, Any]:
        fingerprint = self.fingerprint("fire_tower")
        resource_locks = self._resource_locks_for_step("fire_tower", "runtime_verify")
        run = self.ledger.start(
            asset_id="fire_tower",
            operation="visual_verify",
            fingerprint=fingerprint,
            resource_locks=resource_locks,
        )
        try:
            with self.ledger.resource_locks(resource_locks, run["run_id"]):
                result = self._run_artctl(["verify", "visuals"], timeout=180)
                self.ledger.add_step(run["run_id"], "runtime_verify", result)
                result["run"] = self.ledger.finish(
                    run["run_id"],
                    status="verified" if result["ok"] else "failed",
                    final_fingerprint=self.fingerprint("fire_tower"),
                    message="Strict Godot visual verification passed." if result["ok"] else "Strict Godot visual verification failed.",
                )
                return result
        except RunBusyError as error:
            self.ledger.finish(run["run_id"], status="cancelled", final_fingerprint=self.fingerprint("fire_tower"), message=str(error))
            raise ProjectError(str(error)) from error

    def export_building(self, asset_id: str) -> dict[str, Any]:
        before = self.fingerprint(asset_id)
        resource_locks = self._resource_locks_for_step(asset_id, "export")
        run = self.ledger.start(
            asset_id=asset_id,
            operation="export_and_verify",
            fingerprint=before,
            resource_locks=resource_locks,
        )
        pipeline_validation = self.validate_pipeline(asset_id)
        environment = self.diagnose_environment(asset_id)
        if not pipeline_validation["ok"]:
            completed = self.ledger.finish(
                run["run_id"],
                status="failed",
                final_fingerprint=self.fingerprint(asset_id),
                message="Pipeline definition is invalid; export was not started.",
            )
            return {
                "ok": False,
                "run": completed,
                "pipeline_validation": pipeline_validation,
                "environment": environment,
                "preflight": None,
                "export": None,
                "visual_verify": None,
            }
        if not environment["ok"]:
            completed = self.ledger.finish(
                run["run_id"],
                status="failed",
                final_fingerprint=self.fingerprint(asset_id),
                message="Execution environment diagnostics failed; export was not started.",
            )
            return {
                "ok": False,
                "run": completed,
                "pipeline_validation": pipeline_validation,
                "environment": environment,
                "preflight": None,
                "export": None,
                "visual_verify": None,
            }
        try:
            with self.ledger.resource_locks(resource_locks, run["run_id"]):
                preflight = self.verify_building_export(asset_id)
                self.ledger.add_step(run["run_id"], "contract_verify", preflight)
                if not preflight["ok"]:
                    completed = self.ledger.finish(run["run_id"], status="failed", final_fingerprint=self.fingerprint(asset_id), message="Building contract preflight failed.")
                    return {
                        "ok": False,
                        "run": completed,
                        "pipeline_validation": pipeline_validation,
                        "environment": environment,
                        "preflight": preflight,
                        "export": None,
                        "visual_verify": None,
                    }
                export = self._run_artctl(["export", "building", asset_id], timeout=180)
                self.ledger.add_step(run["run_id"], "export", export)
                if not export["ok"]:
                    completed = self.ledger.finish(run["run_id"], status="failed", final_fingerprint=self.fingerprint(asset_id), message="Runtime PNG export failed.")
                    return {
                        "ok": False,
                        "run": completed,
                        "pipeline_validation": pipeline_validation,
                        "environment": environment,
                        "preflight": preflight,
                        "export": export,
                        "visual_verify": None,
                    }
                visual_verify = self._run_artctl(["verify", "visuals"], timeout=180)
                self.ledger.add_step(run["run_id"], "runtime_verify", visual_verify)
                final_fingerprint = self.fingerprint(asset_id)
                completed = self.ledger.finish(
                    run["run_id"],
                    status="verified" if visual_verify["ok"] else "failed",
                    final_fingerprint=final_fingerprint,
                    message="Runtime PNG and strict visual verification passed." if visual_verify["ok"] else "Strict Godot visual verification failed.",
                )
                return {
                    "ok": visual_verify["ok"],
                    "run": completed,
                    "pipeline_validation": pipeline_validation,
                    "environment": environment,
                    "preflight": preflight,
                    "export": export,
                    "visual_verify": visual_verify,
                }
        except RunBusyError as error:
            completed = self.ledger.finish(run["run_id"], status="cancelled", final_fingerprint=self.fingerprint(asset_id), message=str(error))
            raise ProjectError(str(error)) from error

    def retry_export_from_preflight(self, asset_id: str) -> dict[str, Any]:
        """Safely re-open a failed/interrupted export from its read-only gates."""
        run_state = self.latest_run(asset_id)
        pipeline_validation = self.validate_pipeline(asset_id)
        retryable_states = {"failed", "interrupted", "cancelled", "stale"}
        if run_state["state"] not in retryable_states:
            return {
                "ok": False,
                "asset_id": asset_id,
                "run_state": run_state,
                "message": "仅失败、已中断、已取消或已过期的运行可以从预检重试。",
                "pipeline_validation": pipeline_validation,
                "environment": None,
                "preflight": None,
            }
        if not pipeline_validation["ok"]:
            return {
                "ok": False,
                "asset_id": asset_id,
                "run_state": run_state,
                "message": "管线定义未通过；未启动环境检查、合同验证或导出。",
                "pipeline_validation": pipeline_validation,
                "environment": None,
                "preflight": None,
            }
        environment = self.diagnose_environment(asset_id)
        if not environment["ok"]:
            return {
                "ok": False,
                "asset_id": asset_id,
                "run_state": run_state,
                "message": "环境诊断未通过；未启动合同验证或导出。",
                "pipeline_validation": pipeline_validation,
                "environment": environment,
                "preflight": None,
            }
        preflight = self.verify_building_export(asset_id)
        return {
            "ok": preflight["ok"],
            "asset_id": asset_id,
            "run_state": run_state,
            "message": "合同验证通过；请再次输入资产 ID 确认导出。" if preflight["ok"] else "合同验证失败；未启动导出。",
            "pipeline_validation": pipeline_validation,
            "environment": environment,
            "preflight": preflight,
        }

    def latest_run(self, asset_id: str) -> dict[str, Any]:
        return self.ledger.asset_state(asset_id, self.fingerprint(asset_id))

    def _artctl_capabilities(self) -> tuple[dict[str, Any] | None, str | None]:
        command = [
            str(self.artctl_path),
            "--project-root",
            str(self.godot_root),
            "--json",
            "capabilities",
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=self.source_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return None, f"无法读取 artctl capabilities：{error}"
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or f"退出码 {completed.returncode}"
            return None, f"artctl capabilities 失败：{message}"
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            return None, f"artctl capabilities 未返回 JSON：{error}"
        if not isinstance(report, dict):
            return None, "artctl capabilities 未返回对象。"
        return report, None

    def _run_artctl(self, command_tokens: list[str], *, timeout: int) -> dict[str, Any]:
        if not self._is_allowed_artctl_command(command_tokens):
            raise ProjectError(f"The project adapter does not allow artctl {' '.join(command_tokens)}.")
        command = [
            str(self.artctl_path),
            "--project-root",
            str(self.godot_root),
            "--json",
            *command_tokens,
        ]
        started = datetime.now(UTC)
        try:
            completed = subprocess.run(
                command,
                cwd=self.source_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            finished = datetime.now(UTC)
            return {
                "command": command,
                "cwd": str(self.source_root),
                "exit_code": 124,
                "ok": False,
                "stdout": (error.stdout.decode() if isinstance(error.stdout, bytes) else error.stdout) or "",
                "stderr": ((error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr) or "") + f"\nTimed out after {timeout} seconds.",
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": round((finished - started).total_seconds() * 1000),
            }
        finished = datetime.now(UTC)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {
                "command": command,
                "cwd": str(self.source_root),
                "exit_code": completed.returncode,
                "ok": False,
                "stdout": completed.stdout,
                "stderr": (completed.stderr + "\nartctl did not produce a valid JSON report.").strip(),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": round((finished - started).total_seconds() * 1000),
            }
        if not isinstance(report, dict) or report.get("machine_interface") != "artctl-json-v1":
            return {
                "command": command,
                "cwd": str(self.source_root),
                "exit_code": completed.returncode,
                "ok": False,
                "stdout": completed.stdout,
                "stderr": (completed.stderr + "\nartctl produced an unsupported machine report.").strip(),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "duration_ms": round((finished - started).total_seconds() * 1000),
            }
        report["invocation"] = command
        report["cwd"] = str(self.source_root)
        report["transport_stderr"] = completed.stderr
        report["ok"] = bool(report.get("ok")) and completed.returncode == 0
        report["exit_code"] = completed.returncode
        return report

    def snapshot(self, asset_id: str) -> dict[str, Any]:
        repositories = [self.source_root, self.godot_root, self.docs_root]
        return {
            "asset_id": asset_id,
            "created_at": datetime.now(UTC).isoformat(),
            "repositories": [self._repository_state(path) for path in repositories],
            "contract_sha256": _sha256(self.source_root / "demo/static_building_contracts.json"),
        }

    @staticmethod
    def _repository_state(path: Path) -> dict[str, Any]:
        def git(*args: str) -> str:
            result = subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True, check=False)
            return result.stdout.strip() if result.returncode == 0 else "unavailable"

        return {
            "path": str(path),
            "commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        }
