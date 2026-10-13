from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from backend.app.config import settings
from backend.app.infrastructure.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    """Liveness probe: does not depend on external services."""
    return {"status": "ok", "service": "SIRALOOM Variant API"}


def _check_database() -> tuple[str, str | None]:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent
        # Do not return exception text: DB errors may contain hostnames or credentials.
        return "error", type(exc).__name__


def _check_redis() -> tuple[str, str | None]:
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent
        return "error", type(exc).__name__


def _check_artifact_root() -> tuple[str, str | None]:
    try:
        root = Path(settings.artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        # A unique probe avoids false readiness failures when multiple probes arrive
        # concurrently against the same shared artifact mount.
        with tempfile.NamedTemporaryFile(prefix=".siraloom-readiness-", dir=root) as probe:
            probe.write(b"ok")
            probe.flush()
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent
        # Avoid exposing filesystem paths and OS error details to unauthenticated callers.
        return "error", type(exc).__name__


@router.get("/ready")
def ready(response: Response):
    """Readiness probe for load balancers/orchestrators.

    Returns HTTP 503 whenever a required dependency is unavailable. Liveness remains
    independent so orchestration can distinguish a live process from a ready service.
    Diagnostic details are deliberately limited to exception class names.
    """
    checks = {}
    for name, checker in (
        ("database", _check_database),
        ("redis", _check_redis),
        ("artifact_store", _check_artifact_root),
    ):
        check_status, error = checker()
        checks[name] = {"status": check_status, **({"error": error} if error else {})}

    firebase = {
        "required": bool(settings.firebase_auth_required or settings.app_env.lower() == "production"),
        "configured": bool(settings.firebase_project_id),
    }
    if firebase["required"] and not firebase["configured"]:
        checks["firebase"] = {
            "status": "error",
            "configured": False,
            "required": True,
            "error": "Firebase project is not configured",
        }
    else:
        checks["firebase"] = {
            "status": "ok" if firebase["configured"] else "not_required",
            "configured": firebase["configured"],
            "required": firebase["required"],
        }

    overall = "ok" if all(c["status"] in {"ok", "not_required"} for c in checks.values()) else "not_ready"
    response.status_code = status.HTTP_200_OK if overall == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": overall,
        "service": "SIRALOOM Variant API",
        "environment": settings.app_env,
        "checks": checks,
    }
