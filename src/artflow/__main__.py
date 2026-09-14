from __future__ import annotations

import argparse
import errno
import json
import platform
import shutil
import signal
import sys
import time
from importlib.resources import files
from pathlib import Path

from . import __version__
from .adapter import check_project
from .model import ProjectError


def port_number(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def doctor(project_path=None):
    python_version = platform.python_version()
    system = platform.system() or sys.platform
    runtime_ok = sys.version_info >= (3, 11)
    platform_ok = system in {"Darwin", "Linux"}
    print(f"Artflow {__version__}")
    print(f"{'✓' if runtime_ok else '✗'} Python {python_version} · {sys.executable}")
    print(f"{'✓' if platform_ok else '✗'} Platform {system}")
    if not project_path:
        print("○ Project not checked · pass --project /path/to/project.json")
        return 0 if runtime_ok and platform_ok else 1

    result = check_project(project_path)
    if result["ok"]:
        print(f"✓ Project {result['project_label']} · {len(result['assets'])} asset(s)")
        print("Ready.")
    else:
        print(f"✗ Project {result.get('project_label') or Path(project_path).resolve()}")
        for error in result["errors"]:
            print(f"  [{error.get('code', 'error')}] {error['message']}")
            resolved = error.get("resolved_path")
            if resolved and resolved not in error["message"]:
                print(f"    Path: {resolved}")
            if error.get("hint"):
                print(f"    Fix: {error['hint']}")
    return 0 if runtime_ok and platform_ok and result["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description="Artflow local art-production workbench")
    parser.add_argument("--version", action="version", version=f"artflow {__version__}")
    parser.add_argument("command", nargs="?", choices=["serve", "check", "doctor", "init", "plan", "run"], default="serve")
    parser.add_argument("directory", nargs="?", type=Path, help="Empty destination for init")
    parser.add_argument("--project", type=Path, help="Project manifest")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost"], default="127.0.0.1")
    parser.add_argument("--port", type=port_number, default=4179)
    parser.add_argument("--asset")
    parser.add_argument("--action")
    parser.add_argument("--confirm", default="", help="Exact asset ID for a write action")
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            return doctor(args.project)
        if args.command == "init":
            if not args.directory:
                parser.error("init requires an empty destination directory")
            target = args.directory.resolve()
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise ProjectError("Destination must be empty; existing project files will not be overwritten")
            shutil.copytree(str(files("artflow").joinpath("examples/starter")), target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "output", ".artflow-state"))
            print(f"Created starter at {target}\nNext: \"{sys.executable}\" -m artflow check --project \"{target / 'project.json'}\"")
            return
        if not args.project:
            parser.error("--project is required; use 'artflow init my-studio' to get started")
        if args.command == "check":
            result = check_project(args.project)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 1
        if platform.system() not in {"Darwin", "Linux"}:
            raise ProjectError("Execution is currently supported on macOS and Linux only; run 'artflow doctor' for details")
        from .ledger import RunBusyError
        from .project import Project
        from .server import ArtflowServer

        if args.command in {"plan", "run"} and (not args.asset or not args.action):
            parser.error("--asset and --action are required")
        project = Project(args.project)
        if args.command in {"plan", "run"}:
            run = None
            try:
                plan = project.plan(args.asset, args.action)
                if args.command == "plan":
                    print(json.dumps(plan, ensure_ascii=False, indent=2))
                    return 0 if plan["ok"] else 1
                stop_requested = False
                interrupted = False

                def request_stop(_signal, _frame):
                    nonlocal stop_requested
                    stop_requested = True

                previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
                try:
                    with project.ledger.service_lock():
                        try:
                            project.ledger.recover_interrupted()
                            if stop_requested:
                                interrupted = True
                            else:
                                run = project.submit(args.asset, args.action, plan["token"], args.confirm)
                                while run["status"] in {"queued", "running"}:
                                    if stop_requested:
                                        interrupted = True
                                        project.cancel(run["run_id"])
                                        break
                                    time.sleep(0.1)
                                    run = project.ledger.get(run["run_id"])
                        except KeyboardInterrupt:
                            interrupted = True
                            if run is not None:
                                project.cancel(run["run_id"])
                        finally:
                            # Keep the project-wide lease until every command has
                            # observed cancellation and exited.
                            project.close()
                except RunBusyError as error:
                    raise ProjectError("Another Artflow service is already using this project's storage.") from error
                finally:
                    signal.signal(signal.SIGTERM, previous_sigterm)
                if run is not None:
                    run = project.ledger.get(run["run_id"])
                    print(json.dumps(run, ensure_ascii=False, indent=2))
                if interrupted:
                    print("Artflow run interrupted.", file=sys.stderr)
                    return 130
                return 0 if run and run["status"] in {"succeeded", "verified"} else 1
            finally:
                project.close()
        try:
            server = ArtflowServer((args.host, args.port), project)
        except RunBusyError as error:
            project.close()
            raise ProjectError("Another Artflow service is already using this project's storage.") from error
        except OSError as error:
            project.close()
            if error.errno == errno.EADDRINUSE:
                alternative = args.port + 1 if args.port < 65535 else 4179
                raise ProjectError(f"Port {args.port} is already in use. Retry with --port {alternative}.") from error
            raise
        except BaseException:
            project.close()
            raise
        def stop(_signal, _frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        print(f"Artflow: http://{args.host}:{server.server_port}", flush=True)
        print(f"Project: {project.adapter.config['label']}", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        print("Artflow stopped.", flush=True)
        return 0
    except (ProjectError, OSError) as error:
        print(f"Artflow: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
