from __future__ import annotations
import json
import shutil
import tempfile
import threading
import time
import unittest
from importlib.resources import files
from pathlib import Path

from artflow.adapter import Adapter
from artflow.project import Project
from artflow.model import ProjectError


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="artflow-test-")
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(str(files("artflow").joinpath("examples/starter")), self.root, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".artflow-state", "output"))
        self.project = Project(self.root / "project.json")

    def tearDown(self):
        self.project.close()
        self.tmp.cleanup()

    def wait(self, run):
        end = time.monotonic() + 10
        while run["status"] in {"queued", "running"}:
            if time.monotonic() > end:
                self.fail("run did not finish")
            time.sleep(.03)
            run = self.project.ledger.get(run["run_id"])
        return run

    def build(self, aid="campfire"):
        plan = self.project.plan(aid, "build")
        return self.wait(self.project.submit(aid, "build", plan["token"], aid))

    def edit_pipeline(self, edit):
        path = self.root / "pipelines.json"
        config = json.loads(path.read_text())
        edit(config["pipelines"]["sprite"])
        path.write_text(json.dumps(config))

    def recolor_campfire(self):
        path = self.root / "inputs/campfire.json"
        recipe = json.loads(path.read_text())
        recipe["palette"]["Y"] = "#FFF2A8"
        path.write_text(json.dumps(recipe))

    def test_standalone_two_assets_run_and_publish(self):
        self.assertTrue(Adapter(self.root / "project.json").check()["ok"])
        for aid in ("campfire", "crystal"):
            run = self.build(aid)
            self.assertEqual(run["status"], "verified", run)
            self.assertEqual([s["id"] for s in run["steps"]], ["build", "verify"])
            self.assertTrue(run["approvals"][0]["files"]["recipe"])
            output = self.root / "output" / f"{aid}.png"
            self.assertTrue(output.is_file())
            self.assertTrue(output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertEqual(self.project.read_asset(aid)["published_state"], "verified")

    def test_new_asset_needs_only_config_and_input(self):
        path = self.root / "project.json"
        config = json.loads(path.read_text())
        config["assets"]["ember"] = {"template": "sprite", "label": "Ember"}
        path.write_text(json.dumps(config))
        shutil.copy2(self.root / "inputs/campfire.json", self.root / "inputs/ember.json")
        self.assertEqual(self.build("ember")["status"], "verified")

    def test_configuration_drives_real_executor_and_timeout(self):
        calls = []
        class Fake:
            def run(_, spec, step, cancelled, progress):
                calls.append((step["command"], step["timeout_seconds"]))
                return {"ok": True, "exit_code": 0}
        self.project.executor = Fake()
        self.edit_pipeline(lambda p: p["steps"][0].update(command=["verify", "{artifact.image}"], timeout_seconds=7))
        (self.root / "output").mkdir()
        (self.root / "output/campfire.png").write_bytes(b"existing")
        plan = self.project.plan("campfire", "build")
        self.assertEqual(plan["steps"][0]["argv"][-2:], ["verify", str(self.root / "output/campfire.png")])
        run = self.wait(self.project.submit("campfire", "build", plan["token"], "campfire"))
        self.assertEqual(run["status"], "verified", run)
        self.assertEqual(calls[0], (["verify", str(self.root / "output/campfire.png")], 7))

    def test_missing_input_blocks_before_any_run(self):
        (self.root / "inputs/campfire.json").unlink()
        plan = self.project.plan("campfire", "build")
        self.assertFalse(plan["ok"])
        with self.assertRaises(ProjectError):
            self.project.submit("campfire", "build", plan["token"], "campfire")
        self.assertEqual(self.project.ledger.list("campfire"), [])

    def test_check_requires_external_inputs_but_allows_future_outputs(self):
        self.assertFalse((self.root / "output/campfire.png").exists())
        self.assertTrue(self.project.check()["ok"])
        (self.root / "inputs/campfire.json").unlink()
        result = self.project.check()
        self.assertFalse(result["ok"])
        error = next(item for item in result["errors"] if item["code"] == "missing_input")
        self.assertEqual(error["resolved_path"], str(self.root / "inputs/campfire.json"))
        self.assertTrue(error["hint"])

    def test_check_requires_missing_input_for_in_place_command(self):
        def make_build_in_place(pipeline):
            build = pipeline["steps"][0]
            build["inputs"] = ["recipe"]
            build["outputs"] = ["recipe"]
            pipeline["steps"] = [build]
            pipeline["actions"]["build"]["steps"] = ["build"]
            pipeline["actions"]["build"]["publish_artifacts"] = ["recipe"]
            pipeline["actions"] = {"build": pipeline["actions"]["build"]}

        self.edit_pipeline(make_build_in_place)
        (self.root / "inputs/campfire.json").unlink()
        result = self.project.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any(
            item["asset_id"] == "campfire"
            and item["code"] == "missing_input"
            and item["resolved_path"] == str(self.root / "inputs/campfire.json")
            for item in result["errors"]
        ))

    def test_check_requires_declared_tool_version_files(self):
        (self.root / "make_asset.py").unlink()
        result = self.project.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "missing_version_file" for item in result["errors"]))

    def test_check_resolves_relative_executable_from_executor_cwd(self):
        tool = self.root / "local_tool"
        tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        tool.chmod(0o755)
        path = self.root / "project.json"
        config = json.loads(path.read_text())
        config["executors"]["python"]["argv"] = ["./local_tool"]
        config["executors"]["python"]["version_files"] = ["local_tool"]
        path.write_text(json.dumps(config))
        result = self.project.check()
        self.assertTrue(result["ok"], result)
        self.assertTrue(all(
            executor["resolved_executable"] == str(tool)
            for asset in result["assets"]
            for executor in asset["executors"]
        ))

    def test_check_rejects_malformed_executor_environment(self):
        path = self.root / "project.json"
        config = json.loads(path.read_text())
        config["executors"]["python"]["env"] = ["NOT_AN_OBJECT"]
        path.write_text(json.dumps(config))
        result = self.project.check()
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "invalid_adapter" and ".env" in item["message"]
                            for item in result["errors"]))

    def test_check_reports_identity_changes_require_restart(self):
        path = self.root / "project.json"
        config = json.loads(path.read_text())
        config["storage"] = ".different-state"
        path.write_text(json.dumps(config))
        result = self.project.check()
        self.assertFalse(result["ok"])
        self.assertTrue(result["restart_required"])
        self.assertTrue(any(item["code"] == "restart_required" for item in result["errors"]))

    def test_stale_confirmation_and_wrong_confirmation_rejected(self):
        plan = self.project.plan("campfire", "build")
        with self.assertRaises(ProjectError):
            self.project.submit("campfire", "build", plan["token"], "crystal")
        self.recolor_campfire()
        with self.assertRaisesRegex(ProjectError, "changed"):
            self.project.submit("campfire", "build", plan["token"], "campfire")
        self.assertFalse((self.root / "output").exists())

    def test_changed_input_invalidates_downstream_and_old_publication(self):
        self.build()
        self.recolor_campfire()
        data = self.project.read_asset("campfire")
        self.assertEqual(data["step_states"], {"build":"stale", "verify":"stale"})
        self.assertEqual(data["published_state"], "stale")
        self.assertFalse(self.project.plan("campfire", "verify")["ok"])
        self.assertEqual(self.build()["status"], "verified")

    def test_interrupted_step_invalidates_downstream_result(self):
        run = self.build()
        steps = run["steps"]
        steps[0] = {**steps[0], "status": "interrupted"}
        self.project.ledger.update(run["run_id"], steps=steps)
        self.assertEqual(self.project.read_asset("campfire")["step_states"],
                         {"build": "interrupted", "verify": "stale"})

    def test_changing_tool_invalidates_old_results(self):
        self.build()
        with (self.root / "make_asset.py").open("a") as stream:
            stream.write("\n# a new tool version\n")
        self.assertEqual(self.project.read_asset("campfire")["step_states"]["build"], "stale")

    def test_candidate_like_action_is_durable_without_publishing(self):
        self.edit_pipeline(lambda p: p["actions"].update(candidate={"label":"Candidate","steps":["build"]}))
        plan = self.project.plan("campfire", "candidate")
        run = self.wait(self.project.submit("campfire", "candidate", plan["token"], "campfire"))
        self.assertEqual(run["status"], "succeeded")
        self.assertTrue(run["steps"][0]["inputs"])
        self.assertTrue(run["steps"][0]["files"]["image"])
        self.assertEqual(self.project.read_asset("campfire")["published_state"], "not_run")

    def test_executor_exception_finishes_run_and_releases_lock(self):
        class Broken:
            def run(*args): raise OSError("simulated launch failure")
        original = self.project.executor
        self.project.executor = Broken()
        failed = self.build()
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["steps"][0]["status"], "failed")
        self.assertIn("simulated", failed["message"])
        self.project.executor = original
        self.assertEqual(self.build()["status"], "verified")

    def test_exit_success_without_output_fails(self):
        class Fake:
            def run(*args): return {"ok":True,"exit_code":0}
        self.project.executor = Fake()
        failed = self.build()
        self.assertEqual(failed["status"], "failed")
        self.assertIn("Missing outputs", failed["steps"][0]["stderr"])

    def test_cancel_stops_worker_and_records_status(self):
        started = threading.Event()
        class Slow:
            def run(_, spec, step, cancelled, progress):
                started.set()
                cancelled.wait(5)
                return {"ok":False,"exit_code":130,"stderr":"cancelled"}
        self.project.executor = Slow()
        plan = self.project.plan("campfire","build")
        run = self.project.submit("campfire","build",plan["token"],"campfire")
        self.assertTrue(started.wait(2))
        self.assertTrue(self.project.cancel(run["run_id"])["ok"])
        self.assertEqual(self.wait(run)["status"],"cancelled")

    def test_closed_project_rejects_submit_without_creating_a_run(self):
        plan = self.project.plan("campfire", "build")
        self.project.close()
        with self.assertRaisesRegex(ProjectError, "closing"):
            self.project.submit("campfire", "build", plan["token"], "campfire")
        self.assertEqual(self.project.ledger.list("campfire"), [])

    def test_provided_previews_all_exist_in_artifact_registry(self):
        data = self.project.read_asset("campfire")
        self.assertTrue(set(data["asset"]["preview"]).issubset({a["id"] for a in data["artifacts"]}))


if __name__ == "__main__":
    unittest.main()
