"""Storage capacity planning for governed downloads and workflow artifacts."""
from __future__ import annotations
import shutil
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class StoragePlan:
    required_bytes: int
    available_bytes: int
    reserve_bytes: int
    status: str
    reason: str

def plan_download(*, destination: str | Path, artifact_bytes: int, overhead_ratio: float = 0.20, reserve_bytes: int = 1_073_741_824) -> StoragePlan:
    if artifact_bytes < 0:
        raise ValueError("artifact_bytes must be non-negative")
    if overhead_ratio < 0:
        raise ValueError("overhead_ratio must be non-negative")
    path = Path(destination)
    path.mkdir(parents=True, exist_ok=True)
    available = int(shutil.disk_usage(path).free)
    required = int(artifact_bytes * (1.0 + overhead_ratio)) + int(reserve_bytes)
    if available >= required:
        status = "READY"
        reason = "Sufficient free space for the staged artifact, temporary overhead, and reserve."
    else:
        status = "SPACE_REQUIRED"
        reason = f"Additional storage required: {required - available} bytes."
    return StoragePlan(required, available, int(reserve_bytes), status, reason)

def format_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(max(0, value))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
