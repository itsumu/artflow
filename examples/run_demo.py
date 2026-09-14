#!/usr/bin/env python3
"""Run the repository's packaged demo without installing Artflow."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
SOURCE = REPOSITORY / "src" / "artflow" / "examples" / "starter"
WORKSPACE = Path(os.environ.get("ARTFLOW_DEMO_WORKSPACE", REPOSITORY / ".artflow-demo")).resolve()


def main() -> int:
    if sys.version_info < (3, 11):
        raise SystemExit("Artflow requires Python 3.11 or newer.")
    informational = any(value in {"-h", "--help", "--version"} for value in sys.argv[1:])
    if not informational and not WORKSPACE.exists():
        shutil.copytree(SOURCE, WORKSPACE)
        print(f"Created demo workspace: {WORKSPACE}")
    sys.path.insert(0, str(REPOSITORY / "src"))
    from artflow.__main__ import main as artflow_main

    if informational:
        return artflow_main()

    sys.argv = [sys.argv[0], "serve", "--project", str(WORKSPACE / "project.json"), *sys.argv[1:]]
    return artflow_main()


if __name__ == "__main__":
    raise SystemExit(main())
