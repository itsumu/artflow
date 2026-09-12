"""Generic local command executor. Adapters own argv and response conventions."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import time
from typing import Protocol

from .model import now

MAX_REPORT = 8 * 1024 * 1024
LOG_TAIL = 64000


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
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                process = subprocess.Popen(argv, cwd=spec["cwd"], env=env,
                    stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
            except OSError as error:
                return {**result, "stderr": str(error), "stdout": "", "exit_code": 127,
                        "finished_at": now(), "duration_ms": round((time.monotonic()-start)*1000)}
            status = None
            last_progress = 0.0
            try:
                while process.poll() is None:
                    if cancelled.is_set():
                        status = "cancelled"
                        break
                    if time.monotonic() - start > step["timeout_seconds"]:
                        status = "timeout"
                        break
                    if time.monotonic() - last_progress > 0.3:
                        progress(self.tail(out), self.tail(err))
                        last_progress = time.monotonic()
                    time.sleep(0.05)
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
            stdout, stderr = self.tail(out), self.tail(err)
            code = 130 if status == "cancelled" else 124 if status == "timeout" else process.returncode
            result.update(stdout=stdout, stderr=stderr, exit_code=code,
                          finished_at=now(), duration_ms=round((time.monotonic()-start)*1000))
            if status:
                result["stderr"] += f"\n{status}"
                return result
            response = spec.get("response", {})
            ok = code == 0
            if response.get("format", "exit_code") == "json":
                out.seek(0, 2)
                length = out.tell()
                out.seek(0)
                try:
                    if length > MAX_REPORT:
                        raise ValueError("JSON report exceeds 8 MiB")
                    report = json.loads(out.read().decode("utf-8"))
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
    def tail(stream):
        # pread avoids changing the child's shared file offset.
        size = os.fstat(stream.fileno()).st_size
        return os.pread(stream.fileno(), min(size, LOG_TAIL), max(0, size-LOG_TAIL)).decode("utf-8", errors="replace")
