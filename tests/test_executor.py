import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from artflow.executor import CommandExecutor, LOG_TAIL


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.executor=CommandExecutor()
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_code(self,code,timeout=3,response=None,event=None,progress=None):
        return self.executor.run({"argv":[sys.executable,"-c",code],"cwd":str(self.root),
          "response":response or {"format":"exit_code"}},
          {"command":[],"timeout_seconds":timeout},event or threading.Event(),progress or (lambda *_:None))

    def test_streams_output_before_exit(self):
        chunks=[]
        result=self.run_code("import time; print('working',flush=True); time.sleep(.45)",progress=lambda out,err:chunks.append(out))
        self.assertTrue(result["ok"])
        self.assertTrue(any("working" in s for s in chunks))

    def test_json_response_protocol_failure_is_not_success(self):
        result=self.run_code("print('{\"ok\":true}')",response={"format":"json","required":{"schema":"v1"}})
        self.assertFalse(result["ok"])
        self.assertIn("Unsupported response",result["stderr"])

    def test_missing_executable_is_recorded(self):
        result=self.executor.run({"argv":["/no-such-artflow-tool"],"cwd":str(self.root)},
            {"command":[],"timeout_seconds":1},threading.Event(),lambda *_:None)
        self.assertEqual(result["exit_code"],127)

    def test_large_text_output_is_drained_but_only_keeps_a_tail(self):
        result = self.run_code("import sys; sys.stdout.write('x' * 200000)")
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["stdout"].encode()), LOG_TAIL)

    def test_json_report_is_rejected_at_the_capture_limit(self):
        code = "import json; print(json.dumps({'ok': True, 'data': 'x' * 2048}))"
        with patch("artflow.executor.MAX_REPORT", 1024):
            result = self.run_code(code, response={"format": "json"})
        self.assertFalse(result["ok"])
        self.assertIn("exceeds 1024 bytes", result["stderr"])

    def test_detached_descendant_inheriting_pipes_does_not_block_completion(self):
        pidfile = self.root / "detached.pid"
        code = ("import subprocess,sys; from pathlib import Path; "
                "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],"
                "start_new_session=True); "
                f"Path({str(pidfile)!r}).write_text(str(p.pid))")
        started = time.monotonic()
        try:
            result = self.run_code(code)
            self.assertTrue(result["ok"])
            self.assertLess(time.monotonic() - started, 1.5)
        finally:
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_timeout_kills_child_process_group(self):
        pidfile=self.root/"child.pid"
        code=("import subprocess,sys,time; from pathlib import Path; "
              "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
              f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)")
        result=self.run_code(code,timeout=1)
        self.assertEqual(result["exit_code"],124)
        pid=int(pidfile.read_text())
        # A dead child can briefly remain a zombie until adopted/reaped.
        import subprocess
        state=subprocess.run(["ps","-o","stat=","-p",str(pid)],capture_output=True,text=True).stdout.strip()
        self.assertTrue(not state or state.startswith("Z"),state)
