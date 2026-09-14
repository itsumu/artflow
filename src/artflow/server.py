from __future__ import annotations

import json
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import __version__
from .model import ProjectError
from .project import Project


class ArtflowServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, project: Project):
        self.project = project
        self.web_root = Path(str(files("artflow").joinpath("web"))).resolve()
        self.token = secrets.token_urlsafe(32)
        self._lease = project.ledger.service_lock()
        self._lease.__enter__()
        try:
            project.ledger.recover_interrupted()
            super().__init__(address, ArtflowHandler)
        except BaseException:
            self._lease.__exit__(None, None, None)
            raise

    def server_close(self):
        super().server_close()
        self.project.close()
        self._lease.__exit__(None, None, None)


class ArtflowHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request(False)

    def do_POST(self):
        self.handle_request(True)

    def handle_request(self, post):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in {"localhost", "127.0.0.1"}:
            self.send_error(403, "Local host required")
            return
        if post and not secrets.compare_digest(self.headers.get("X-Artflow-Token", ""), self.server.token):
            self.send_error(403, "Refresh the local workbench before submitting")
            return
        parts = [unquote(p) for p in urlparse(self.path).path.strip("/").split("/") if p]
        project = self.server.project
        try:
            if not post and parts == ["api", "health"]:
                return self.json({"ok": True, "service": "artflow", "version": __version__,
                                  "project_id": project.adapter.config["project_id"]})
            if not post and parts == ["api", "project"]:
                return self.json({**project.assets(), "token": self.server.token})
            if not post and parts == ["api", "check"]:
                return self.json(project.check())
            if len(parts) >= 3 and parts[:2] == ["api", "assets"]:
                aid = parts[2]
                if not post and len(parts) == 3:
                    return self.json(project.read_asset(aid))
                if not post and len(parts) == 4 and parts[3] == "runs":
                    return self.json({"runs": project.ledger.list(aid)})
                if post and len(parts) == 6 and parts[3] == "actions":
                    action, verb = parts[4:]
                    payload = self.request_json()
                    if verb == "plan":
                        return self.json(project.plan(aid, action))
                    if verb == "run":
                        run = project.submit(aid, action, payload.get("token"), payload.get("confirmation", ""))
                        return self.json(run, 202)
            if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
                rid = parts[2]
                if not post and len(parts) == 3:
                    return self.json(project.ledger.get(rid))
                if post and len(parts) == 4 and parts[3] == "cancel":
                    return self.json(project.cancel(rid))
            if not post and len(parts) == 3 and parts[0] == "artifact":
                asset = project.resolve(parts[1])
                artifact = asset["artifacts"].get(parts[2])
                if not artifact:
                    raise ProjectError("Unknown artifact")
                return self.file(Path(artifact["path"]), artifact=True)
            if not post and (not parts or parts[0] != "api"):
                path = (self.server.web_root / ("/".join(parts) if parts else "index.html")).resolve()
                if not path.is_relative_to(self.server.web_root):
                    return self.send_error(403)
                return self.file(path)
            self.send_error(404)
        except (ProjectError, OSError, KeyError, TypeError, ValueError) as error:
            self.json({"ok": False, "error": str(error)}, 400)

    def request_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > 65536:
            raise ProjectError("Request too large")
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ProjectError("Expected JSON object")
        return payload

    def file(self, path, artifact=False):
        if not path.is_file():
            return self.send_error(404)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if artifact:
            self.send_header("Content-Security-Policy", "sandbox; default-src 'none'; style-src 'unsafe-inline'")
            if not mime.startswith(("image/", "audio/", "video/")):
                self.send_header("Content-Disposition", "attachment")
        else:
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            with path.open("rb") as stream:
                while chunk := stream.read(65536):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def json(self, value, status=200):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass
