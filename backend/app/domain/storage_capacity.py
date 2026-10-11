"""Filesystem capacity inspection and conservative analysis preflight estimates.

These estimates are configurable planning guards, not disk reservations or a
promise of supported maximum VCF size. Concurrent workloads can consume space
after a successful preflight; deployments must monitor disk and test concurrency.
"""
from __future__ import annotations

import math
import os
import shutil
from pathlib import Path
from typing import Any

from backend.app.config import settings


def inspect_storage_root(label: str, raw_path: str) -> dict[str, Any]:
    path = Path(raw_path).expanduser().resolve(strict=False)
    result: dict[str, Any] = {
        "label": label,
        "path": str(path),
        "exists": path.is_dir(),
        "writable": False,
        "total_bytes": None,
        "used_bytes": None,
        "free_bytes": None,
        "error_code": None,
        "error_message": None,
        "_device_id": None,
    }
    if not path.is_dir():
        result["error_code"] = "STORAGE_PATH_MISSING"
        result["error_message"] = "Configured storage directory does not exist or is not a directory."
        return result
    try:
        result["writable"] = os.access(path, os.W_OK | os.X_OK)
        usage = shutil.disk_usage(path)
        result.update({
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "_device_id": path.stat().st_dev,
        })
        if not result["writable"]:
            result["error_code"] = "STORAGE_PATH_NOT_WRITABLE"
            result["error_message"] = "Service process cannot write to the configured storage directory."
    except OSError as exc:
        result["error_code"] = "STORAGE_CAPACITY_UNAVAILABLE"
        result["error_message"] = f"Filesystem capacity could not be inspected: {type(exc).__name__}"
    return result


def inspect_deployment_capacity() -> dict[str, Any]:
    roots = [
        inspect_storage_root("artifact_store", settings.artifact_root),
        inspect_storage_root("worker_scratch", settings.worker_scratch_root),
        inspect_storage_root("resource_cache", settings.resource_cache_root),
    ]
    public_roots = [{key: value for key, value in root.items() if not key.startswith("_")} for root in roots]
    issues = [
        {"code": root["error_code"], "message": root["error_message"], "storage": root["label"]}
        for root in roots if root["error_code"]
    ]
    return {
        "status": "BLOCKED" if issues else "READY",
        "capacity_preflight_enabled": settings.storage_capacity_preflight_enabled,
        "max_artifact_upload_bytes": settings.max_artifact_upload_bytes,
        "resource_staging_max_bytes": settings.resource_staging_max_bytes,
        "reservation_supported": False,
        "roots": public_roots,
        "issues": issues,
    }


def preflight_analysis_capacity(input_size_bytes: int) -> dict[str, Any]:
    if not settings.storage_capacity_preflight_enabled:
        return {
            "status": "NOT_CONFIGURED",
            "enabled": False,
            "input_size_bytes": input_size_bytes,
            "estimated_required_bytes": None,
            "reservation_supported": False,
            "issues": [{
                "code": "CAPACITY_PREFLIGHT_DISABLED",
                "message": "Storage capacity preflight is disabled; enable STORAGE_CAPACITY_PREFLIGHT_ENABLED for laboratory deployments.",
            }],
            "roots": [],
        }
    if input_size_bytes <= 0:
        return {
            "status": "BLOCKED",
            "enabled": True,
            "input_size_bytes": input_size_bytes,
            "estimated_required_bytes": None,
            "reservation_supported": False,
            "issues": [{"code": "INPUT_SIZE_UNKNOWN", "message": "The input artifact size is missing or invalid."}],
            "roots": [],
        }

    headroom = settings.analysis_storage_headroom_bytes
    artifact_required = math.ceil(input_size_bytes * settings.analysis_artifact_output_multiplier) + headroom
    scratch_required = math.ceil(input_size_bytes * settings.analysis_scratch_multiplier) + headroom
    roots = [
        inspect_storage_root("artifact_store", settings.artifact_root),
        inspect_storage_root("worker_scratch", settings.worker_scratch_root),
    ]
    issues: list[dict[str, Any]] = []
    for root in roots:
        if root["error_code"]:
            issues.append({"code": root["error_code"], "message": root["error_message"], "storage": root["label"]})

    device_groups: dict[int, dict[str, Any]] = {}
    for root, required in zip(roots, (artifact_required, scratch_required)):
        device_id = root.get("_device_id")
        if device_id is None:
            continue
        group = device_groups.setdefault(device_id, {
            "available_bytes": root["free_bytes"],
            "required_bytes": 0,
            "labels": [],
        })
        group["required_bytes"] += required
        group["labels"].append(root["label"])

    for group in device_groups.values():
        if group["available_bytes"] is not None and group["available_bytes"] < group["required_bytes"]:
            issues.append({
                "code": "INSUFFICIENT_STORAGE_CAPACITY",
                "message": "Available filesystem capacity is below the configured analysis planning estimate.",
                "storage": ", ".join(group["labels"]),
                "available_bytes": group["available_bytes"],
                "required_bytes": group["required_bytes"],
            })

    public_roots = []
    for root, required in zip(roots, (artifact_required, scratch_required)):
        public_roots.append({
            key: value for key, value in root.items() if not key.startswith("_")
        } | {"estimated_required_bytes": required})

    return {
        "status": "BLOCKED" if issues else "READY",
        "enabled": True,
        "input_size_bytes": input_size_bytes,
        "estimated_required_bytes": artifact_required + scratch_required,
        "artifact_output_multiplier": settings.analysis_artifact_output_multiplier,
        "scratch_multiplier": settings.analysis_scratch_multiplier,
        "headroom_bytes_per_root": headroom,
        "reservation_supported": False,
        "issues": issues,
        "roots": public_roots,
    }
