from __future__ import annotations

import importlib.util
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY / "scripts" / "verify_wheel.py"
SPEC = importlib.util.spec_from_file_location("artflow_verify_wheel", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY_WHEEL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_WHEEL)


class VerifyWheelTests(unittest.TestCase):
    def _write_wheel(
        self,
        path: Path,
        *,
        replacements: dict[str, bytes] | None = None,
        extras: dict[str, bytes] | None = None,
    ) -> None:
        source_root = REPOSITORY / "src" / "artflow"
        members = {
            "artflow/" + source.relative_to(source_root).as_posix(): source.read_bytes()
            for source in source_root.rglob("*")
            if source.is_file()
            and not any(
                part in {"__pycache__", ".artflow-state", "output"}
                for part in source.relative_to(source_root).parts
            )
            and source.suffix != ".pyc"
        }
        members.update(replacements or {})
        members.update(extras or {})
        project = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())["project"]
        members[f"artflow-{project['version']}.dist-info/METADATA"] = (
            f"Metadata-Version: 2.4\nName: artflow\nVersion: {project['version']}\n"
        ).encode()
        with zipfile.ZipFile(path, "w") as archive:
            for name, contents in members.items():
                archive.writestr(name, contents)

    def test_accepts_package_that_matches_source_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "artflow-0.2.0-py3-none-any.whl"
            self._write_wheel(wheel)

            self.assertEqual(VERIFY_WHEEL.verify(wheel), [])

    def test_rejects_packaged_file_with_stale_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "artflow-0.2.0-py3-none-any.whl"
            self._write_wheel(
                wheel,
                replacements={"artflow/__main__.py": b"# stale package contents\n"},
            )

            errors = VERIFY_WHEEL.verify(wheel)

            self.assertTrue(
                any(
                    "Wheel files differ from current source: artflow/__main__.py" in error
                    for error in errors
                ),
                errors,
            )

    def test_rejects_ds_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "artflow-0.2.0-py3-none-any.whl"
            self._write_wheel(
                wheel,
                extras={"artflow/web/.DS_Store": b"finder metadata"},
            )

            errors = VERIFY_WHEEL.verify(wheel)

            self.assertTrue(
                any(
                    "Stale or generated files" in error and ".DS_Store" in error
                    for error in errors
                ),
                errors,
            )


if __name__ == "__main__":
    unittest.main()
