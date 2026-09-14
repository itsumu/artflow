"""Generic local command executor. Adapters own argv and response conventions."""
from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import time
from typing import Protocol

from .model import now

MAX_REPORT = 8 * 1024 * 1024
LOG_TAIL = 64000


class BoundedCapture:
    """Continuously drain a pipe while retaining only bounded output."""

    def __init__(self, full_limit=0):
        self.full_limit = full_limit
        self.total = 0
        self.tail_bytes = bytearray()
        self.full_bytes = bytearray()

    def append(self, data):
        self.total += len(data)
        self.tail_bytes.extend(data)
        if len(self.tail_bytes) > LOG_TAIL:
            del self.tail_bytes[:-LOG_TAIL]
        if self.full_limit and len(self.full_bytes) < self.full_limit:
            remaining = self.full_limit - len(self.full_bytes)
            self.full_bytes.extend(data[:remaining])

    def tail(self):
        return bytes(self.tail_bytes).decode("utf-8", errors="replace")

    def full(self):
        if self.total > self.full_limit:
            limit = (f"{self.full_limit // (1024 * 1024)} MiB"
                     if self.full_limit % (1024 * 1024) == 0 else f"{self.full_limit} bytes")
            raise ValueError(f"JSON report exceeds {limit}")
        return bytes(self.full_bytes)


class Executor(Protocol):
    def run(self, spec: dict, step: dict, cancelled, progress) -> dict: ...


class CommandExecutor:
    def run(self, spec, step, cancelled, progress):
        argv = [*spec["argv"], *step["command"]]
        started = now()
        start = time.monotonic()
        env = {key: os.environ[key] for key in spec.get("inherit_env", ["PATH", "HOME", "TMPDIR", "LANG", "LC_ALL"])
               if key in os.environ}
        env.update(spec.get("env", {}))
        env.setdefault("PYTHONUNBUFFERED", "1")
        result = {"command": argv, "started_at": started, "ok": False}
        response = spec.get("response", {})
        capture_report = response.get("format", "exit_code") == "json"
        stdout_capture = BoundedCapture(MAX_REPORT if capture_report else 0)
        stderr_capture = BoundedCapture()
        try:
            process = subprocess.Popen(argv, cwd=spec["cwd"], env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True, bufsize=0)
        except OSError as error:
            return {**result, "stderr": str(error), "stdout": "", "exit_code": 127,
                    "finished_at": now(), "duration_ms": round((time.monotonic()-start)*1000)}

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, stdout_capture)
        selector.register(process.stderr, selectors.EVENT_READ, stderr_capture)
        status = None
        last_progress = 0.0
        try:
            while True:
                self.pump(selector, 0.05)
                if process.poll() is not None:
                    break
                if cancelled.is_set():
                    status = "cancelled"
                    break
                if time.monotonic() - start > step["timeout_seconds"]:
                    status = "timeout"
                    break
                if time.monotonic() - last_progress > 0.3:
                    progress(stdout_capture.tail(), stderr_capture.tail())
                    last_progress = time.monotonic()
        finally:
            if status or process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
                except ProcessLookupError:
                    pass
                # Also stop descendants if the parent exited after SIGTERM.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            drain_deadline = time.monotonic() + 0.05
            while time.monotonic() < drain_deadline and self.pump(selector, 0):
                pass
            self.close_pipes(selector)

        stdout, stderr = stdout_capture.tail(), stderr_capture.tail()
        code = 130 if status == "cancelled" else 124 if status == "timeout" else process.returncode
        result.update(stdout=stdout, stderr=stderr, exit_code=code,
                      finished_at=now(), duration_ms=round((time.monotonic()-start)*1000))
        if status:
            result["stderr"] += f"\n{status}"
            return result
        ok = code == 0
        if capture_report:
            try:
                report = json.loads(stdout_capture.full().decode("utf-8"))
                if not isinstance(report, dict):
                    raise ValueError("Expected JSON object")
                for key, value in response.get("required", {}).items():
                    if report.get(key) != value:
                        raise ValueError(f"Unsupported response field {key}")
                if report.get(response.get("success_field", "ok")) is not True:
                    ok = False
                result["report"] = report
            except (ValueError, UnicodeDecodeError) as error:
                ok = False
                result["stderr"] += f"\nInvalid machine report: {error}"
        result["ok"] = ok
        return result

    @staticmethod
    def pump(selector, timeout):
        events = selector.select(timeout)
        for key, _events in events:
            try:
                data = os.read(key.fileobj.fileno(), 65536)
            except BlockingIOError:
                continue
            if data:
                key.data.append(data)
            else:
                selector.unregister(key.fileobj)
                key.fileobj.close()
        return bool(events)

    @staticmethod
    def close_pipes(selector):
        for key in list(selector.get_map().values()):
            selector.unregister(key.fileobj)
            key.fileobj.close()
        selector.close()
