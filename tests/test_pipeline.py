from __future__ import annotations

from copy import deepcopy
import unittest

from artflow.pipeline import validate_pipeline_definition


CAPABILITIES = {
    "schema_version": 1,
    "machine_interface": "artctl-json-v1",
    "commands": [
        {"argv": ["verify", "all|buildings"], "mode": "read"},
        {"argv": ["export", "building", "<contract-id>"], "mode": "write"},
    ],
}
ALLOWED_COMMANDS = [["verify", "buildings"], ["export", "building", "{asset_id}"]]
ARTIFACTS = {"contract", "runtime"}


def valid_pipeline() -> dict:
    return {
        "steps": [
            {
                "id": "snapshot",
                "label": "Snapshot",
                "kind": "read",
                "inputs": ["artifact.contract"],
                "outputs": ["snapshot"],
            },
            {
                "id": "verify",
                "label": "Verify",
                "kind": "command",
                "depends_on": ["snapshot"],
                "inputs": ["step.snapshot.snapshot"],
                "executor": "artctl",
                "command": ["verify", "buildings"],
                "timeout_seconds": 60,
                "retry_policy": "safe",
                "write_paths": [],
                "locks": [],
                "outputs": ["report"],
            },
            {
                "id": "export",
                "label": "Export",
                "kind": "command",
                "depends_on": ["verify"],
                "inputs": ["step.verify.report"],
                "executor": "artctl",
                "command": ["export", "building", "{asset_id}"],
                "requires_approval": True,
                "timeout_seconds": 180,
                "retry_policy": "manual",
                "write_paths": ["asset.runtime_path"],
                "locks": ["asset:{asset_id}"],
                "outputs": ["runtime_png"],
            },
        ]
    }


class PipelineValidationTests(unittest.TestCase):
    def validate(self, pipeline: dict) -> dict:
        return validate_pipeline_definition(
            "fixture",
            pipeline,
            asset_id="fire_tower",
            artifact_ids=ARTIFACTS,
            allowed_commands=ALLOWED_COMMANDS,
            capabilities=CAPABILITIES,
        )

    def test_valid_pipeline_has_a_safe_execution_order(self) -> None:
        report = self.validate(valid_pipeline())

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["execution_order"], ["snapshot", "verify", "export"])
        self.assertEqual(report["write_count"], 1)

    def test_rejects_a_write_that_bypasses_approval_and_lock(self) -> None:
        pipeline = deepcopy(valid_pipeline())
        export = pipeline["steps"][2]
        export["requires_approval"] = False
        export["locks"] = []

        report = self.validate(pipeline)
        codes = {error["code"] for error in report["errors"]}

        self.assertFalse(report["ok"])
        self.assertIn("approval.write", codes)
        self.assertIn("command.locks.required", codes)

    def test_rejects_a_step_output_used_without_a_dependency(self) -> None:
        pipeline = deepcopy(valid_pipeline())
        pipeline["steps"][2]["depends_on"] = []

        report = self.validate(pipeline)

        self.assertIn("input.dependency", {error["code"] for error in report["errors"]})

    def test_rejects_cycles_and_duplicate_write_paths(self) -> None:
        pipeline = deepcopy(valid_pipeline())
        pipeline["steps"][0]["depends_on"] = ["export"]
        duplicate = deepcopy(pipeline["steps"][2])
        duplicate["id"] = "export_again"
        duplicate["label"] = "Export again"
        duplicate["outputs"] = ["second_png"]
        pipeline["steps"].append(duplicate)

        report = self.validate(pipeline)
        codes = {error["code"] for error in report["errors"]}

        self.assertIn("dag.cycle", codes)
        self.assertIn("command.path_conflict", codes)


if __name__ == "__main__":
    unittest.main()
