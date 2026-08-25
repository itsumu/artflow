from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from artflow.project import UnamedTacticsProject


class UnamedTacticsProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workspace = Path(__file__).resolve().parents[2]
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.project = UnamedTacticsProject(
            workspace / "art_source/.artflow/project.json",
            ledger_directory=Path(cls.temporary_directory.name),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_fire_tower_contract_and_evidence_are_readable(self) -> None:
        asset = self.project.read_asset("fire_tower")

        self.assertEqual(asset["asset"]["canvas"], [96, 128])
        self.assertEqual(asset["asset"]["foot_anchor"], [48, 100])
        self.assertTrue(asset["health"]["ok"], asset["health"]["missing_artifacts"])
        self.assertTrue(any(entry["id"] == "runtime" and entry["exists"] for entry in asset["artifacts"]))

    def test_dry_run_declares_but_does_not_write(self) -> None:
        dry_run = self.project.dry_run("fire_tower")
        export_step = next(step for step in dry_run["steps"] if step["id"] == "export")

        self.assertTrue(dry_run["safe"])
        self.assertFalse(dry_run["writes_files"])
        self.assertTrue(dry_run["environment"]["ok"], dry_run["environment"])
        self.assertTrue(dry_run["pipeline_validation"]["ok"], dry_run["pipeline_validation"]["errors"])
        self.assertTrue(export_step["blocked"])
        self.assertEqual(export_step["argv"][-2:], ["building", "fire_tower"])
        self.assertEqual(
            [step["id"] for step in dry_run["steps"] if step["will_run"]],
            ["contract_verify"],
        )

    def test_export_is_declared_as_an_allowed_command(self) -> None:
        self.assertTrue(self.project._is_allowed_artctl_command(["export", "building", "fire_tower"]))
        self.assertTrue(self.project._is_allowed_artctl_command(["verify", "building-export", "fire_tower"]))
        self.assertTrue(self.project._is_allowed_artctl_command(["candidate", "normalize", "building", "fire_tower"]))
        self.assertTrue(self.project._is_allowed_artctl_command(["candidate", "source", "building", "fire_tower"]))
        self.assertTrue(self.project._is_allowed_artctl_command(["candidate", "promote", "building", "fire_tower"]))

    def test_environment_diagnostics_are_readable_and_non_blocking_for_optional_yaml(self) -> None:
        report = self.project.diagnose_environment("fire_tower")
        checks = {check["id"]: check for check in report["checks"]}

        self.assertTrue(report["ok"], report)
        self.assertTrue(checks["artctl"]["ok"])
        self.assertTrue(checks["aseprite_batch"]["ok"])
        self.assertTrue(checks["godot_binary"]["ok"])
        self.assertTrue(checks["runtime_output_directories"]["ok"])
        self.assertFalse(checks["python_pyyaml"]["blocking"])
        self.assertTrue(checks["docs_repository"]["ok"])

    def test_fire_tower_pipeline_matches_capabilities_and_approval_policy(self) -> None:
        report = self.project.validate_pipeline("fire_tower")

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["execution_order"][-1], "runtime_verify")
        self.assertEqual(report["write_count"], 4)

    def test_pipeline_resource_locks_are_resolved_from_the_project_definition(self) -> None:
        self.assertEqual(
            self.project._resource_locks_for_step("fire_tower", "export"),
            ["aseprite_batch", "asset:fire_tower", "godot_import"],
        )
        self.assertEqual(
            self.project._resource_locks_for_step("fire_tower", "runtime_verify"),
            ["asset:fire_tower", "godot_import"],
        )

    def test_failed_run_can_retry_from_read_only_preflight(self) -> None:
        fingerprint = self.project.fingerprint("fire_tower")
        run = self.project.ledger.start(asset_id="fire_tower", operation="export_and_verify", fingerprint=fingerprint)
        self.project.ledger.finish(run["run_id"], status="failed", final_fingerprint=fingerprint)

        retry = self.project.retry_export_from_preflight("fire_tower")

        self.assertTrue(retry["ok"], retry)
        self.assertEqual(retry["run_state"]["state"], "failed")
        self.assertTrue(retry["environment"]["ok"])
        self.assertTrue(retry["preflight"]["ok"])

    def test_building_validation_uses_the_artctl_json_interface(self) -> None:
        report = self.project.verify_buildings()

        self.assertTrue(report["ok"], report.get("stderr"))
        self.assertEqual(report["machine_interface"], "artctl-json-v1")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["assets"][0]["id"], "fire_tower")
        self.assertEqual(report["assets"][0]["foot_anchor"], [48, 100])

    def test_building_export_preflight_uses_a_runtime_optional_check(self) -> None:
        original_godot_project = self.project.config["paths"]["godot_project"]
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            (project_root / "game/resources/visuals").mkdir(parents=True)
            (project_root / "game/art/demo/tiles").mkdir(parents=True)
            (project_root / "tools").mkdir()
            shutil.copy2(self.project.godot_root / "project.godot", project_root / "project.godot")
            shutil.copy2(
                self.project.godot_root / "game/resources/visuals/demo_visual_catalog.tres",
                project_root / "game/resources/visuals/demo_visual_catalog.tres",
            )
            shutil.copy2(
                self.project.godot_root / "tools/validate_demo_visual_assets.gd",
                project_root / "tools/validate_demo_visual_assets.gd",
            )
            shutil.copy2(
                self.project.godot_root / "game/art/demo/tiles/tile_ground_base.png",
                project_root / "game/art/demo/tiles/tile_ground_base.png",
            )
            self.project.config["paths"]["godot_project"] = str(project_root)
            try:
                preflight = self.project.verify_building_export("fire_tower")
                complete_validation = self.project.verify_buildings()
            finally:
                self.project.config["paths"]["godot_project"] = original_godot_project

        self.assertTrue(preflight["ok"], preflight.get("stderr"))
        self.assertFalse(preflight["assets"][0]["runtime"]["exists"])
        self.assertEqual(preflight["command"], ["verify", "building-export", "fire_tower"])
        self.assertFalse(complete_validation["ok"])
        self.assertIn("missing runtime PNG", complete_validation["stderr"])

    def test_verified_run_becomes_stale_when_a_fingerprint_changes(self) -> None:
        fingerprint = self.project.fingerprint("fire_tower")
        run = self.project.ledger.start(asset_id="fire_tower", operation="test", fingerprint=fingerprint)
        self.project.ledger.finish(run["run_id"], status="verified", final_fingerprint=fingerprint)

        self.assertEqual(self.project.latest_run("fire_tower")["state"], "verified")
        changed = {**fingerprint, "runtime_sha256": "different"}
        self.assertEqual(self.project.ledger.asset_state("fire_tower", changed)["state"], "stale")


if __name__ == "__main__":
    unittest.main()
