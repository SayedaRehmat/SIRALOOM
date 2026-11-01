"""Durable idempotency reservations for artifact uploads.

The intent is committed before bytes are written to artifact storage. A retry
with the same tenant, case, key, and request fingerprint can therefore recover
an object left behind by an interrupted API process without creating a second
artifact identity.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactUploadIntent(Base):
    __tablename__ = "artifact_upload_intents"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    case_id: Mapped[UUID] = mapped_column(
        ForeignKey("cases.id"), nullable=False
    )
    idempotency_key_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="RESERVED")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "case_id",
            "idempotency_key_sha256",
            name="uq_artifact_upload_intent_scope_key",
        ),
        CheckConstraint(
            "status IN ('RESERVED', 'COMMITTED', 'RECOVERY_REQUIRED')",
            name="ck_artifact_upload_intent_status",
        ),
        Index("ix_artifact_upload_intents_status_created", "status", "created_at"),
    )
