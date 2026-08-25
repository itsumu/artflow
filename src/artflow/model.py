from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Artifact:
    id: str
    label: str
    kind: str
    path: Path
    required: bool = True

    def to_dict(self, *, exists: bool, sha256: str | None, size: int | None) -> dict:
        return {
            **asdict(self),
            "path": str(self.path),
            "exists": exists,
            "sha256": sha256,
            "size": size,
        }


@dataclass(frozen=True)
class CommandSpec:
    id: str
    label: str
    argv: tuple[str, ...]
    writes_files: bool
