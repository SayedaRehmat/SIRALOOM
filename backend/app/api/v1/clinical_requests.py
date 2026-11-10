"""Versioned clinical requests, referrer verification and separate authorities."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import require_case_permission
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Case, OrganizationMembership
from backend.app.infrastructure.db.clinical_requests import (
    AccessionDecision, AccessionProcedure, ClinicalAttestation, ClinicalRequest,
    ClinicalRequestRevision, OrganizationCapabilityAssignment, ReferrerVerification,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["clinical-requests"])
CAPABILITIES = {"REFERRER_VERIFY", "ACCESSION_DECIDE", "CLINICAL_ATTEST", "CAPABILITY_ADMIN", "HISTORY_RECONCILE"}


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_identifier: str = Field(min_length=1, max_length=200)
    requested_examination: str = Field(min_length=1, max_length=500)
    referral_indication: str = Field(min_length=1, max_length=2000)
    clinical_question: str = Field(min_length=1, max_length=5000)
    referrer_name: str = Field(min_length=1, max_length=300)
    referrer_role: str | None = Field(default=None, max_length=200)
    referrer_organization: str | None = Field(default=None, max_length=300)
    referrer_identifier: str | None = Field(default=None, max_length=300)
    referrer_contact: str | None = Field(default=None, max_length=500)
    referral_channel: str = Field(min_length=1, max_length=100)
    source_evidence_reference: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def clean(self):
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, str):
                setattr(self, name, value.strip())
        return self


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_examination: str = Field(min_length=1, max_length=500)
    referral_indication: str = Field(min_length=1, max_length=2000)
    clinical_question: str = Field(min_length=1, max_length=5000)
    referrer_name: str = Field(min_length=1, max_length=300)
    referrer_role: str | None = Field(default=None, max_length=200)
    referrer_organization: str | None = Field(default=None, max_length=300)
    referrer_identifier: str | None = Field(default=None, max_length=300)
    referrer_contact: str | None = Field(default=None, max_length=500)
    referral_channel: str = Field(min_length=1, max_length=100)
    source_evidence_reference: str | None = Field(default=None, max_length=1000)


class VerificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["VERIFIED", "UNABLE_TO_VERIFY"]
    method: str = Field(min_length=3, max_length=200)
    evidence_reference: str = Field(min_length=1, max_length=1000)
    outcome_note: str = Field(min_length=1, max_length=3000)


class DecisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["ACCEPT", "REJECT", "NEEDS_INFORMATION"]
    reason: str = Field(min_length=1, max_length=5000)
    verification_id: UUID | None = None
    exception_procedure_id: UUID | None = None

    @model_validator(mode="after")
    def validate_acceptance_basis(self):
        if self.verification_id and self.exception_procedure_id:
            raise ValueError("Choose either referrer verification or an approved-procedure exception, not both")
        return self


class CapabilityGrantInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    capability: Literal["REFERRER_VERIFY", "ACCESSION_DECIDE", "CLINICAL_ATTEST", "CAPABILITY_ADMIN", "HISTORY_RECONCILE"]
    reason: str = Field(min_length=1, max_length=2000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self):
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Capability expiry must include a timezone")
        return self


class CapabilityRevokeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class ProcedureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    procedure_identifier: str = Field(min_length=1, max_length=200)
    procedure_version: str = Field(min_length=1, max_length=100)
    effective_at: datetime
    expires_at: datetime | None = None
    approval_evidence_reference: str = Field(min_length=1, max_length=1000)
    allows_unverified_referrer_exception: bool = False

    @model_validator(mode="after")
    def validate_effective_window(self):
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("Procedure effective_at must include a timezone")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None or self.expires_at.utcoffset() is None:
                raise ValueError("Procedure expires_at must include a timezone")
            if self.expires_at <= self.effective_at:
                raise ValueError("Procedure expires_at must be later than effective_at")
        return self


class ProcedureApprovalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_evidence_reference: str = Field(min_length=1, max_length=1000)


class ProcedureWithdrawalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=2000)


class AttestationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_revision_id: UUID
    clinical_intake_revision_id: UUID | None = None
    attestation_type: str = Field(min_length=1, max_length=100)
    conclusion: str = Field(min_length=1, max_length=1000)
    rationale: str = Field(min_length=1, max_length=5000)


def _membership(db: Session, organization_id: UUID, user_id: UUID):
    row = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == user_id,
        OrganizationMembership.status == "ACTIVE",
    ))
    if row is None:
        raise HTTPException(403, "Active organization membership required")
    return row


def _require_capability(db: Session, organization_id: UUID, user_id: UUID, capability: str):
    _membership(db, organization_id, user_id)
    now = datetime.now(UTC)
    grant = db.scalar(select(OrganizationCapabilityAssignment).where(
        OrganizationCapabilityAssignment.organization_id == organization_id,
        OrganizationCapabilityAssignment.user_id == user_id,
        OrganizationCapabilityAssignment.capability == capability,
        OrganizationCapabilityAssignment.revoked_at.is_(None),
        (OrganizationCapabilityAssignment.expires_at.is_(None) | (OrganizationCapabilityAssignment.expires_at > now)),
    ).order_by(OrganizationCapabilityAssignment.created_at.desc()).limit(1))
    if grant is None:
        raise HTTPException(403, f"Missing organization capability: {capability}")
    return grant


def _request_or_404(db: Session, request_id: UUID, principal: Principal, permission: str = "read"):
    row = db.get(ClinicalRequest, request_id)
    if row is None or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Clinical request not found")
    case = db.get(Case, row.case_id)
    if case is None:
        raise HTTPException(404, "Clinical request not found")
    require_case_permission(case, principal, db, permission)
    return row, case


def _revision_payload(row):
    return {"revision_id": str(row.id), "version": row.version, "fingerprint": row.fingerprint, "payload": row.payload, "created_by": str(row.created_by), "created_at": row.created_at.isoformat()}


def _assert_accession_decision_state(request: ClinicalRequest) -> None:
    """Only a currently submitted revision may receive an accession decision.

    A request returned for more information or marked for reassessment must be
    revised and resubmitted before another decision can be recorded.
    """
    if request.status not in {"SUBMITTED", "UNDER_REVIEW"} or not request.current_revision_id:
        raise HTTPException(409, "Request must have a current submitted revision before an accession decision")


@router.post("/cases/{case_id}/clinical-requests", status_code=201)
def create_clinical_request(case_id: UUID, body: RequestCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "write")
    request = ClinicalRequest(id=uuid4(), case_id=case.id, organization_id=case.organization_id, request_identifier=body.request_identifier, status="DRAFT", created_by=principal.user_id)
    db.add(request)
    try:
        db.flush()
        payload = body.model_dump(mode="json")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        revision = ClinicalRequestRevision(id=uuid4(), request_id=request.id, version=1, schema_version=1, fingerprint=fingerprint, payload=payload, created_by=principal.user_id)
        db.add(revision)
        db.flush()
        request.current_revision_id = revision.id
        AuditService(db).record(event_type="CLINICAL_REQUEST_CREATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="CLINICAL_REQUEST", subject_id=str(request.id), operation="CREATE", after_state={"request_identifier": request.request_identifier, "revision_id": str(revision.id)})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Request identifier already exists for this case") from exc
    return {"request_id": str(request.id), "status": request.status, "revision": _revision_payload(revision)}


@router.get("/cases/{case_id}/clinical-requests")
def list_clinical_requests(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    require_case_permission(case, principal, db, "read")
    rows = db.scalars(select(ClinicalRequest).where(ClinicalRequest.case_id == case.id).order_by(ClinicalRequest.created_at)).all()
    return [{"request_id": str(r.id), "request_identifier": r.request_identifier, "status": r.status, "current_revision_id": str(r.current_revision_id) if r.current_revision_id else None} for r in rows]


@router.get("/clinical-requests/{request_id}")
def get_clinical_request(request_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, _ = _request_or_404(db, request_id, principal)
    revisions = db.scalars(select(ClinicalRequestRevision).where(ClinicalRequestRevision.request_id == request.id).order_by(ClinicalRequestRevision.version)).all()
    decisions = db.scalars(select(AccessionDecision).where(AccessionDecision.request_id == request.id).order_by(AccessionDecision.created_at)).all()
    verifications = db.scalars(select(ReferrerVerification).where(ReferrerVerification.request_id == request.id).order_by(ReferrerVerification.verified_at)).all()
    return {"request_id": str(request.id), "request_identifier": request.request_identifier, "status": request.status, "revisions": [_revision_payload(x) for x in revisions], "decisions": [{"decision_id": str(x.id), "revision_id": str(x.revision_id), "decision": x.decision, "reason": x.reason, "actor_id": str(x.actor_id), "verification_id": str(x.verification_id) if x.verification_id else None, "exception_procedure_id": str(x.exception_procedure_id) if x.exception_procedure_id else None, "created_at": x.created_at.isoformat()} for x in decisions], "verifications": [{"verification_id": str(x.id), "revision_id": str(x.revision_id), "status": x.status, "method": x.method, "evidence_reference": x.evidence_reference, "verified_by": str(x.verified_by), "verified_at": x.verified_at.isoformat()} for x in verifications]}


@router.post("/clinical-requests/{request_id}/revisions", status_code=201)
def create_request_revision(request_id: UUID, body: RevisionInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, case = _request_or_404(db, request_id, principal, "write")
    request = db.scalar(select(ClinicalRequest).where(ClinicalRequest.id == request.id).with_for_update())
    if request.status in {"REJECTED", "CLOSED"}:
        raise HTTPException(409, "Closed or rejected requests cannot be revised")
    payload = body.model_dump(mode="json")
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = db.scalar(select(ClinicalRequestRevision).where(ClinicalRequestRevision.request_id == request.id, ClinicalRequestRevision.fingerprint == fingerprint))
    if existing:
        return _revision_payload(existing)
    version = (db.scalar(select(func.max(ClinicalRequestRevision.version)).where(ClinicalRequestRevision.request_id == request.id)) or 0) + 1
    revision = ClinicalRequestRevision(id=uuid4(), request_id=request.id, version=version, schema_version=1, fingerprint=fingerprint, payload=payload, created_by=principal.user_id)
    db.add(revision)
    request.current_revision_id = revision.id
    if request.status == "ACCEPTED":
        request.status = "REASSESSMENT_REQUIRED"
    else:
        request.status = "DRAFT"
    AuditService(db).record(event_type="CLINICAL_REQUEST_REVISION_CREATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="CLINICAL_REQUEST_REVISION", subject_id=str(revision.id), operation="CREATE", after_state={"request_id": str(request.id), "version": version, "fingerprint": fingerprint})
    db.commit()
    return _revision_payload(revision)


@router.post("/clinical-requests/{request_id}/submit")
def submit_request(request_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, case = _request_or_404(db, request_id, principal, "write")
    if request.status not in {"DRAFT", "NEEDS_INFORMATION", "REASSESSMENT_REQUIRED"} or not request.current_revision_id:
        raise HTTPException(409, "Request cannot be submitted from its current state")
    request.status = "SUBMITTED"
    AuditService(db).record(event_type="CLINICAL_REQUEST_SUBMITTED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="CLINICAL_REQUEST", subject_id=str(request.id), operation="SUBMIT", after_state={"revision_id": str(request.current_revision_id)})
    db.commit()
    return {"request_id": str(request.id), "status": request.status}


@router.post("/clinical-requests/{request_id}/verify-referrer", status_code=201)
def verify_referrer(request_id: UUID, body: VerificationInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, case = _request_or_404(db, request_id, principal, "read")
    _require_capability(db, request.organization_id, principal.user_id, "REFERRER_VERIFY")
    if request.status not in {"SUBMITTED", "UNDER_REVIEW"} or not request.current_revision_id:
        raise HTTPException(409, "Referrer verification requires a submitted request revision")
    row = ReferrerVerification(id=uuid4(), request_id=request.id, revision_id=request.current_revision_id, status=body.status, method=body.method.strip(), evidence_reference=body.evidence_reference.strip(), outcome_note=body.outcome_note.strip(), verified_by=principal.user_id)
    db.add(row)
    AuditService(db).record(event_type="REFERRER_IDENTITY_VERIFIED" if body.status == "VERIFIED" else "REFERRER_IDENTITY_UNVERIFIED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="REFERRER_VERIFICATION", subject_id=str(row.id), operation="CREATE", after_state={"request_id": str(request.id), "revision_id": str(request.current_revision_id), "status": body.status, "method": body.method, "evidence_reference": body.evidence_reference})
    db.commit()
    return {"verification_id": str(row.id), "status": row.status, "revision_id": str(row.revision_id)}


@router.post("/clinical-requests/{request_id}/decisions", status_code=201)
def decide_accession(request_id: UUID, body: DecisionInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, case = _request_or_404(db, request_id, principal, "read")
    _require_capability(db, request.organization_id, principal.user_id, "ACCESSION_DECIDE")
    request = db.scalar(select(ClinicalRequest).where(ClinicalRequest.id == request.id).with_for_update())
    _assert_accession_decision_state(request)
    verification_id = None
    exception_id = None
    if body.decision == "ACCEPT":
        if body.verification_id:
            verification = db.get(ReferrerVerification, body.verification_id)
            if verification is None or verification.request_id != request.id or verification.revision_id != request.current_revision_id or verification.status != "VERIFIED":
                raise HTTPException(422, "Verified referrer evidence must apply to the current request revision")
            latest_verification = db.scalar(select(ReferrerVerification).where(
                ReferrerVerification.request_id == request.id,
                ReferrerVerification.revision_id == request.current_revision_id,
            ).order_by(ReferrerVerification.verified_at.desc()).limit(1))
            if latest_verification is None or latest_verification.id != verification.id:
                raise HTTPException(422, "Acceptance must reference the latest referrer verification for the current request revision")
            verification_id = verification.id
        elif body.exception_procedure_id:
            procedure = db.get(AccessionProcedure, body.exception_procedure_id)
            now = datetime.now(UTC)
            if procedure is None or procedure.organization_id != request.organization_id or procedure.status != "APPROVED" or not procedure.allows_unverified_referrer_exception or procedure.effective_at > now or (procedure.expires_at and procedure.expires_at <= now):
                raise HTTPException(422, "A current, approved, in-scope exception procedure is required")
            exception_id = procedure.id
        else:
            raise HTTPException(422, "Acceptance requires current referrer verification or an approved-procedure exception")
    decision = AccessionDecision(id=uuid4(), request_id=request.id, revision_id=request.current_revision_id, decision=body.decision, reason=body.reason.strip(), actor_id=principal.user_id, verification_id=verification_id, exception_procedure_id=exception_id)
    db.add(decision)
    request.status = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "NEEDS_INFORMATION": "NEEDS_INFORMATION"}[body.decision]
    AuditService(db).record(event_type=f"ACCESSION_{body.decision}", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="ACCESSION_DECISION", subject_id=str(decision.id), operation=body.decision, after_state={"request_id": str(request.id), "revision_id": str(request.current_revision_id), "verification_id": str(verification_id) if verification_id else None, "exception_procedure_id": str(exception_id) if exception_id else None}, reason=body.reason)
    db.commit()
    return {"decision_id": str(decision.id), "request_id": str(request.id), "status": request.status}


@router.get("/organizations/capabilities")
def list_capabilities(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role != "organization_admin":
        _require_capability(db, principal.organization_id, principal.user_id, "CAPABILITY_ADMIN")
    rows = db.scalars(
        select(OrganizationCapabilityAssignment)
        .where(OrganizationCapabilityAssignment.organization_id == principal.organization_id)
        .order_by(OrganizationCapabilityAssignment.created_at.desc())
    ).all()
    return [
        {
            "assignment_id": str(row.id),
            "user_id": str(row.user_id),
            "capability": row.capability,
            "granted_by": str(row.granted_by),
            "grant_reason": row.grant_reason,
            "expires_at": row.expires_at.isoformat() if row.expires_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
            "revoked_by": str(row.revoked_by) if row.revoked_by else None,
            "revocation_reason": row.revocation_reason,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/organizations/capabilities", status_code=201)
def grant_capability(body: CapabilityGrantInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role != "organization_admin":
        _require_capability(db, principal.organization_id, principal.user_id, "CAPABILITY_ADMIN")
    if body.user_id == principal.user_id:
        raise HTTPException(403, "Users cannot grant capabilities to themselves")
    if body.capability == "CLINICAL_ATTEST":
        raise HTTPException(
            409,
            "Clinical-attestation capability is disabled until a governed professional-qualification verification workflow is available",
        )
    _membership(db, principal.organization_id, body.user_id)
    row = OrganizationCapabilityAssignment(id=uuid4(), organization_id=principal.organization_id, user_id=body.user_id, capability=body.capability, granted_by=principal.user_id, grant_reason=body.reason.strip(), expires_at=body.expires_at)
    db.add(row)
    AuditService(db).record(event_type="ORGANIZATION_CAPABILITY_GRANTED", case_id=None, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="ORGANIZATION_CAPABILITY", subject_id=str(row.id), operation="GRANT", after_state={"user_id": str(body.user_id), "capability": body.capability, "expires_at": body.expires_at.isoformat() if body.expires_at else None}, reason=body.reason)
    db.commit()
    return {"assignment_id": str(row.id), "user_id": str(row.user_id), "capability": row.capability}


@router.post("/organizations/capabilities/{assignment_id}/revoke")
def revoke_capability(assignment_id: UUID, body: CapabilityRevokeInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role != "organization_admin":
        _require_capability(db, principal.organization_id, principal.user_id, "CAPABILITY_ADMIN")
    row = db.get(OrganizationCapabilityAssignment, assignment_id)
    if row is None or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Capability assignment not found")
    if row.user_id == principal.user_id:
        raise HTTPException(403, "Users cannot revoke their own capability")
    if row.revoked_at is not None:
        raise HTTPException(409, "Capability assignment is already revoked")
    row.revoked_at = datetime.now(UTC)
    row.revoked_by = principal.user_id
    row.revocation_reason = body.reason.strip()
    AuditService(db).record(event_type="ORGANIZATION_CAPABILITY_REVOKED", case_id=None, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="ORGANIZATION_CAPABILITY", subject_id=str(row.id), operation="REVOKE", after_state={"user_id": str(row.user_id), "capability": row.capability}, reason=body.reason)
    db.commit()
    return {"assignment_id": str(row.id), "revoked": True}


@router.post("/organizations/accession-procedures", status_code=201)
def create_accession_procedure(body: ProcedureInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role not in {"organization_admin", "lab_director"}:
        raise HTTPException(403, "Only designated organization procedure authorities may register a procedure")
    row = AccessionProcedure(
        id=uuid4(),
        organization_id=principal.organization_id,
        procedure_identifier=body.procedure_identifier.strip(),
        procedure_version=body.procedure_version.strip(),
        status="PENDING_APPROVAL",
        effective_at=body.effective_at,
        expires_at=body.expires_at,
        approved_by=None,
        created_by=principal.user_id,
        approval_evidence_reference=body.approval_evidence_reference.strip(),
        allows_unverified_referrer_exception=body.allows_unverified_referrer_exception,
    )
    db.add(row)
    AuditService(db).record(
        event_type="ACCESSION_PROCEDURE_SUBMITTED_FOR_APPROVAL",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="ACCESSION_PROCEDURE",
        subject_id=str(row.id),
        operation="SUBMIT",
        after_state={"procedure_identifier": row.procedure_identifier, "procedure_version": row.procedure_version, "exception_allowed": row.allows_unverified_referrer_exception},
        reason="Procedure is pending independent approval and cannot authorize an accession exception.",
    )
    db.commit()
    return {"procedure_id": str(row.id), "status": row.status}


@router.post("/organizations/accession-procedures/{procedure_id}/approve")
def approve_accession_procedure(
    procedure_id: UUID,
    body: ProcedureApprovalInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role not in {"organization_admin", "lab_director"}:
        raise HTTPException(403, "Only designated organization procedure authorities may approve a procedure")
    row = db.get(AccessionProcedure, procedure_id)
    if row is None or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Accession procedure not found")
    if row.status != "PENDING_APPROVAL":
        raise HTTPException(409, "Only a pending procedure can be approved")
    if row.created_by == principal.user_id:
        raise HTTPException(403, "The procedure submitter cannot approve their own procedure")
    evidence = body.approval_evidence_reference.strip()
    if not evidence:
        raise HTTPException(422, "Approval evidence reference is required")
    row.status = "APPROVED"
    row.approved_by = principal.user_id
    row.approval_evidence_reference = evidence
    AuditService(db).record(
        event_type="ACCESSION_PROCEDURE_APPROVED",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="ACCESSION_PROCEDURE",
        subject_id=str(row.id),
        operation="APPROVE",
        after_state={"procedure_identifier": row.procedure_identifier, "procedure_version": row.procedure_version, "approval_evidence_reference": evidence},
    )
    db.commit()
    return {"procedure_id": str(row.id), "status": row.status, "approved_by": str(row.approved_by)}


@router.post("/organizations/accession-procedures/{procedure_id}/withdraw")
def withdraw_accession_procedure(
    procedure_id: UUID,
    body: ProcedureWithdrawalInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    _membership(db, principal.organization_id, principal.user_id)
    if principal.role not in {"organization_admin", "lab_director"}:
        raise HTTPException(403, "Only designated organization procedure authorities may withdraw a procedure")
    row = db.get(AccessionProcedure, procedure_id)
    if row is None or row.organization_id != principal.organization_id:
        raise HTTPException(404, "Accession procedure not found")
    if row.status == "WITHDRAWN":
        raise HTTPException(409, "Accession procedure is already withdrawn")
    previous_status = row.status
    row.status = "WITHDRAWN"
    AuditService(db).record(
        event_type="ACCESSION_PROCEDURE_WITHDRAWN",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="ACCESSION_PROCEDURE",
        subject_id=str(row.id),
        operation="WITHDRAW",
        before_state={"status": previous_status},
        after_state={"status": row.status},
        reason=body.reason,
    )
    db.commit()
    return {"procedure_id": str(row.id), "status": row.status}


@router.post("/clinical-requests/{request_id}/attestations", status_code=201)
def create_clinical_attestation(request_id: UUID, body: AttestationInput, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    request, case = _request_or_404(db, request_id, principal, "read")
    _require_capability(db, request.organization_id, principal.user_id, "CLINICAL_ATTEST")
    revision = db.get(ClinicalRequestRevision, body.request_revision_id)
    if revision is None or revision.request_id != request.id:
        raise HTTPException(422, "Attestation must reference a revision belonging to this request")
    if body.clinical_intake_revision_id:
        from backend.app.infrastructure.db.models import ClinicalIntakeRevision
        intake = db.get(ClinicalIntakeRevision, body.clinical_intake_revision_id)
        if intake is None or intake.case_id != case.id:
            raise HTTPException(422, "Clinical intake revision must belong to this case")
    row = ClinicalAttestation(id=uuid4(), request_id=request.id, request_revision_id=revision.id, clinical_intake_revision_id=body.clinical_intake_revision_id, attestation_type=body.attestation_type.strip(), conclusion=body.conclusion.strip(), rationale=body.rationale.strip(), actor_id=principal.user_id)
    db.add(row)
    AuditService(db).record(event_type="CLINICAL_ATTESTATION_RECORDED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="CLINICAL_ATTESTATION", subject_id=str(row.id), operation="ATTEST", after_state={"request_id": str(request.id), "request_revision_id": str(revision.id), "clinical_intake_revision_id": str(body.clinical_intake_revision_id) if body.clinical_intake_revision_id else None, "attestation_type": body.attestation_type, "conclusion": body.conclusion}, reason=body.rationale)
    db.commit()
    return {"attestation_id": str(row.id), "request_id": str(request.id)}
