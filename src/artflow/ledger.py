from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterator, Sequence
from uuid import uuid4


class RunBusyError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RunLedger:
    """Small durable run ledger. It records execution facts, never asset facts."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.path = directory / "runs.json"
        self._guard = threading.RLock()

    def recover_interrupted(self) -> int:
        """A new local server marks unfinished records interrupted before reuse."""
        with self._guard:
            data = self._load()
            recovered = 0
            for run in data["runs"]:
                if run.get("status") == "running":
                    run["status"] = "interrupted"
                    run["finished_at"] = _now()
                    run["message"] = "Artflow restarted before this run finished. Safe retry required."
                    recovered += 1
            if recovered:
                self._save(data)
            for lock_path in self.directory.glob("*.lock") if self.directory.exists() else []:
                lock_path.unlink(missing_ok=True)
            return recovered

    def start(
        self,
        *,
        asset_id: str,
        operation: str,
        fingerprint: dict[str, str | None],
        resource_locks: Sequence[str] = (),
    ) -> dict[str, Any]:
        run = {
            "run_id": uuid4().hex,
            "asset_id": asset_id,
            "operation": operation,
            "resource_locks": sorted(set(resource_locks)),
            "status": "running",
            "started_at": _now(),
            "finished_at": None,
            "duration_ms": None,
            "fingerprint": fingerprint,
            "final_fingerprint": None,
            "steps": [],
            "message": None,
        }
        with self._guard:
            data = self._load()
            data["runs"].append(run)
            self._save(data)
        return run

    def add_step(self, run_id: str, step_id: str, result: dict[str, Any]) -> None:
        with self._guard:
            data = self._load()
            run = self._find(data, run_id)
            run["steps"].append({
                "id": step_id,
                "status": "passed" if result.get("ok") else "failed",
                "command": result.get("command"),
                "exit_code": result.get("exit_code"),
                "duration_ms": result.get("duration_ms"),
                "stdout": result.get("stdout", ""),
                "stderr": result.get("stderr", ""),
                "started_at": result.get("started_at"),
                "finished_at": result.get("finished_at"),
            })
            self._save(data)

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        final_fingerprint: dict[str, str | None],
        message: str | None = None,
    ) -> dict[str, Any]:
        with self._guard:
            data = self._load()
            run = self._find(data, run_id)
            finished = _now()
            run["status"] = status
            run["finished_at"] = finished
            run["final_fingerprint"] = final_fingerprint
            run["message"] = message
            started = datetime.fromisoformat(run["started_at"])
            run["duration_ms"] = round((datetime.fromisoformat(finished) - started).total_seconds() * 1000)
            self._save(data)
            return run

    def latest(self, asset_id: str) -> dict[str, Any] | None:
        with self._guard:
            candidates = [run for run in self._load()["runs"] if run.get("asset_id") == asset_id]
            return candidates[-1] if candidates else None

    def asset_state(self, asset_id: str, fingerprint: dict[str, str | None]) -> dict[str, Any]:
        latest = self.latest(asset_id)
        if latest is None:
            return {"state": "not_run", "latest": None}
        if latest.get("status") == "verified" and latest.get("final_fingerprint") != fingerprint:
            return {"state": "stale", "latest": latest}
        return {"state": latest.get("status", "unknown"), "latest": latest}

    @contextmanager
    def asset_lock(self, asset_id: str, run_id: str) -> Iterator[None]:
        with self.resource_locks([f"asset:{asset_id}"], run_id):
            yield

    @contextmanager
    def resource_locks(self, resources: Sequence[str], run_id: str) -> Iterator[None]:
        """Acquire named cross-process locks in a stable order.

        The names come from the validated pipeline definition.  A process can
        safely request an overlapping set because every caller acquires names
        in sorted order; a conflict fails fast instead of queueing an export.
        """
        self.directory.mkdir(parents=True, exist_ok=True)
        requested = sorted(set(resources))
        if not requested:
            yield
            return
        lock_paths = [(resource, self._lock_path(resource)) for resource in requested]
        paths: list[Path] = []
        try:
            for resource, path in lock_paths:
                payload = json.dumps({"run_id": run_id, "resource": resource, "created_at": _now()})
                try:
                    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as error:
                    raise RunBusyError(f"资源锁正在使用：{resource}") from error
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                paths.append(path)
        except Exception:
            for path in reversed(paths):
                path.unlink(missing_ok=True)
            raise
        try:
            yield
        finally:
            for path in reversed(paths):
                path.unlink(missing_ok=True)

    def _lock_path(self, resource: str) -> Path:
        normalized = "".join(character if character.isalnum() else "_" for character in resource).strip("_")
        if not normalized:
            raise ValueError("Resource lock name cannot be empty.")
        suffix = sha256(resource.encode("utf-8")).hexdigest()[:12]
        return self.directory / f"resource_{normalized[:48]}_{suffix}.lock"

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "runs": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Cannot read Artflow run ledger: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("runs"), list):
            raise RuntimeError("Artflow run ledger has an unsupported shape.")
        return value

    def _save(self, data: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _find(data: dict[str, Any], run_id: str) -> dict[str, Any]:
        for run in data["runs"]:
            if run.get("run_id") == run_id:
                return run
        raise RuntimeError(f"Unknown Artflow run: {run_id}")
