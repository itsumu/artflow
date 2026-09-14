import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from artflow.ledger import RunLedger, RunBusyError, file_lock, shared_lock_directory
from artflow.model import ProjectError


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.ledger=RunLedger(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_constructing_second_ledger_does_not_recover_live_run(self):
        run=self.ledger.create("test","build",{})
        with self.ledger.resource_locks([str(self.root)]):
            second=RunLedger(self.root)
            self.assertEqual(second.get(run["run_id"])["status"],"queued")
            with self.assertRaises(RunBusyError):
                with second.resource_locks([str(self.root)]): pass

    def test_service_lock_refuses_second_owner(self):
        with self.ledger.service_lock():
            with self.assertRaises(RunBusyError):
                with RunLedger(self.root).service_lock(): pass

    def test_different_project_ledgers_share_physical_resource_lock(self):
        other=RunLedger(self.root/"other")
        with self.ledger.resource_locks(["path:"+str(self.root)]):
            with self.assertRaises(RunBusyError):
                with other.resource_locks(["path:"+str(self.root)]): pass

    def test_shared_lock_directory_is_private_and_rejects_symlinks(self):
        shared = self.root / "shared"
        with patch.dict(os.environ, {"ARTFLOW_LOCK_DIR": str(shared)}):
            self.assertEqual(stat.S_IMODE(shared_lock_directory().stat().st_mode), 0o700)
        target = self.root / "target"
        target.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(target, target_is_directory=True)
        with patch.dict(os.environ, {"ARTFLOW_LOCK_DIR": str(alias)}):
            with self.assertRaises(ProjectError):
                shared_lock_directory()

    def test_cross_process_lock_is_released_on_process_exit(self):
        path=self.root/"held.lock"
        script="import fcntl,sys,time; f=open(sys.argv[1],'a+'); fcntl.flock(f,fcntl.LOCK_EX); print('held',flush=True); time.sleep(60)"
        proc=subprocess.Popen([sys.executable,"-c",script,str(path)],stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(),"held")
            with self.assertRaises(RunBusyError):
                with file_lock(path): pass
        finally:
            proc.kill(); proc.wait(); proc.stdout.close()
        with file_lock(path): pass
        self.assertTrue(path.exists())

    def test_recovery_retains_history(self):
        run=self.ledger.create("test","build",{})
        self.ledger.update(run["run_id"], status="running", steps=[
            {"id": "build", "status": "passed", "finished_at": "earlier"},
            {"id": "verify", "status": "running", "started_at": "now"},
        ])
        with self.ledger.service_lock():
            self.assertEqual(self.ledger.recover_interrupted(),1)
        recovered = self.ledger.get(run["run_id"])
        self.assertEqual(recovered["status"],"interrupted")
        self.assertEqual(recovered["steps"][0]["status"], "passed")
        self.assertEqual(recovered["steps"][1]["status"], "interrupted")
        self.assertTrue(recovered["steps"][1]["finished_at"])

    def test_legacy_json_import_is_idempotent_and_retained(self):
        folder=self.root/"legacy";folder.mkdir()
        raw={"runs":[{"run_id":"old","asset_id":"test","started_at":"2026-01-01","status":"verified"}]}
        (folder/"runs.json").write_text(json.dumps(raw))
        first=RunLedger(folder);second=RunLedger(folder)
        self.assertEqual(len(second.list("test")),1)
        self.assertTrue(first.get("old")["legacy"])
        self.assertEqual(json.loads((folder/"runs.json").read_text()),raw)
