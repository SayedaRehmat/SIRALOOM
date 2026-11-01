"""Database models for governed sex-chromosome caller ploidy policies."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import now


class CallerPloidyPolicyRevision(Base):
    """Append-only, exact caller-version/assay/build-specific ploidy policy."""
    __tablename__ = "caller_ploidy_policy_revisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    assay_id: Mapped[UUID] = mapped_column(ForeignKey("assays.id"), nullable=False)
    caller_id: Mapped[str] = mapped_column(Text, nullable=False)
    caller_version: Mapped[str] = mapped_column(Text, nullable=False)
    policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    reference_build: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(nullable=False, default=1)
    validation_evidence_reference: Mapped[str | None] = mapped_column(Text)
    region_copy_number_to_gt_ploidy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    qualified_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    revision_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    audit_event_id: Mapped[UUID] = mapped_column(ForeignKey("audit_events.id"), nullable=False, unique=True)
    __table_args__ = (
        UniqueConstraint(
            "assay_id", "caller_id", "caller_version", "policy_version", "reference_build", "status",
            name="uq_caller_ploidy_policy_exact_version_status",
        ),
        UniqueConstraint("assay_id", "revision_fingerprint", name="uq_caller_ploidy_policy_fingerprint"),
        CheckConstraint("schema_version = 1", name="ck_caller_ploidy_policy_schema_version"),
        CheckConstraint(
            "status IN ('DRAFT', 'QUALIFIED', 'RETIRED')",
            name="ck_caller_ploidy_policy_status",
        ),
        CheckConstraint(
            "(status != 'QUALIFIED') OR "
            "(qualified_by IS NOT NULL AND qualified_at IS NOT NULL "
            "AND validation_evidence_reference IS NOT NULL)",
            name="ck_caller_ploidy_policy_qualified_provenance",
        ),
        Index(
            "ix_caller_ploidy_policy_assay_caller_build_status",
            "assay_id", "caller_id", "caller_version", "reference_build", "status",
        ),
    )
