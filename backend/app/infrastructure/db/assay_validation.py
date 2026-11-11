"""Immutable assay validation submissions and append-only decisions."""
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import now


class AssayValidationSubmission(Base):
    """A frozen, evidence-backed validation/verification package for one assay version."""

    __tablename__ = "assay_validation_submissions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    assay_id: Mapped[UUID] = mapped_column(ForeignKey("assays.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    protocol_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_version: Mapped[str] = mapped_column(Text, nullable=False)
    intended_use: Mapped[str] = mapped_column(Text, nullable=False)
    specimen_types: Mapped[list] = mapped_column(JSON, nullable=False)
    variant_classes: Mapped[list] = mapped_column(JSON, nullable=False)
    reference_builds: Mapped[list] = mapped_column(JSON, nullable=False)
    workflow_id: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_version: Mapped[str] = mapped_column(Text, nullable=False)
    pipeline_components: Mapped[list] = mapped_column(JSON, nullable=False)
    performance_specifications: Mapped[list] = mapped_column(JSON, nullable=False)
    study_design_summary: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_manifest: Mapped[list] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    supersedes_id: Mapped[UUID | None] = mapped_column(ForeignKey("assay_validation_submissions.id"))
    submitted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    __table_args__ = (
        UniqueConstraint("assay_id", "revision", name="uq_assay_validation_submission_revision"),
        CheckConstraint("revision > 0", name="ck_assay_validation_revision_positive"),
        CheckConstraint("validation_type IN ('VALIDATION','VERIFICATION')", name="ck_assay_validation_type"),
        CheckConstraint("sample_count > 0", name="ck_assay_validation_sample_count_positive"),
        Index("ix_assay_validation_org_assay", "organization_id", "assay_id", "revision"),
    )


class AssayValidationDecision(Base):
    """Append-only approval, rejection, suspension, withdrawal or supersession decision."""

    __tablename__ = "assay_validation_decisions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    submission_id: Mapped[UUID] = mapped_column(
        ForeignKey("assay_validation_submissions.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "decision IN ('APPROVE','REJECT','SUSPEND','WITHDRAW','SUPERSEDE')",
            name="ck_assay_validation_decision",
        ),
        CheckConstraint(
            "(decision != 'APPROVE') OR "
            "(evidence_reference IS NOT NULL AND effective_at IS NOT NULL "
            "AND expires_at IS NOT NULL AND expires_at > effective_at)",
            name="ck_assay_validation_approval_evidence_and_dates",
        ),
        Index("ix_assay_validation_decision_latest", "submission_id", "created_at", "id"),
    )
