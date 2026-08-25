from __future__ import annotations

import argparse
from pathlib import Path

from .project import UnamedTacticsProject
from .server import ArtflowServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the local Artflow workbench.")
    parser.add_argument("--project", required=True, type=Path, help="Path to a project.json adapter.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4179, type=int)
    args = parser.parse_args()
    web_root = Path(__file__).resolve().parents[2] / "web"
    project = UnamedTacticsProject(args.project)
    server = ArtflowServer((args.host, args.port), project, web_root)
    print(f"Artflow: http://{args.host}:{args.port}")
    print(f"Project: {project.label}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
