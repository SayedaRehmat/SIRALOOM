from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from time import monotonic

from fastapi import APIRouter, Response
from sqlalchemy import text

from backend.app.config import settings
from backend.app.domain.storage_profiles import (
    StorageProfileError,
    configured_firebase_storage_target_ids,
    configured_local_storage_targets,
    probe_configured_firebase_storage_target,
)
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.db.session import SessionLocal

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)
_CLOUD_PROBE_CACHE: dict[str, tuple[float, str, str | None]] = {}
_CLOUD_PROBE_LOCK = Lock()
_CLOUD_PROBE_SUCCESS_TTL_SECONDS = 30.0
_CLOUD_PROBE_FAILURE_TTL_SECONDS = 5.0


@router.get("/health")
def health():
    """Liveness probe: does not depend on external services."""
    return {"status": "ok", "service": "SIRALOOM Variant API"}


def _check_database() -> tuple[str, str | None]:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent  # noqa: BLE001
        logger.warning("Readiness database check failed (%s)", type(exc).__name__)
        return "error", "DATABASE_UNAVAILABLE"


def _check_redis() -> tuple[str, str | None]:
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent  # noqa: BLE001
        logger.warning("Readiness Redis check failed (%s)", type(exc).__name__)
        return "error", "REDIS_UNAVAILABLE"


def _check_artifact_root(root_path: str | None = None) -> tuple[str, str | None]:
    probe_path: Path | None = None
    try:
        root = Path(root_path or settings.artifact_root).expanduser().resolve()
        if not root.is_dir():
            return "error", "ARTIFACT_STORE_UNAVAILABLE"
        with NamedTemporaryFile(
            mode="wb", prefix=".siraloom-readiness-", dir=root, delete=False
        ) as probe:
            probe_path = Path(probe.name)
            probe.write(b"siraloom-readiness")
            probe.flush()
            os.fsync(probe.fileno())
        probe_path.unlink()
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent  # noqa: BLE001
        logger.warning("Readiness artifact-store check failed (%s)", type(exc).__name__)
        return "error", "ARTIFACT_STORE_UNAVAILABLE"
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Readiness probe cleanup failed")


def _check_cloud_artifact_store(
    cache_key: str, probe: Callable[[], None]
) -> tuple[str, str | None]:
    now = monotonic()
    with _CLOUD_PROBE_LOCK:
        cached = _CLOUD_PROBE_CACHE.get(cache_key)
        if cached is not None and cached[0] > now:
            return cached[1], cached[2]
        try:
            probe()
            result = ("ok", None)
            ttl = _CLOUD_PROBE_SUCCESS_TTL_SECONDS
        except Exception as exc:  # pragma: no cover - provider/runtime dependent
            logger.warning("Readiness cloud artifact-store check failed (%s)", type(exc).__name__)
            result = ("error", "CLOUD_ARTIFACT_STORE_UNAVAILABLE")
            ttl = _CLOUD_PROBE_FAILURE_TTL_SECONDS
        _CLOUD_PROBE_CACHE[cache_key] = (now + ttl, result[0], result[1])
        return result


def _check_legacy_artifact_store() -> tuple[str, str | None]:
    try:
        local_targets = configured_local_storage_targets()
        cloud_target_ids = configured_firebase_storage_target_ids()
    except StorageProfileError as exc:
        logger.warning("Artifact target configuration is invalid (%s)", type(exc).__name__)
        return "error", "ARTIFACT_TARGET_CONFIGURATION_INVALID"
    if local_targets or cloud_target_ids:
        return "not_required", None
    if settings.firebase_storage_enabled and settings.firebase_storage_bucket:
        store = FirebaseArtifactStore(settings.firebase_storage_bucket)
        return _check_cloud_artifact_store("__legacy_firebase__", store.probe)
    return _check_artifact_root()


def _check_organization_artifact_targets() -> tuple[str, str | None]:
    try:
        local_targets = configured_local_storage_targets()
        cloud_target_ids = configured_firebase_storage_target_ids()
    except StorageProfileError as exc:
        logger.warning("Organization artifact target configuration is invalid (%s)", type(exc).__name__)
        return "error", "ARTIFACT_TARGET_CONFIGURATION_INVALID"
    for _target_id, root in local_targets:
        status, _error = _check_artifact_root(root)
        if status != "ok":
            return "error", "ORGANIZATION_ARTIFACT_TARGET_UNAVAILABLE"
    for target_id in cloud_target_ids:
        status, _error = _check_cloud_artifact_store(
            target_id,
            lambda target_id=target_id: probe_configured_firebase_storage_target(target_id),
        )
        if status != "ok":
            return "error", "ORGANIZATION_ARTIFACT_TARGET_UNAVAILABLE"
    return ("ok", None) if local_targets or cloud_target_ids else ("not_required", None)


@router.get("/ready")
def ready(response: Response):
    """Readiness probe for load balancers/orchestrators.

    Liveness and readiness are intentionally separate: a process can be alive while
    its database, queue, or artifact store is unavailable. The endpoint never returns
    credentials or provider secrets.
    """
    checks = {}
    for name, checker in (
        ("database", _check_database),
        ("redis", _check_redis),
        ("artifact_store", _check_legacy_artifact_store),
        ("organization_artifact_targets", _check_organization_artifact_targets),
    ):
        status, error = checker()
        checks[name] = {"status": status, **({"error": error} if error else {})}

    firebase = {
        "required": bool(settings.firebase_auth_required or settings.app_env.lower() == "production"),
        "configured": bool(settings.firebase_project_id),
    }
    if firebase["required"] and not firebase["configured"]:
        checks["firebase"] = {"status": "error", "configured": False, "required": True, "error": "Firebase project is not configured"}
    else:
        checks["firebase"] = {"status": "ok" if firebase["configured"] else "not_required", "configured": firebase["configured"], "required": firebase["required"]}

    overall = "ok" if all(c["status"] in {"ok", "not_required"} for c in checks.values()) else "not_ready"
    if overall != "ok":
        response.status_code = 503
    return {
        "status": overall,
        "service": "SIRALOOM Variant API",
        "environment": settings.app_env,
        "checks": checks,
    }
