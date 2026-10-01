"""Resolve lab-local resources without silently changing provenance."""
from __future__ import annotations
import shutil
from pathlib import Path

class LocalResourceNotFound(RuntimeError):
    pass

def resolve_local_path(*, configured_path: str | None, executable: str | None = None) -> Path:
    candidates: list[Path] = []
    if configured_path:
        candidates.append(Path(configured_path))
    if executable:
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.exists() and (candidate.is_file() or candidate.is_dir()):
            return candidate.resolve()
    description = configured_path or executable or "requested resource"
    raise LocalResourceNotFound(f"Local resource not found: {description}")

def resolve_or_require_staging(*, configured_path: str | None, executable: str | None = None, allow_staging: bool = True) -> dict[str, object]:
    try:
        path = resolve_local_path(configured_path=configured_path, executable=executable)
    except LocalResourceNotFound as exc:
        if allow_staging:
            return {"status": "STAGING_REQUIRED", "message": str(exc)}
        return {"status": "NOT_AVAILABLE", "message": str(exc)}
    return {"status": "AVAILABLE", "path": str(path)}
