"""SQLite run history and OS-owned advisory locks (macOS/Linux)."""
from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .model import digest, now, ProjectError

ACTIVE = {"queued", "running"}


class RunBusyError(ProjectError):
    pass


@contextmanager
def file_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Never unlink lock files: all processes must lock the same inode.
    with path.open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunBusyError(f"Resource is in use: {path.name}") from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class RunLedger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "runs.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, asset TEXT NOT NULL, created TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS runs_asset_created ON runs(asset, created)")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
            legacy = self.directory / "runs.json"
            if legacy.exists() and not db.execute("SELECT 1 FROM metadata WHERE key='json_import'").fetchone():
                data = json.loads(legacy.read_text(encoding="utf-8"))
                for run in data.get("runs", []):
                    # Historical fingerprints have different semantics. Preserve
                    # records, but never present them as newly verified work.
                    run = {**run, "legacy": True}
                    db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,?)",
                               (run["run_id"], run["asset_id"], run["started_at"], json.dumps(run)))
                db.execute("INSERT INTO metadata VALUES ('json_import', ?)", (now(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, aid, action, plan):
        run = {"run_id": uuid4().hex, "asset_id": aid, "operation": action, "status": "queued",
               "started_at": now(), "finished_at": None, "steps": [], "approvals": [],
               "plan": plan, "owner_pid": os.getpid(), "message": None}
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?)",
                       (run["run_id"], aid, run["started_at"], json.dumps(run)))
        return run

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ProjectError(f"Unknown run: {run_id}")
        return json.loads(row[0])

    def update(self, run_id, **fields):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
            if not row:
                raise ProjectError(f"Unknown run: {run_id}")
            run = {**json.loads(row[0]), **fields}
            db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(run), run_id))
        return run

    def list(self, aid, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT payload FROM runs WHERE asset=? ORDER BY created DESC, rowid DESC LIMIT ?",
                              (aid, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def recover_interrupted(self):
        """Call only while holding the project's lifetime service lock."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id, payload FROM runs").fetchall()
            count = 0
            for rid, payload in rows:
                run = json.loads(payload)
                if run.get("status") in ACTIVE:
                    run.update(status="interrupted", finished_at=now(), message="Previous worker stopped; prepare a fresh plan to retry.")
                    db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(run), rid))
                    count += 1
            return count

    @contextmanager
    def resource_locks(self, resources):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for resource in sorted(set(resources)):
                shared = Path(tempfile.gettempdir()) / f"artflow-locks-{os.getuid()}"
                stack.enter_context(file_lock(shared / (digest(resource) + ".lock")))
            yield

    def service_lock(self):
        return file_lock(self.directory / "service.lock")
