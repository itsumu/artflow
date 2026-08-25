from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from artflow.ledger import RunBusyError, RunLedger


class RunLedgerResourceLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.ledger = RunLedger(Path(self.temporary_directory.name))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _fingerprint() -> dict[str, str | None]:
        return {"contract_sha256": "fixture", "source_sha256": "fixture", "runtime_sha256": "fixture", "catalog_sha256": "fixture"}

    def test_conflicting_resource_lock_fails_fast_and_releases_all_acquired_locks(self) -> None:
        first = self.ledger.start(
            asset_id="fire_tower",
            operation="export_and_verify",
            fingerprint=self._fingerprint(),
            resource_locks=["godot_import", "asset:fire_tower", "aseprite_batch"],
        )
        second = self.ledger.start(asset_id="water_well", operation="export_and_verify", fingerprint=self._fingerprint())

        with self.ledger.resource_locks(first["resource_locks"], first["run_id"]):
            self.assertEqual(len(list(self.ledger.directory.glob("*.lock"))), 3)
            with self.assertRaisesRegex(RunBusyError, "aseprite_batch"):
                with self.ledger.resource_locks(["aseprite_batch", "asset:water_well"], second["run_id"]):
                    self.fail("a conflicting resource lock must not be acquired")
            self.assertEqual(len(list(self.ledger.directory.glob("*.lock"))), 3)

        self.assertEqual(list(self.ledger.directory.glob("*.lock")), [])
        with self.ledger.resource_locks(["aseprite_batch", "asset:water_well"], second["run_id"]):
            self.assertEqual(len(list(self.ledger.directory.glob("*.lock"))), 2)

    def test_recovery_marks_running_record_interrupted_and_removes_stale_resource_locks(self) -> None:
        run = self.ledger.start(
            asset_id="fire_tower",
            operation="export_and_verify",
            fingerprint=self._fingerprint(),
            resource_locks=["asset:fire_tower", "aseprite_batch"],
        )
        self.ledger.directory.mkdir(parents=True, exist_ok=True)
        self.ledger._lock_path("aseprite_batch").write_text("simulated crash", encoding="utf-8")

        recovered = RunLedger(self.ledger.directory).recover_interrupted()

        self.assertEqual(recovered, 1)
        self.assertEqual(self.ledger.latest("fire_tower")["status"], "interrupted")
        self.assertEqual(list(self.ledger.directory.glob("*.lock")), [])
        self.assertEqual(self.ledger.latest("fire_tower")["run_id"], run["run_id"])

    def test_resource_lock_names_do_not_collide_after_filename_normalization(self) -> None:
        self.assertNotEqual(
            self.ledger._lock_path("asset:fire_tower"),
            self.ledger._lock_path("asset/fire_tower"),
        )


if __name__ == "__main__":
    unittest.main()
