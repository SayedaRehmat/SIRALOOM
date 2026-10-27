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


def enforce_laboratory_capacity_policy(
    capacity: dict[str, Any],
    *,
    is_laboratory: bool,
) -> dict[str, Any]:
    """Fail closed for laboratory analyses unless capacity preflight is READY.

    Trial deployments retain the pre-existing capacity policy. This function
    enforces a readiness gate only; it does not reserve disk space.
    """
    if not is_laboratory or capacity.get("status") == "READY":
        return capacity

    issues = list(capacity.get("issues") or [])
    if not any(
        isinstance(issue, dict)
        and issue.get("code") == "LAB_CAPACITY_PREFLIGHT_REQUIRED"
        for issue in issues
    ):
        issues.append({
            "code": "LAB_CAPACITY_PREFLIGHT_REQUIRED",
            "message": (
                "Laboratory analysis requires a successful storage-capacity "
                "preflight. Configure and enable STORAGE_CAPACITY_PREFLIGHT_ENABLED, "
                "then resolve any storage readiness issues before retrying."
            ),
        })
    return {**capacity, "status": "BLOCKED", "issues": issues}




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


def _capacity_roots(
    *, artifact_root: str | None, artifact_backend_type: str
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if artifact_backend_type not in {"LOCAL_FILESYSTEM", "FIREBASE_GCS"}:
        raise ValueError("Unsupported artifact storage backend for capacity inspection")
    remote_storage = None
    roots = []
    if artifact_backend_type == "LOCAL_FILESYSTEM":
        roots.append(
            inspect_storage_root(
                "artifact_store", artifact_root or settings.artifact_root
            )
        )
    else:
        # Object-store quota/free capacity is not exposed as a filesystem
        # measurement. Actual writes remain authoritative; do not substitute
        # the unrelated legacy ARTIFACT_ROOT's free-space figure.
        remote_storage = {
            "backend_type": artifact_backend_type,
            "capacity_status": "PROVIDER_MANAGED_NOT_MEASURABLE",
        }
    roots.extend(
        (
            inspect_storage_root("worker_scratch", settings.worker_scratch_root),
            inspect_storage_root("resource_cache", settings.resource_cache_root),
        )
    )
    return roots, remote_storage


def inspect_deployment_capacity(
    *,
    artifact_root: str | None = None,
    artifact_backend_type: str = "LOCAL_FILESYSTEM",
) -> dict[str, Any]:
    roots, remote_storage = _capacity_roots(
        artifact_root=artifact_root,
        artifact_backend_type=artifact_backend_type,
    )
    public_roots = [{key: value for key, value in root.items() if not key.startswith("_")} for root in roots]
    issues = [
        {"code": root["error_code"], "message": root["error_message"], "storage": root["label"]}
        for root in roots if root["error_code"]
    ]
    result = {
        "status": "BLOCKED" if issues else "READY",
        "capacity_preflight_enabled": settings.storage_capacity_preflight_enabled,
        "max_artifact_upload_bytes": settings.max_artifact_upload_bytes,
        "resource_staging_max_bytes": settings.resource_staging_max_bytes,
        "reservation_supported": False,
        "roots": public_roots,
        "issues": issues,
    }
    if remote_storage is not None:
        result["artifact_storage"] = remote_storage
    return result


def preflight_upload_capacity(
    incoming_size_bytes: int,
    *,
    artifact_root: str | None = None,
    artifact_backend_type: str = "LOCAL_FILESYSTEM",
) -> dict[str, Any]:
    """Estimate extra space needed to stage and persist an incoming upload."""
    if not settings.storage_capacity_preflight_enabled:
        return {
            "status": "NOT_CONFIGURED",
            "enabled": False,
            "input_size_bytes": incoming_size_bytes,
            "estimated_required_bytes": None,
            "reservation_supported": False,
            "issues": [],
            "roots": [],
        }
    if incoming_size_bytes <= 0:
        return {
            "status": "BLOCKED",
            "enabled": True,
            "input_size_bytes": incoming_size_bytes,
            "estimated_required_bytes": None,
            "reservation_supported": False,
            "issues": [{"code": "INPUT_SIZE_UNKNOWN", "message": "The incoming upload size is missing or invalid."}],
            "roots": [],
        }
    headroom = settings.analysis_storage_headroom_bytes
    required = incoming_size_bytes + headroom
    roots, remote_storage = _capacity_roots(
        artifact_root=artifact_root,
        artifact_backend_type=artifact_backend_type,
    )
    roots = [root for root in roots if root["label"] != "resource_cache"]
    issues: list[dict[str, Any]] = [
        {"code": root["error_code"], "message": root["error_message"], "storage": root["label"]}
        for root in roots if root["error_code"]
    ]
    groups: dict[int, dict[str, Any]] = {}
    for root in roots:
        device_id = root.get("_device_id")
        if device_id is None:
            continue
        group = groups.setdefault(device_id, {
            "available_bytes": root["free_bytes"],
            "required_bytes": 0,
            "labels": [],
        })
        group["required_bytes"] += required
        group["labels"].append(root["label"])
    for group in groups.values():
        if group["available_bytes"] is not None and group["available_bytes"] < group["required_bytes"]:
            issues.append({
                "code": "INSUFFICIENT_UPLOAD_CAPACITY",
                "message": "Available capacity is below the estimate for multipart staging and persistent artifact storage.",
                "storage": ", ".join(group["labels"]),
                "available_bytes": group["available_bytes"],
                "required_bytes": group["required_bytes"],
            })
    result = {
        "status": "BLOCKED" if issues else "READY",
        "enabled": True,
        "input_size_bytes": incoming_size_bytes,
        "estimated_required_bytes": required * len(roots),
        "headroom_bytes_per_root": headroom,
        "reservation_supported": False,
        "issues": issues,
        "roots": [
            {key: value for key, value in root.items() if not key.startswith("_")}
            | {"estimated_required_bytes": required}
            for root in roots
        ],
    }
    if remote_storage is not None:
        result["artifact_storage"] = remote_storage
    return result


def preflight_analysis_capacity(
    input_size_bytes: int,
    *,
    artifact_root: str | None = None,
    artifact_backend_type: str = "LOCAL_FILESYSTEM",
) -> dict[str, Any]:
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
    roots, remote_storage = _capacity_roots(
        artifact_root=artifact_root,
        artifact_backend_type=artifact_backend_type,
    )
    roots = [root for root in roots if root["label"] != "resource_cache"]
    issues: list[dict[str, Any]] = []
    for root in roots:
        if root["error_code"]:
            issues.append({"code": root["error_code"], "message": root["error_message"], "storage": root["label"]})

    device_groups: dict[int, dict[str, Any]] = {}
    required_by_label = {
        "artifact_store": artifact_required,
        "worker_scratch": scratch_required,
    }
    for root in roots:
        required = required_by_label[root["label"]]
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
    for root in roots:
        required = required_by_label[root["label"]]
        public_roots.append({
            key: value for key, value in root.items() if not key.startswith("_")
        } | {"estimated_required_bytes": required})

    result = {
        "status": "BLOCKED" if issues else "READY",
        "enabled": True,
        "input_size_bytes": input_size_bytes,
        "estimated_required_bytes": sum(
            required_by_label[root["label"]] for root in roots
        ),
        "artifact_output_multiplier": settings.analysis_artifact_output_multiplier,
        "scratch_multiplier": settings.analysis_scratch_multiplier,
        "headroom_bytes_per_root": headroom,
        "reservation_supported": False,
        "issues": issues,
        "roots": public_roots,
    }
    if remote_storage is not None:
        result["artifact_storage"] = {
            **remote_storage,
            "estimated_artifact_bytes": artifact_required,
        }
    return result
