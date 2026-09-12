"""Shared errors and deterministic identities."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


class ProjectError(ValueError):
    pass


def now():
    return datetime.now(UTC).isoformat()


def read_json(path: Path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ProjectError(f"{path}: {error}") from error
    if not isinstance(data, dict):
        raise ProjectError(f"{path}: expected a JSON object")
    return data


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_hash(path: Path):
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
