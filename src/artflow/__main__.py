from __future__ import annotations

import argparse
import json
import shutil
import signal
import sys
import time
from importlib.resources import files
from pathlib import Path

from .adapter import Adapter
from .model import ProjectError
from .project import Project
from .server import ArtflowServer


def main():
    parser = argparse.ArgumentParser(description="Artflow local art-production workbench")
    parser.add_argument("command", nargs="?", choices=["serve", "check", "init", "plan", "run"], default="serve")
    parser.add_argument("directory", nargs="?", type=Path, help="Empty destination for init")
    parser.add_argument("--project", type=Path, help="Project manifest")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4179)
    parser.add_argument("--asset")
    parser.add_argument("--action")
    parser.add_argument("--confirm", default="", help="Exact asset ID for a write action")
    args = parser.parse_args()
    try:
        if args.command == "init":
            if not args.directory:
                parser.error("init requires an empty destination directory")
            target = args.directory.resolve()
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ProjectError("Destination must be empty; existing project files will not be overwritten")
            shutil.copytree(str(files("artflow").joinpath("examples/starter")), target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "output", ".artflow-state"))
            print(f"Created starter at {target}\nNext: artflow check --project \"{target / 'project.json'}\"")
            return
        if not args.project:
            parser.error("--project is required; use 'artflow init my-studio' to get started")
        if args.command == "check":
            result = Adapter(args.project).check()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        project = Project(args.project)
        if args.command in {"plan", "run"}:
            if not args.asset or not args.action:
                parser.error("--asset and --action are required")
            try:
                plan = project.plan(args.asset, args.action)
                if args.command == "plan":
                    print(json.dumps(plan, ensure_ascii=False, indent=2))
                    return 0 if plan["ok"] else 1
                with project.ledger.service_lock():
                    project.ledger.recover_interrupted()
                    run = project.submit(args.asset, args.action, plan["token"], args.confirm)
                    while run["status"] in {"queued", "running"}:
                        time.sleep(0.1)
                        run = project.ledger.get(run["run_id"])
                    print(json.dumps(run, ensure_ascii=False, indent=2))
                    return 0 if run["status"] in {"succeeded", "verified"} else 1
            finally:
                project.close()
        try:
            server = ArtflowServer((args.host, args.port), project)
        except BaseException:
            project.close()
            raise
        def stop(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        print(f"Artflow: http://{args.host}:{server.server_port}", flush=True)
        print(f"Project: {project.adapter.config['label']}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except (ProjectError, OSError) as error:
        print(f"Artflow: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
