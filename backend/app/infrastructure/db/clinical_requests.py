"""Append-only clinical request, referral verification and authority records."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import now


class ClinicalRequest(Base):
    __tablename__ = "clinical_requests"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    case_id: Mapped[UUID] = mapped_column(ForeignKey("cases.id"), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    request_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="DRAFT")
    current_revision_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now, nullable=False)
    __table_args__ = (
        UniqueConstraint("case_id", "request_identifier", name="uq_clinical_request_case_identifier"),
        CheckConstraint("status IN ('DRAFT','SUBMITTED','UNDER_REVIEW','NEEDS_INFORMATION','ACCEPTED','REJECTED','CLOSED','REASSESSMENT_REQUIRED')", name="ck_clinical_request_status"),
        Index("ix_clinical_requests_org_case", "organization_id", "case_id"),
    )


class ClinicalRequestRevision(Base):
    __tablename__ = "clinical_request_revisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_requests.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        UniqueConstraint("request_id", "version", name="uq_clinical_request_revision_version"),
        UniqueConstraint("request_id", "fingerprint", name="uq_clinical_request_revision_fingerprint"),
        CheckConstraint("version > 0", name="ck_clinical_request_revision_positive"),
    )


class ReferrerVerification(Base):
    __tablename__ = "referrer_verifications"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_requests.id"), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_request_revisions.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_note: Mapped[str] = mapped_column(Text, nullable=False)
    verified_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (CheckConstraint("status IN ('VERIFIED','UNABLE_TO_VERIFY')", name="ck_referrer_verification_status"),)


class AccessionProcedure(Base):
    __tablename__ = "accession_procedures"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id", name="fk_accession_procedures_organization_id_organizations"), nullable=False)
    procedure_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    procedure_version: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", name="fk_accession_procedures_approved_by_users"), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", name="fk_accession_procedures_created_by_users"), nullable=True)
    procedure_evidence_reference: Mapped[str] = mapped_column(Text, nullable=False)
    approval_evidence_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    allows_unverified_referrer_exception: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        UniqueConstraint("organization_id", "procedure_identifier", "procedure_version", name="uq_accession_procedure_version"),
        CheckConstraint("status IN ('PENDING_APPROVAL','APPROVED','WITHDRAWN')", name="ck_accession_procedure_status"),
        CheckConstraint("(status != 'APPROVED') OR (approved_by IS NOT NULL)", name="ck_accession_procedure_approved_by"),
    )


class AccessionDecision(Base):
    __tablename__ = "accession_decisions"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_requests.id"), nullable=False)
    revision_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_request_revisions.id"), nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    verification_id: Mapped[UUID | None] = mapped_column(ForeignKey("referrer_verifications.id"))
    exception_procedure_id: Mapped[UUID | None] = mapped_column(ForeignKey("accession_procedures.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        CheckConstraint("decision IN ('ACCEPT','REJECT','NEEDS_INFORMATION')", name="ck_accession_decision"),
        CheckConstraint("(decision != 'ACCEPT') OR (verification_id IS NOT NULL OR exception_procedure_id IS NOT NULL)", name="ck_accession_acceptance_basis"),
    )


class OrganizationCapabilityAssignment(Base):
    __tablename__ = "organization_capability_assignments"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    capability: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    grant_reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    revocation_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    __table_args__ = (
        CheckConstraint("capability IN ('REFERRER_VERIFY','ACCESSION_DECIDE','CLINICAL_ATTEST','CAPABILITY_ADMIN','HISTORY_RECONCILE')", name="ck_org_capability"),
        Index("ix_org_capability_active", "organization_id", "user_id", "capability", "revoked_at"),
    )


class ClinicalAttestation(Base):
    __tablename__ = "clinical_attestations"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    request_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_requests.id"), nullable=False)
    request_revision_id: Mapped[UUID] = mapped_column(ForeignKey("clinical_request_revisions.id"), nullable=False)
    clinical_intake_revision_id: Mapped[UUID | None] = mapped_column(ForeignKey("clinical_intake_revisions.id"))
    attestation_type: Mapped[str] = mapped_column(Text, nullable=False)
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
