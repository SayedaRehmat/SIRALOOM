from datetime import UTC, datetime
import hashlib
import json
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import CASE_WRITE_ROLES, READ_ROLES, REVIEW_ROLES, require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.ploidy_schemas import CallerPloidyPolicyCreate
from backend.app.domain.sample_ploidy_policy import PloidyPolicyValidationError, parse_caller_ploidy_policy
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Assay
from backend.app.infrastructure.db.ploidy_models import CallerPloidyPolicyRevision
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/assays", tags=["assay-ploidy-policy"])


def _policy_payload(row: CallerPloidyPolicyRevision) -> dict:
    return {
        "policy_revision_id": str(row.id),
        "assay_id": str(row.assay_id),
        "caller_id": row.caller_id,
        "caller_version": row.caller_version,
        "policy_version": row.policy_version,
        "reference_build": row.reference_build,
        "status": row.status,
        "schema_version": row.schema_version,
        "validation_evidence_reference": row.validation_evidence_reference,
        "region_copy_number_to_gt_ploidy": row.region_copy_number_to_gt_ploidy or {},
        "qualified_by": str(row.qualified_by) if row.qualified_by else None,
        "qualified_at": row.qualified_at.isoformat() if row.qualified_at else None,
        "recorded_by": str(row.recorded_by),
        "recorded_at": row.recorded_at.isoformat() if row.recorded_at else None,
        "audit_event_id": str(row.audit_event_id),
        "revision_fingerprint": row.revision_fingerprint,
    }


@router.post("/{assay_id}/ploidy-policies", status_code=201)
def create_caller_ploidy_policy(
    assay_id: UUID,
    payload: CallerPloidyPolicyCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Append an immutable caller/assay/build policy revision."""
    assay = db.get(Assay, assay_id)
    if assay is None or assay.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Assay not found")
    if assay.status != "ACTIVE":
        raise HTTPException(status_code=409, detail="Caller ploidy policies require an active assay")

    if payload.status in {"QUALIFIED", "RETIRED"}:
        require_role(principal, REVIEW_ROLES)
    else:
        require_role(principal, CASE_WRITE_ROLES)

    qualified_at = datetime.now(UTC) if payload.status == "QUALIFIED" else None
    policy_payload = payload.model_dump(mode="json")
    policy_payload.update({
        "assay_id": str(assay.id),
        "qualified_by": str(principal.user_id) if qualified_at else None,
        "qualified_at": qualified_at.isoformat() if qualified_at else None,
    })
    try:
        policy = parse_caller_ploidy_policy(policy_payload)
    except PloidyPolicyValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    fingerprint_payload = {
        "schema_version": 1,
        "assay_id": str(assay.id),
        "caller_id": policy.caller_id,
        "caller_version": policy.caller_version,
        "policy_version": policy.policy_version,
        "reference_build": policy.reference_build,
        "status": policy.status,
        "validation_evidence_reference": policy.validation_evidence_reference,
        "qualified_by": str(principal.user_id) if qualified_at else None,
        "recorded_by": str(principal.user_id),
        "region_copy_number_to_gt_ploidy": {
            region: {str(copy_number): ploidy for copy_number, ploidy in mapping.items()}
            for region, mapping in policy.region_copy_number_to_gt_ploidy.items()
        },
    }
    canonical = json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    exact_version = db.scalar(select(CallerPloidyPolicyRevision).where(
        CallerPloidyPolicyRevision.assay_id == assay.id,
        CallerPloidyPolicyRevision.caller_id == policy.caller_id,
        CallerPloidyPolicyRevision.caller_version == policy.caller_version,
        CallerPloidyPolicyRevision.policy_version == policy.policy_version,
        CallerPloidyPolicyRevision.reference_build == policy.reference_build,
        CallerPloidyPolicyRevision.status == policy.status,
    ))
    if exact_version is not None:
        if exact_version.revision_fingerprint == fingerprint:
            return _policy_payload(exact_version)
        raise HTTPException(
            status_code=409,
            detail="This caller/assay/policy-version/build/status identity already exists; issue a new policy_version for changed content",
        )

    audit_event_id = AuditService(db).record(
        event_type="CALLER_PLOIDY_POLICY_RECORDED",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CALLER_PLOIDY_POLICY",
        subject_id=f"{assay.id}:{policy.caller_id}:{policy.caller_version}:{policy.policy_version}",
        operation="CREATE_REVISION",
        after_state={
            "assay_id": str(assay.id),
            "caller_id": policy.caller_id,
            "caller_version": policy.caller_version,
            "policy_version": policy.policy_version,
            "reference_build": policy.reference_build,
            "status": policy.status,
            "validation_evidence_reference": policy.validation_evidence_reference,
            "region_copy_number_to_gt_ploidy": fingerprint_payload["region_copy_number_to_gt_ploidy"],
            "qualified_by": str(principal.user_id) if qualified_at else None,
            "qualified_at": qualified_at.isoformat() if qualified_at else None,
            "revision_fingerprint": fingerprint,
        },
        reason="Caller/assay ploidy policy revision recorded",
    )
    row = CallerPloidyPolicyRevision(
        id=uuid4(),
        assay_id=assay.id,
        caller_id=policy.caller_id,
        caller_version=policy.caller_version,
        policy_version=policy.policy_version,
        reference_build=policy.reference_build,
        status=policy.status,
        schema_version=1,
        validation_evidence_reference=policy.validation_evidence_reference,
        region_copy_number_to_gt_ploidy=fingerprint_payload["region_copy_number_to_gt_ploidy"],
        qualified_by=principal.user_id if qualified_at else None,
        qualified_at=qualified_at,
        recorded_by=principal.user_id,
        revision_fingerprint=fingerprint,
        audit_event_id=audit_event_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CallerPloidyPolicyRevision).where(
            CallerPloidyPolicyRevision.assay_id == assay.id,
            CallerPloidyPolicyRevision.caller_id == policy.caller_id,
            CallerPloidyPolicyRevision.caller_version == policy.caller_version,
            CallerPloidyPolicyRevision.policy_version == policy.policy_version,
            CallerPloidyPolicyRevision.reference_build == policy.reference_build,
            CallerPloidyPolicyRevision.status == policy.status,
        ))
        if duplicate is not None and duplicate.revision_fingerprint == fingerprint:
            return _policy_payload(duplicate)
        raise HTTPException(status_code=409, detail="Caller ploidy policy changed concurrently; retry with a new policy version") from exc
    db.refresh(row)
    return _policy_payload(row)


@router.get("/{assay_id}/ploidy-policies")
def list_caller_ploidy_policies(
    assay_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, READ_ROLES)
    assay = db.get(Assay, assay_id)
    if assay is None or assay.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Assay not found")
    rows = db.scalars(
        select(CallerPloidyPolicyRevision)
        .where(CallerPloidyPolicyRevision.assay_id == assay.id)
        .order_by(
            CallerPloidyPolicyRevision.caller_id,
            CallerPloidyPolicyRevision.caller_version,
            CallerPloidyPolicyRevision.policy_version,
            CallerPloidyPolicyRevision.status,
        )
    ).all()
    return [_policy_payload(row) for row in rows]
