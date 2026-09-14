import json
import shutil
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from importlib.resources import files
from artflow import __version__
from artflow.project import Project
from artflow.server import ArtflowServer
from artflow.ledger import RunBusyError


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        shutil.copytree(str(files("artflow").joinpath("examples/starter")),self.root,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__",".artflow-state","output"))
        self.project=Project(self.root/"project.json")
        self.server=ArtflowServer(("127.0.0.1",0),self.project)
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.worker.start()
        self.url=f"http://127.0.0.1:{self.server.server_port}"
        self.token=self.request("/api/project")["token"]

    def tearDown(self):
        self.server.shutdown();self.worker.join()
        self.server.server_close();self.tmp.cleanup()

    def request(self,path,payload=None,token=True):
        headers={"X-Artflow-Token":self.token} if token and hasattr(self,"token") else {}
        data=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request(self.url+path,data=data,headers=headers)
        with urllib.request.urlopen(req,timeout=5) as response:
            return json.loads(response.read())

    def test_dynamic_assets_and_preview_ids(self):
        self.assertEqual([a["id"] for a in self.request("/api/project")["assets"]],["campfire","crystal"])
        self.assertEqual(self.request("/api/assets/crystal")["asset"]["label"],"Crystal")

    def test_health_reports_service_version_and_project(self):
        health = self.request("/api/health", token=False)
        self.assertEqual(health, {"ok": True, "service": "artflow", "version": __version__,
                                  "project_id": "pixel_sprite_demo"})

    def test_check_reloads_changed_and_invalid_configuration(self):
        manifest = self.root / "project.json"
        config = json.loads(manifest.read_text())
        config["executors"]["python"]["argv"][0] = "/missing-artflow-tool"
        manifest.write_text(json.dumps(config))
        result = self.request("/api/check", token=False)
        self.assertFalse(result["ok"])
        self.assertTrue(any(item["code"] == "missing_executable" for item in result["errors"]))
        manifest.write_text("{")
        result = self.request("/api/check", token=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["code"], "invalid_adapter")

    def test_write_requires_session_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.request("/api/assets/campfire/actions/build/plan",{},token=False)
        self.assertEqual(cm.exception.code,403)
        cm.exception.close()

    def test_rejects_non_local_host_and_static_path_traversal(self):
        request = urllib.request.Request(self.url + "/api/health", headers={"Host": "example.com"})
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.url + "/%2e%2e/pyproject.toml", timeout=5)
        self.assertEqual(context.exception.code, 403)
        context.exception.close()

    def test_non_media_artifact_is_download_only(self):
        with urllib.request.urlopen(self.url + "/artifact/campfire/recipe") as response:
            self.assertEqual(response.headers["Content-Disposition"], "attachment")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_plan_submit_poll_and_artifact(self):
        plan=self.request("/api/assets/crystal/actions/build/plan",{})
        run=self.request("/api/assets/crystal/actions/build/run",{"token":plan["token"],"confirmation":"crystal"})
        deadline=time.monotonic()+5
        while run["status"] in {"queued","running"} and time.monotonic()<deadline:
            time.sleep(.05)
            run=self.request("/api/runs/"+run["run_id"])
        self.assertEqual(run["status"],"verified",run)
        with urllib.request.urlopen(self.url+"/artifact/crystal/image") as response:
            self.assertTrue(response.read().startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn("sandbox",response.headers["Content-Security-Policy"])

    def test_second_service_does_not_interrupt_first(self):
        second=Project(self.root/"project.json")
        try:
            with self.assertRaises(RunBusyError):
                ArtflowServer(("127.0.0.1",0),second)
            self.assertTrue(self.request("/api/project")["assets"])
        finally:
            second.close()

    def test_packaged_frontend_is_served(self):
        with urllib.request.urlopen(self.url+"/") as response:
            self.assertIn(b"assetNav",response.read())
        with urllib.request.urlopen(self.url+"/app.js") as response:
            self.assertIn(b"prepareAction",response.read())
