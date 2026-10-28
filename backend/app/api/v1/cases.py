from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    REVIEW_ROLES,
    case_access_predicate,
    require_case_permission,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.case_change import create_case_change_candidates
from backend.app.domain.case_workspace import CaseUpdate, SpecimenCreate
from backend.app.domain.enums import CaseStatus
from backend.app.domain.schemas import CaseCreate
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Assay, Case, CaseAccessGrant, Specimen
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_payload(db: Session, case: Case) -> dict:
    specimens = db.scalars(select(Specimen).where(Specimen.case_id == case.id).order_by(Specimen.created_at)).all()
    analyses = db.scalars(select(Analysis).where(Analysis.case_id == case.id).order_by(Analysis.created_at.desc())).all()
    assays = db.scalars(
        select(Assay)
        .where(
            Assay.organization_id == case.organization_id,
            Assay.status == "ACTIVE",
        )
        .order_by(Assay.name, Assay.version)
    ).all()
    return {
        "case_id": str(case.id), "case_identifier": case.case_identifier, "organization_id": str(case.organization_id),
        "status": case.status, "language": case.language, "clinical_context": case.clinical_context or {},
        "created_by": str(case.created_by), "created_at": case.created_at.isoformat(), "updated_at": case.updated_at.isoformat(),
        "assays": [{
            "assay_id": str(assay.id), "name": assay.name,
            "version": assay.version, "assay_type": assay.assay_type,
            "has_qc_rules": bool((assay.configuration or {}).get("rules")),
        } for assay in assays],
        "specimens": [{
            "specimen_id": str(s.id), "specimen_identifier": s.specimen_identifier, "specimen_type": s.specimen_type,
            "collection_datetime": s.collection_datetime.isoformat() if s.collection_datetime else None,
            "received_datetime": s.received_datetime.isoformat() if s.received_datetime else None, "metadata": s.metadata_json or {},
        } for s in specimens],
        "analyses": [{
            "analysis_id": str(a.id), "status": a.status, "analysis_type": a.analysis_type,
            "workflow_id": a.workflow_id, "workflow_version": a.workflow_version, "reference_build": a.reference_build,
            "created_at": a.created_at.isoformat(),
        } for a in analyses],
    }


@router.post("", status_code=201)
def create(payload: CaseCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    require_role(principal, CASE_WRITE_ROLES)
    existing = db.scalar(select(Case).where(
        Case.organization_id == principal.organization_id, Case.case_identifier == payload.case_identifier,
    ))
    if existing:
        require_case_permission(existing, principal, db, "read")
        return {"case_id": str(existing.id), "case_identifier": existing.case_identifier, "status": existing.status, "created": False}
    case = Case(
        id=uuid4(), organization_id=principal.organization_id, case_identifier=payload.case_identifier,
        status=CaseStatus.DRAFT, language=payload.language, clinical_context=payload.clinical_context,
        created_by=principal.user_id,
    )
    db.add(case)
    try:
        # The organization/case_identifier unique constraint is the final arbiter
        # under concurrent submissions. Reconcile the losing request to the
        # winning row instead of surfacing a spurious HTTP 500.
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(Case).where(
            Case.organization_id == principal.organization_id,
            Case.case_identifier == payload.case_identifier,
        ))
        if existing is not None:
            require_case_permission(existing, principal, db, "read")
            return {
                "case_id": str(existing.id),
                "case_identifier": existing.case_identifier,
                "status": existing.status,
                "created": False,
            }
        raise
    db.add(CaseAccessGrant(
        id=uuid4(), case_id=case.id, user_id=principal.user_id,
        can_read=True, can_write=True,
        can_review=principal.role in REVIEW_ROLES,
        granted_by=principal.user_id,
    ))
    AuditService(db).record(
        event_type="CASE_CREATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="CASE", subject_id=str(case.id), operation="CREATE", after_state={"case_identifier": case.case_identifier},
    )
    db.commit()
    created = True
    return {"case_id": str(case.id), "case_identifier": case.case_identifier, "status": case.status, "created": created}


@router.get("")
def list_cases(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rows = db.scalars(select(Case).where(case_access_predicate(principal)).order_by(Case.updated_at.desc())).all()
    return [_case_payload(db, case) for case in rows]


@router.get("/{case_id}")
def get_case(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "read")
    return _case_payload(db, case)


@router.patch("/{case_id}")
def update_case(case_id: UUID, payload: CaseUpdate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    # Case metadata and its audit/reanalysis candidates form one serialized
    # clinical-history mutation. Lock the row before reading the prior state.
    case = db.get(Case, case_id, with_for_update=True)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    before = {"language": case.language, "clinical_context": case.clinical_context or {}}
    before_updated_at = case.updated_at.isoformat() if case.updated_at else None
    clinical_context_changed = payload.clinical_context is not None and payload.clinical_context != (case.clinical_context or {})
    if payload.language is not None:
        case.language = payload.language
    if payload.clinical_context is not None:
        case.clinical_context = payload.clinical_context
    AuditService(db).record(
        event_type="CASE_UPDATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="CASE", subject_id=str(case.id), operation="UPDATE", before_state=before,
        after_state={"language": case.language, "clinical_context": case.clinical_context or {}}, reason="Case metadata updated",
    )
    if clinical_context_changed:
        create_case_change_candidates(
            db,
            case=case,
            trigger_type="CLINICAL_CONTEXT_UPDATE",
            reason=f"Clinical context for case {case.case_identifier} changed; completed analyses may require reanalysis.",
            metadata={"before": before["clinical_context"], "after": case.clinical_context or {}, "previous_updated_at": before_updated_at},
        )
    db.commit()
    return _case_payload(db, case)


@router.post("/{case_id}/specimens", status_code=201)
def create_specimen(case_id: UUID, payload: SpecimenCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    # Sign-out snapshots the selected specimen while holding this case row.
    # Use the same lock so specimen registration cannot race report creation.
    case = db.get(Case, case_id, with_for_update=True)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    db.refresh(case, with_for_update=True)
    require_case_permission(case, principal, db, "write")
    require_role(principal, CASE_WRITE_ROLES)
    specimen_metadata = dict(payload.metadata or {})
    configured_sample = specimen_metadata.get("vcf_sample_name")
    if configured_sample is not None:
        if not isinstance(configured_sample, str) or not configured_sample.strip():
            raise HTTPException(
                status_code=422,
                detail="metadata.vcf_sample_name must be a non-empty string",
            )
        specimen_metadata["vcf_sample_name"] = configured_sample.strip()
    if payload.vcf_sample_name is not None:
        declared_sample = payload.vcf_sample_name.strip()
        if not declared_sample:
            raise HTTPException(status_code=422, detail="vcf_sample_name cannot be blank")
        existing_sample = specimen_metadata.get("vcf_sample_name")
        if existing_sample is not None and existing_sample != declared_sample:
            raise HTTPException(status_code=422, detail="vcf_sample_name conflicts with specimen metadata")
        specimen_metadata["vcf_sample_name"] = declared_sample
    specimen = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier=payload.specimen_identifier, specimen_type=payload.specimen_type,
        collection_datetime=payload.collection_datetime, received_datetime=payload.received_datetime, metadata_json=specimen_metadata,
    )
    db.add(specimen)
    AuditService(db).record(
        event_type="SPECIMEN_REGISTERED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="SPECIMEN", subject_id=str(specimen.id), operation="CREATE",
        after_state={"specimen_identifier": specimen.specimen_identifier, "specimen_type": specimen.specimen_type, "vcf_sample_name": specimen_metadata.get("vcf_sample_name")},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(Specimen).where(
            Specimen.case_id == case.id,
            Specimen.specimen_identifier == payload.specimen_identifier,
        ))
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail="A specimen with this identifier already exists in the case",
            ) from exc
        raise
    return {"specimen_id": str(specimen.id), "case_id": str(case.id), "specimen_identifier": specimen.specimen_identifier, "specimen_type": specimen.specimen_type, "vcf_sample_name": specimen_metadata.get("vcf_sample_name")}
