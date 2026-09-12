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
        self.assertEqual([a["id"] for a in self.request("/api/project")["assets"]],["sun","moon"])
        self.assertEqual(self.request("/api/assets/moon")["asset"]["label"],"月亮")

    def test_write_requires_session_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.request("/api/assets/sun/actions/build/plan",{},token=False)
        self.assertEqual(cm.exception.code,403)
        cm.exception.close()

    def test_plan_submit_poll_and_artifact(self):
        plan=self.request("/api/assets/moon/actions/build/plan",{})
        run=self.request("/api/assets/moon/actions/build/run",{"token":plan["token"],"confirmation":"moon"})
        deadline=time.monotonic()+5
        while run["status"] in {"queued","running"} and time.monotonic()<deadline:
            time.sleep(.05)
            run=self.request("/api/runs/"+run["run_id"])
        self.assertEqual(run["status"],"verified",run)
        with urllib.request.urlopen(self.url+"/artifact/moon/image") as response:
            self.assertIn(b"<svg",response.read())
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
