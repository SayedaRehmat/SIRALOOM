"""Persistence operations for durable artifact upload idempotency intents."""
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.domain.upload_idempotency import (
    idempotency_key_sha256,
)
from backend.app.infrastructure.db.artifact_upload_intents import ArtifactUploadIntent


class UploadIdempotencyConflict(ValueError):
    """An idempotency key was reused for a different upload request."""


def reserve_upload_intent(
    db: Session,
    *,
    organization_id,
    case_id,
    key_sha256: str,
    request_fingerprint: str,
) -> tuple[ArtifactUploadIntent, bool]:
    """Durably reserve one artifact identity before writing storage bytes.

    Returns (intent, created). Concurrent insertions are reconciled through the
    database uniqueness constraint; the losing request reads the winner's
    committed reservation and validates its request fingerprint.
    """
    statement = select(ArtifactUploadIntent).where(
        ArtifactUploadIntent.organization_id == organization_id,
        ArtifactUploadIntent.case_id == case_id,
        ArtifactUploadIntent.idempotency_key_sha256 == key_sha256,
    )
    existing = db.scalar(statement)
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise UploadIdempotencyConflict(
                "This Idempotency-Key is already bound to a different upload request."
            )
        return existing, False

    intent = ArtifactUploadIntent(
        id=uuid4(),
        organization_id=organization_id,
        case_id=case_id,
        idempotency_key_sha256=key_sha256,
        request_fingerprint=request_fingerprint,
        artifact_id=uuid4(),
        status="RESERVED",
    )
    db.add(intent)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(statement)
        if existing is None:
            raise
        if existing.request_fingerprint != request_fingerprint:
            raise UploadIdempotencyConflict(
                "This Idempotency-Key is already bound to a different upload request."
            )
        return existing, False

    return intent, True
