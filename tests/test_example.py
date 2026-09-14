import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ExampleLauncherTests(unittest.TestCase):
    def test_repository_demo_starts_without_site_packages(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="artflow-example-") as temporary:
            workspace = Path(temporary) / "workspace"
            environment = {**os.environ, "ARTFLOW_DEMO_WORKSPACE": str(workspace), "PYTHONDONTWRITEBYTECODE": "1"}
            result = subprocess.run(
                [sys.executable, "-S", str(repository / "examples/run_demo.py"), "--help"],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Artflow local art-production workbench", result.stdout)
            self.assertFalse(workspace.exists(), "--help must not create a demo workspace")

            result = subprocess.run(
                [sys.executable, "-S", str(repository / "examples/run_demo.py"), "--version"],
                cwd=repository,
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("artflow 0.2.0", result.stdout)
            self.assertFalse(workspace.exists(), "--version must not create a demo workspace")


if __name__ == "__main__":
    unittest.main()
