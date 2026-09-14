"""Project-neutral planning, execution, approval and artifact inspection."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from .adapter import Adapter, check_project
from .executor import CommandExecutor
from .ledger import ACTIVE, RunLedger
from .model import ProjectError, digest, file_hash, now


class Project:
    def __init__(self, config_path, *, ledger_directory=None, executor=None):
        self.config_path = Path(config_path).resolve()
        self.adapter = Adapter(self.config_path)
        self.ledger = RunLedger(ledger_directory or self.adapter.storage)
        self.executor = executor or CommandExecutor()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="artflow")
        self.cancel_events = {}
        self.guard = threading.Lock()
        self.closed = False

    def current_adapter(self):
        """Reload configuration while preserving the running service identity."""
        adapter = Adapter(self.config_path)
        if adapter.storage != self.adapter.storage or adapter.config["project_id"] != self.adapter.config["project_id"]:
            raise ProjectError("Project identity or storage changed; restart the service to use the new location")
        return adapter

    def check(self):
        return check_project(self.config_path,
                             expected_project_id=self.adapter.config["project_id"],
                             expected_storage=self.adapter.storage)

    def resolve(self, aid):
        # Reload definitions for every plan. Browser confirmations bind their hash.
        adapter = self.current_adapter()
        return adapter.resolve(aid)

    def assets(self):
        adapter = self.current_adapter()
        resolved = [adapter.resolve(aid) for aid in adapter.config["assets"]]
        return {"artflow_version": __version__,
                "project": {"id": adapter.config["project_id"], "label": adapter.config["label"]},
                "assets": [{k: asset[k] for k in ("id", "label", "kind")} for asset in resolved]}

    @staticmethod
    def hashes(asset, ids):
        return {aid: file_hash(Path(asset["artifacts"][aid]["path"])) for aid in sorted(set(ids))}

    def step_states(self, asset):
        latest = {}
        for run in self.ledger.list(asset["id"], limit=10000):
            if run.get("legacy"):
                continue
            for record in reversed(run.get("steps", [])):
                latest.setdefault(record["id"], record)
        states = {}
        for sid in asset["validation"]["execution_order"]:
            step = next(s for s in asset["pipeline"]["steps"] if s["id"] == sid)
            record = latest.get(sid)
            status = "not_run"
            if record:
                status = record["status"]
                current = self.hashes(asset, step.get("inputs", []) + step.get("outputs", []))
                if status == "passed" and (record.get("files") != current or record.get("definition_hash") != asset["definition_hash"]):
                    status = "stale"
            if status == "passed" and any(states.get(dep) in {"stale", "failed", "cancelled", "interrupted"}
                                          for dep in step.get("depends_on", [])):
                status = "stale"
            states[sid] = status
        return states

    def read_asset(self, aid):
        adapter = self.current_adapter()
        asset = adapter.resolve(aid)
        records = []
        for item in asset["artifacts"].values():
            path = Path(item["path"])
            exists = path.is_file()
            records.append({**item, "exists": exists, "sha256": file_hash(path),
                            "size": path.stat().st_size if exists else None})
        states = self.step_states(asset) if asset["validation"]["ok"] else {}
        runs = self.ledger.list(aid)
        published = next((r for r in runs if r.get("status") == "verified" and r.get("published_files") and not r.get("legacy")), None)
        published_state = "not_run"
        if published:
            valid = (published.get("definition_hash") == asset["definition_hash"]
                     and published["published_files"] == self.hashes(asset, list(published["published_files"])))
            published_state = "verified" if valid else "stale"
        return {"project": {"id": adapter.config["project_id"], "label": adapter.config["label"]},
                "asset": {k: asset[k] for k in ("id", "label", "kind", "metadata", "preview", "pipeline_id")},
                "artifacts": records, "pipeline": asset["pipeline"], "validation": asset["validation"],
                "step_states": states, "runs": runs, "published_state": published_state,
                "published": published, "read_at": now()}

    def plan(self, aid, action_id):
        asset = self.resolve(aid)
        if not asset["validation"]["ok"]:
            raise ProjectError("Invalid pipeline: " + str(asset["validation"]["errors"]))
        action = asset["pipeline"]["actions"].get(action_id)
        if action is None:
            raise ProjectError(f"Unknown action: {action_id}")
        by_id = {s["id"]: s for s in asset["pipeline"]["steps"]}
        steps = [by_id[sid] for sid in asset["validation"]["execution_order"] if sid in action["steps"]]
        produced, external, tracked, reviewed = set(), set(), set(), set()
        errors = []
        resolved = []
        for step in steps:
            inputs = set(step.get("inputs", []))
            outputs = set(step.get("outputs", []))
            reviewed.update(step.get("approval_artifacts", []))
            external.update(inputs - produced)
            tracked.update(inputs | outputs | set(step.get("approval_artifacts", [])))
            produced.update(outputs)
            command = None
            if step["kind"] == "command":
                command = [*asset["executors"][step["executor"]]["argv"], *step["command"]]
            resolved.append({**step, "argv": command})
        external.update(reviewed)
        tracked.update(action.get("publish_artifacts", []))
        files = self.hashes(asset, tracked)
        for artifact in sorted(external):
            if files.get(artifact) is None:
                errors.append(f"Missing input: {artifact}")
        states = self.step_states(asset)
        for sid, source in by_id.items():
            if (sid not in action["steps"]
                    and external.intersection(source.get("outputs", []))
                    and states.get(sid) in {"stale", "failed", "cancelled", "interrupted"}):
                errors.append(f"Input producer {sid} is {states[sid]}; rebuild before continuing")
        locks = sorted({f"asset:{self.adapter.config['project_id']}:{aid}"} |
                       {lock for s in steps for lock in s.get("locks", [])} |
                       {f"path:{asset['artifacts'][a]['path']}" for a in tracked})
        plan = {"asset_id": aid, "action_id": action_id, "label": action["label"],
                "description": action.get("description", ""), "steps": resolved,
                "definition_hash": asset["definition_hash"], "files": files,
                "checkpoints": [{"id": a, "path": asset["artifacts"][a]["path"], "sha256": files.get(a)} for a in sorted(external)],
                "writes": [{"id": a, "path": asset["artifacts"][a]["path"]} for a in sorted(produced)],
                "requires_approval": any(s.get("requires_approval", False) for s in steps),
                "reviewed_artifacts": sorted(reviewed), "locks": locks,
                "ok": not errors, "errors": errors}
        plan["token"] = digest(plan)
        return plan

    def submit(self, aid, action_id, token, confirmation=""):
        with self.guard:
            if self.closed:
                raise ProjectError("Project is closing; no new run can be submitted.")
        plan = self.plan(aid, action_id)
        if not plan["ok"]:
            raise ProjectError("; ".join(plan["errors"]))
        if token != plan["token"]:
            raise ProjectError("Inputs or configuration changed. Review a fresh plan.")
        if plan["requires_approval"] and confirmation != aid:
            raise ProjectError("Exact asset confirmation is required.")
        event = threading.Event()
        with self.guard:
            if self.closed:
                raise ProjectError("Project is closing; no new run can be submitted.")
            run = self.ledger.create(aid, action_id, plan)
            self.cancel_events[run["run_id"]] = event
            try:
                self.pool.submit(self._execute, run["run_id"], event, confirmation)
            except RuntimeError as error:
                self.cancel_events.pop(run["run_id"], None)
                self.ledger.update(run["run_id"], status="failed", finished_at=now(),
                                   message="Worker pool was unavailable; no command started.")
                raise ProjectError("Project is closing; no new run can be submitted.") from error
        return run

    def _execute(self, rid, cancelled, confirmation):
        run = self.ledger.get(rid)
        aid, action_id, plan = run["asset_id"], run["operation"], run["plan"]
        records = []
        try:
            with self.ledger.resource_locks(plan["locks"]):
                if cancelled.is_set():
                    self.ledger.update(rid, status="cancelled", finished_at=now())
                    return
                current = self.plan(aid, action_id)
                if current["token"] != plan["token"]:
                    raise ProjectError("Inputs changed before the worker acquired its locks; no command started.")
                asset = self.resolve(aid)
                expected_files = dict(plan["files"])
                approvals = [{"asset_id": aid, "confirmed_at": now(), "plan_token": plan["token"],
                              "files": {a: plan["files"][a] for a in plan["reviewed_artifacts"]},
                              "confirmation": confirmation}] if plan["requires_approval"] else []
                self.ledger.update(rid, status="running", approvals=approvals)
                for step in plan["steps"]:
                    if cancelled.is_set():
                        self.ledger.update(rid, status="cancelled", finished_at=now())
                        return
                    # Reject edits to manifests/tools while a multi-step action runs.
                    if self.resolve(aid)["definition_hash"] != plan["definition_hash"]:
                        raise ProjectError("Configuration or tool changed during execution")
                    inputs = self.hashes(asset, step.get("inputs", []))
                    if any(value is None for value in inputs.values()):
                        raise ProjectError(f"{step['id']}: input disappeared")
                    if any(value != expected_files.get(key) for key, value in inputs.items()):
                        raise ProjectError(f"{step['id']}: reviewed input changed before execution")
                    record = {"id": step["id"], "label": step["label"], "status": "running",
                              "started_at": now(), "inputs": inputs, "definition_hash": plan["definition_hash"],
                              "stdout": "", "stderr": ""}
                    records.append(record)
                    self.ledger.update(rid, steps=records)
                    def progress(out, err):
                        record.update(stdout=out, stderr=err)
                        self.ledger.update(rid, steps=records)
                    if step["kind"] == "command":
                        result = self.executor.run(asset["executors"][step["executor"]], step, cancelled, progress)
                    else:
                        result = {"ok": True, "exit_code": 0, "stdout": "Existing input checkpoint recorded.", "stderr": "", "finished_at": now()}
                    files = self.hashes(asset, step.get("inputs", []) + step.get("outputs", []))
                    missing = [a for a in step.get("outputs", []) if files[a] is None]
                    changed = [a for a, sha in inputs.items() if a not in step.get("outputs", []) and files[a] != sha]
                    if missing or changed:
                        result["ok"] = False
                        result["stderr"] = result.get("stderr", "") + f"\nMissing outputs: {missing}; inputs changed during execution: {changed}"
                    record.update(result, files=files, status="passed" if result["ok"] else "cancelled" if cancelled.is_set() else "failed")
                    expected_files.update({a: files[a] for a in step.get("outputs", [])})
                    self.ledger.update(rid, steps=records)
                    if not result["ok"]:
                        self.ledger.update(rid, status=record["status"], finished_at=now(), message=f"Stopped at {step['label']}")
                        return
                action = asset["pipeline"]["actions"][action_id]
                published_ids = action.get("publish_artifacts", [])
                published_files = self.hashes(asset, published_ids)
                if any(v is None for v in published_files.values()):
                    raise ProjectError("Cannot publish missing artifacts")
                if any(value != expected_files.get(key) for key, value in published_files.items()):
                    raise ProjectError("Published artifact changed after validation")
                self.ledger.update(rid, status="verified" if published_ids else "succeeded",
                                   finished_at=now(), definition_hash=plan["definition_hash"],
                                   published_files=published_files, message="All selected steps passed.")
        except Exception as error:
            if records and records[-1]["status"] == "running":
                records[-1].update(status="failed", stderr=str(error), finished_at=now())
            self.ledger.update(rid, status="failed", steps=records, finished_at=now(), message=str(error))
        finally:
            with self.guard:
                self.cancel_events.pop(rid, None)

    def cancel(self, rid):
        run = self.ledger.get(rid)
        with self.guard:
            event = self.cancel_events.get(rid)
            if event:
                event.set()
        return {"ok": bool(event), "run_id": rid, "status": run["status"]}

    def close(self):
        with self.guard:
            if self.closed:
                return
            self.closed = True
            for event in self.cancel_events.values():
                event.set()
        self.pool.shutdown(wait=True)
