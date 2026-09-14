#!/usr/bin/env python3
"""Verify that an Artflow wheel contains one clean, current starter."""
from __future__ import annotations

import argparse
import sys
import tomllib
import zipfile
from pathlib import Path


REQUIRED = {
    "artflow/__init__.py",
    "artflow/__main__.py",
    "artflow/web/index.html",
    "artflow/web/app.js",
    "artflow/web/styles.css",
    "artflow/examples/starter/project.json",
    "artflow/examples/starter/pipelines.json",
    "artflow/examples/starter/make_asset.py",
    "artflow/examples/starter/README.md",
    "artflow/examples/starter/.gitignore",
    "artflow/examples/starter/inputs/campfire.json",
    "artflow/examples/starter/inputs/crystal.json",
}
FORBIDDEN_PARTS = {
    "__pycache__",
    ".artflow-state",
    ".DS_Store",
    "output",
    "sun.json",
    "moon.json",
}


def verify(path: Path) -> list[str]:
    errors = []
    repository = Path(__file__).resolve().parents[1]
    source_root = repository / "src" / "artflow"
    expected_package = {
        "artflow/" + source.relative_to(source_root).as_posix()
        for source in source_root.rglob("*")
        if source.is_file()
        and not any(part in {"__pycache__", ".artflow-state", "output"}
                    for part in source.relative_to(source_root).parts)
        and source.suffix != ".pyc"
    }
    if not path.is_file():
        return [f"Wheel does not exist: {path}"]
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            missing = sorted(REQUIRED - names)
            if missing:
                errors.append("Missing packaged files: " + ", ".join(missing))
            packaged = {name for name in names if name.startswith("artflow/")}
            missing_source = sorted(expected_package - packaged)
            extra_package = sorted(packaged - expected_package)
            if missing_source:
                errors.append("Source files missing from wheel: " + ", ".join(missing_source))
            if extra_package:
                errors.append("Wheel contains files absent from source: " + ", ".join(extra_package))
            changed_package = sorted(
                name
                for name in expected_package & packaged
                if archive.read(name)
                != (source_root / name.removeprefix("artflow/")).read_bytes()
            )
            if changed_package:
                errors.append(
                    "Wheel files differ from current source: " + ", ".join(changed_package)
                )
            stale = sorted(name for name in names
                           if any(part in FORBIDDEN_PARTS for part in Path(name).parts))
            if stale:
                errors.append("Stale or generated files are packaged: " + ", ".join(stale))
            metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metadata_names) != 1:
                errors.append("Wheel must contain exactly one METADATA file")
            else:
                metadata = archive.read(metadata_names[0]).decode("utf-8")
                project = tomllib.loads((repository / "pyproject.toml").read_text())["project"]
                if f"Name: {project['name']}\n" not in metadata:
                    errors.append("Wheel distribution name does not match pyproject.toml")
                if f"Version: {project['version']}\n" not in metadata:
                    errors.append("Wheel version does not match pyproject.toml")
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as error:
        errors.append(f"Invalid wheel: {error}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args(argv)
    errors = verify(args.wheel)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"Verified clean Artflow wheel: {args.wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
