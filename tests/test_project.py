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

    def build(self, aid="sun"):
        plan = self.project.plan(aid, "build")
        return self.wait(self.project.submit(aid, "build", plan["token"], aid))

    def edit_pipeline(self, edit):
        path = self.root / "pipelines.json"
        config = json.loads(path.read_text())
        edit(config["pipelines"]["icon"])
        path.write_text(json.dumps(config))

    def test_standalone_two_assets_run_and_publish(self):
        self.assertTrue(Adapter(self.root / "project.json").check()["ok"])
        for aid in ("sun", "moon"):
            run = self.build(aid)
            self.assertEqual(run["status"], "verified", run)
            self.assertEqual([s["id"] for s in run["steps"]], ["build", "verify"])
            self.assertTrue(run["approvals"][0]["files"]["brief"])
            self.assertTrue((self.root / "output" / f"{aid}.svg").is_file())
            self.assertEqual(self.project.read_asset(aid)["published_state"], "verified")

    def test_new_asset_needs_only_config_and_input(self):
        path = self.root / "project.json"
        config = json.loads(path.read_text())
        config["assets"]["star"] = {"template": "icon", "label": "Star"}
        path.write_text(json.dumps(config))
        shutil.copy2(self.root / "inputs/sun.json", self.root / "inputs/star.json")
        self.assertEqual(self.build("star")["status"], "verified")

    def test_configuration_drives_real_executor_and_timeout(self):
        calls = []
        class Fake:
            def run(_, spec, step, cancelled, progress):
                calls.append((step["command"], step["timeout_seconds"]))
                return {"ok": True, "exit_code": 0}
        self.project.executor = Fake()
        self.edit_pipeline(lambda p: p["steps"][0].update(command=["verify", "{artifact.image}"], timeout_seconds=7))
        (self.root / "output").mkdir()
        (self.root / "output/sun.svg").write_text("existing")
        plan = self.project.plan("sun", "build")
        self.assertEqual(plan["steps"][0]["argv"][-2:], ["verify", str(self.root / "output/sun.svg")])
        run = self.wait(self.project.submit("sun", "build", plan["token"], "sun"))
        self.assertEqual(run["status"], "verified", run)
        self.assertEqual(calls[0], (["verify", str(self.root / "output/sun.svg")], 7))

    def test_missing_input_blocks_before_any_run(self):
        (self.root / "inputs/sun.json").unlink()
        plan = self.project.plan("sun", "build")
        self.assertFalse(plan["ok"])
        with self.assertRaises(ProjectError):
            self.project.submit("sun", "build", plan["token"], "sun")
        self.assertEqual(self.project.ledger.list("sun"), [])

    def test_stale_confirmation_and_wrong_confirmation_rejected(self):
        plan = self.project.plan("sun", "build")
        with self.assertRaises(ProjectError):
            self.project.submit("sun", "build", plan["token"], "moon")
        (self.root / "inputs/sun.json").write_text('{"shape":"sun","color":"#ffffff"}')
        with self.assertRaisesRegex(ProjectError, "changed"):
            self.project.submit("sun", "build", plan["token"], "sun")
        self.assertFalse((self.root / "output").exists())

    def test_changed_input_invalidates_downstream_and_old_publication(self):
        self.build()
        (self.root / "inputs/sun.json").write_text('{"shape":"sun","color":"#ffffff"}')
        data = self.project.read_asset("sun")
        self.assertEqual(data["step_states"], {"build":"stale", "verify":"stale"})
        self.assertEqual(data["published_state"], "stale")
        self.assertFalse(self.project.plan("sun", "verify")["ok"])
        self.assertEqual(self.build()["status"], "verified")

    def test_changing_tool_invalidates_old_results(self):
        self.build()
        with (self.root / "make_asset.py").open("a") as stream:
            stream.write("\n# a new tool version\n")
        self.assertEqual(self.project.read_asset("sun")["step_states"]["build"], "stale")

    def test_candidate_like_action_is_durable_without_publishing(self):
        self.edit_pipeline(lambda p: p["actions"].update(candidate={"label":"Candidate","steps":["build"]}))
        plan = self.project.plan("sun", "candidate")
        run = self.wait(self.project.submit("sun", "candidate", plan["token"], "sun"))
        self.assertEqual(run["status"], "succeeded")
        self.assertTrue(run["steps"][0]["inputs"])
        self.assertTrue(run["steps"][0]["files"]["image"])
        self.assertEqual(self.project.read_asset("sun")["published_state"], "not_run")

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
        plan = self.project.plan("sun","build")
        run = self.project.submit("sun","build",plan["token"],"sun")
        self.assertTrue(started.wait(2))
        self.assertTrue(self.project.cancel(run["run_id"])["ok"])
        self.assertEqual(self.wait(run)["status"],"cancelled")

    def test_provided_previews_all_exist_in_artifact_registry(self):
        data = self.project.read_asset("sun")
        self.assertTrue(set(data["asset"]["preview"]).issubset({a["id"] for a in data["artifacts"]}))


if __name__ == "__main__":
    unittest.main()
