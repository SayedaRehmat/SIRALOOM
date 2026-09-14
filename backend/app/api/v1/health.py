from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
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
        return "error", str(exc)[:300]


def _check_redis() -> tuple[str, str | None]:
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent
        return "error", str(exc)[:300]


def _check_artifact_root() -> tuple[str, str | None]:
    try:
        root = Path(settings.artifact_root)
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".siraloom-readiness-probe"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return "ok", None
    except Exception as exc:  # pragma: no cover - deployment/runtime dependent
        return "error", str(exc)[:300]


@router.get("/ready")
def ready():
    """Readiness probe for load balancers/orchestrators.

    Liveness and readiness are intentionally separate: a process can be alive while
    its database, queue, or artifact store is unavailable. The endpoint never returns
    credentials or provider secrets.
    """
    checks = {}
    for name, checker in (
        ("database", _check_database),
        ("redis", _check_redis),
        ("artifact_store", _check_artifact_root),
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
    return {
        "status": overall,
        "service": "SIRALOOM Variant API",
        "environment": settings.app_env,
        "checks": checks,
    }
