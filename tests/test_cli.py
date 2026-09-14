from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
import urllib.request
from importlib.resources import files
from pathlib import Path

from artflow import __version__
from artflow.ledger import RunLedger


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="artflow-cli-")
        self.root = Path(self.temporary.name)
        shutil.copytree(str(files("artflow").joinpath("examples/starter")), self.root,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", ".artflow-state", "output"))
        self.repository = Path(__file__).resolve().parents[1]
        self.environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        source = str(self.repository / "src")
        self.environment["PYTHONPATH"] = source + os.pathsep + self.environment.get("PYTHONPATH", "")

    def tearDown(self):
        self.temporary.cleanup()

    def run_cli(self, *arguments, timeout=10):
        return subprocess.run([sys.executable, "-m", "artflow", *arguments],
                              cwd=self.repository, env=self.environment,
                              capture_output=True, text=True, timeout=timeout)

    def test_version_matches_package_metadata(self):
        metadata = tomllib.loads((self.repository / "pyproject.toml").read_text())
        self.assertEqual(metadata["project"]["version"], __version__)
        result = self.run_cli("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"artflow {__version__}")

    def test_doctor_explains_ready_and_missing_input(self):
        project = str(self.root / "project.json")
        result = self.run_cli("doctor", "--project", project)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Ready.", result.stdout)
        (self.root / "inputs/campfire.json").unlink()
        result = self.run_cli("doctor", "--project", project)
        self.assertEqual(result.returncode, 1)
        self.assertIn("[missing_input]", result.stdout)
        self.assertIn(str(self.root / "inputs/campfire.json"), result.stdout)

    def test_port_conflict_has_actionable_error(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            result = self.run_cli("serve", "--project", str(self.root / "project.json"),
                                  "--port", str(port))
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"Port {port} is already in use", result.stderr)
        self.assertIn("--port", result.stderr)

    def test_project_service_conflict_has_actionable_error(self):
        ledger = RunLedger(self.root / ".artflow-state")
        with ledger.service_lock():
            result = self.run_cli("serve", "--project", str(self.root / "project.json"),
                                  "--port", "0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Another Artflow service", result.stderr)

    def test_sigterm_stops_service_and_releases_project(self):
        process = subprocess.Popen(
            [sys.executable, "-m", "artflow", "serve", "--project",
             str(self.root / "project.json"), "--port", "0"],
            cwd=self.repository, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            address_line = process.stdout.readline().strip()
            self.assertTrue(address_line.startswith("Artflow: http://"), address_line)
            address = address_line.removeprefix("Artflow: ")
            with urllib.request.urlopen(address + "/api/health", timeout=5) as response:
                self.assertTrue(response.read())
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn("Artflow stopped.", stdout)
            with RunLedger(self.root / ".artflow-state").service_lock():
                pass
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_sigterm_cancels_run_before_releasing_project(self):
        pidfile = self.root / "tool.pid"
        tool = self.root / "long_tool.py"
        tool.write_text(
            "import os, sys, time\n"
            "from pathlib import Path\n"
            f"Path({str(pidfile)!r}).write_text(str(os.getpid()))\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        manifest_path = self.root / "project.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["executors"]["python"]["argv"] = [sys.executable, str(tool)]
        manifest["executors"]["python"]["version_files"] = [str(tool)]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        process = subprocess.Popen(
            [sys.executable, "-m", "artflow", "run", "--project", str(manifest_path),
             "--asset", "campfire", "--action", "build", "--confirm", "campfire"],
            cwd=self.repository, env=self.environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            deadline = time.monotonic() + 5
            while not pidfile.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.03)
            self.assertTrue(pidfile.exists(), process.stderr.read() if process.poll() is not None else "tool did not start")
            tool_pid = int(pidfile.read_text())
            process.terminate()
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130, (stdout, stderr))
            self.assertIn("Artflow run interrupted.", stderr)
            with self.assertRaises(ProcessLookupError):
                os.kill(tool_pid, 0)
            ledger = RunLedger(self.root / ".artflow-state")
            self.assertTrue(ledger.list("campfire"))
            self.assertNotIn(ledger.list("campfire")[0]["status"], {"queued", "running"})
            with ledger.service_lock():
                pass
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

    def test_invalid_port_is_rejected_before_startup(self):
        result = self.run_cli("serve", "--project", str(self.root / "project.json"),
                              "--port", "70000")
        self.assertEqual(result.returncode, 2)
        self.assertIn("between 0 and 65535", result.stderr)


if __name__ == "__main__":
    unittest.main()
