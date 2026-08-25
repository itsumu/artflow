from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .project import ProjectError, UnamedTacticsProject


class ArtflowServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], project: UnamedTacticsProject, web_root: Path):
        super().__init__(server_address, ArtflowHandler)
        self.project = project
        self.web_root = web_root


class ArtflowHandler(BaseHTTPRequestHandler):
    server: ArtflowServer

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/asset/fire_tower":
            self._json(self.server.project.read_asset("fire_tower"))
        elif parsed.path == "/api/dry-run/fire_tower":
            self._json(self.server.project.dry_run("fire_tower"))
        elif parsed.path == "/api/pipeline-check/fire_tower":
            self._json(self.server.project.validate_pipeline("fire_tower"))
        elif parsed.path == "/api/diagnostics/fire_tower":
            self._json(self.server.project.diagnose_environment("fire_tower"))
        elif parsed.path == "/api/snapshot/fire_tower":
            self._json(self.server.project.snapshot("fire_tower"))
        elif parsed.path == "/api/runs/fire_tower":
            self._json(self.server.project.latest_run("fire_tower"))
        elif parsed.path.startswith("/artifact/"):
            self._artifact(unquote(parsed.path.removeprefix("/artifact/")))
        else:
            self._static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in {
            "/api/verify/fire_tower", "/api/verify-visuals/fire_tower", "/api/export/fire_tower",
            "/api/retry-preflight/fire_tower", "/api/candidate-normalize/fire_tower",
            "/api/candidate-source/fire_tower", "/api/candidate-promote/fire_tower",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            if path.startswith("/api/candidate-"):
                payload = self._request_json()
                if payload.get("confirmation") != "fire_tower":
                    self._json({"ok": False, "error": "Exact asset confirmation is required."}, status=HTTPStatus.FORBIDDEN)
                    return
                expected_sha256 = str(payload.get("artifact_sha256", ""))
                if path == "/api/candidate-normalize/fire_tower":
                    result = self.server.project.normalize_building_candidate("fire_tower", expected_sha256)
                elif path == "/api/candidate-source/fire_tower":
                    result = self.server.project.build_building_source_candidate("fire_tower", expected_sha256)
                else:
                    result = self.server.project.promote_building_source_candidate("fire_tower", expected_sha256)
            elif path == "/api/export/fire_tower":
                payload = self._request_json()
                if payload.get("confirmation") != "fire_tower":
                    self._json({"ok": False, "error": "Exact asset confirmation is required before export."}, status=HTTPStatus.FORBIDDEN)
                    return
                result = self.server.project.export_building("fire_tower")
            elif path == "/api/retry-preflight/fire_tower":
                result = self.server.project.retry_export_from_preflight("fire_tower")
            elif path == "/api/verify-visuals/fire_tower":
                result = self.server.project.verify_visuals()
            else:
                result = self.server.project.verify_buildings()
            self._json(result)
        except (OSError, ProjectError) as error:
            self._json({"ok": False, "error": str(error)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _request_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
            raise ProjectError(f"Invalid JSON request: {error}") from error
        if not isinstance(payload, dict):
            raise ProjectError("Expected a JSON object.")
        return payload

    def _artifact(self, artifact_id: str) -> None:
        artifact = next((entry for entry in self.server.project.artifacts("fire_tower") if entry.id == artifact_id), None)
        if artifact is None or not artifact.path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(artifact.path)

    def _static(self, path: str) -> None:
        target = "index.html" if path in {"", "/"} else path.lstrip("/")
        file_path = (self.server.web_root / target).resolve()
        if self.server.web_root not in file_path.parents and file_path != self.server.web_root:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not file_path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._file(file_path)

    def _file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, value: dict, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, _format: str, *_args: object) -> None:
        return
