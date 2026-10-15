"""Compensate stored artifact bytes after a failed database transaction."""

import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Artifact
from backend.app.infrastructure.db.session import SessionLocal

logger = logging.getLogger(__name__)


def compensate_uncommitted_artifact(
    db: Session,
    store,
    artifact_id: UUID,
    storage_uri: str,
    *,
    verification_session_factory: Callable | None = None,
) -> None:
    """Delete stored bytes only after a fresh DB read proves no row committed."""
    db.rollback()
    try:
        with (verification_session_factory or SessionLocal)() as verification_db:
            durable = verification_db.get(Artifact, artifact_id)
    except Exception as exc:  # noqa: BLE001 - uncertain commit outcome must preserve the object
        logger.warning("Could not verify failed artifact commit outcome (%s)", type(exc).__name__)
        return

    if durable is not None:
        return
    try:
        store.delete(storage_uri)
    except Exception as exc:  # noqa: BLE001 - cleanup failure must not mask the original error
        logger.warning("Could not remove uncommitted artifact object (%s)", type(exc).__name__)


def commit_with_artifact_compensation(db: Session, store, artifact: Artifact) -> None:
    """Commit DB metadata and compensate external bytes if commit raises."""
    artifact_id = artifact.id
    storage_uri = artifact.storage_uri
    try:
        db.commit()
    except Exception:
        compensate_uncommitted_artifact(db, store, artifact_id, storage_uri)
        raise
