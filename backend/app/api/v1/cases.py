from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.session import get_db
from backend.app.auth.principal import Principal, get_current_principal, require_case_tenant
from backend.app.domain.enums import CaseStatus
from backend.app.domain.schemas import CaseCreate
from backend.app.domain.case_workspace import CaseUpdate, SpecimenCreate
from backend.app.infrastructure.db.models import Case, Specimen, Analysis
from backend.app.infrastructure.audit.service import AuditService

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_payload(db: Session, case: Case) -> dict:
    specimens = db.scalars(select(Specimen).where(Specimen.case_id == case.id).order_by(Specimen.created_at)).all()
    analyses = db.scalars(select(Analysis).where(Analysis.case_id == case.id).order_by(Analysis.created_at.desc())).all()
    return {
        "case_id": str(case.id), "case_identifier": case.case_identifier, "organization_id": str(case.organization_id),
        "status": case.status, "language": case.language, "clinical_context": case.clinical_context or {},
        "created_by": str(case.created_by), "created_at": case.created_at.isoformat(), "updated_at": case.updated_at.isoformat(),
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
    existing = db.scalar(select(Case).where(
        Case.organization_id == principal.organization_id, Case.case_identifier == payload.case_identifier,
    ))
    if existing:
        return {"case_id": str(existing.id), "case_identifier": existing.case_identifier, "status": existing.status, "created": False}
    case = Case(
        id=uuid4(), organization_id=principal.organization_id, case_identifier=payload.case_identifier,
        status=CaseStatus.DRAFT, language=payload.language, clinical_context=payload.clinical_context,
        created_by=principal.user_id,
    )
    db.add(case)
    db.flush()
    AuditService(db).record(
        event_type="CASE_CREATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="CASE", subject_id=str(case.id), operation="CREATE", after_state={"case_identifier": case.case_identifier},
    )
    db.commit()
    created = True
    return {"case_id": str(case.id), "case_identifier": case.case_identifier, "status": case.status, "created": created}


@router.get("")
def list_cases(db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    rows = db.scalars(select(Case).where(Case.organization_id == principal.organization_id).order_by(Case.updated_at.desc())).all()
    return [_case_payload(db, case) for case in rows]


@router.get("/{case_id}")
def get_case(case_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    return _case_payload(db, case)


@router.patch("/{case_id}")
def update_case(case_id: UUID, payload: CaseUpdate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    before = {"language": case.language, "clinical_context": case.clinical_context or {}}
    if payload.language is not None:
        case.language = payload.language
    if payload.clinical_context is not None:
        case.clinical_context = payload.clinical_context
    AuditService(db).record(
        event_type="CASE_UPDATED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="CASE", subject_id=str(case.id), operation="UPDATE", before_state=before,
        after_state={"language": case.language, "clinical_context": case.clinical_context or {}}, reason="Case metadata updated",
    )
    db.commit()
    return _case_payload(db, case)


@router.post("/{case_id}/specimens", status_code=201)
def create_specimen(case_id: UUID, payload: SpecimenCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_tenant(case, principal)
    specimen = Specimen(
        id=uuid4(), case_id=case.id, specimen_identifier=payload.specimen_identifier, specimen_type=payload.specimen_type,
        collection_datetime=payload.collection_datetime, received_datetime=payload.received_datetime, metadata_json=payload.metadata,
    )
    db.add(specimen)
    AuditService(db).record(
        event_type="SPECIMEN_REGISTERED", case_id=case.id, analysis_id=None, actor_type="HUMAN", actor_id=str(principal.user_id),
        subject_type="SPECIMEN", subject_id=str(specimen.id), operation="CREATE",
        after_state={"specimen_identifier": specimen.specimen_identifier, "specimen_type": specimen.specimen_type},
    )
    db.commit()
    return {"specimen_id": str(specimen.id), "case_id": str(case.id), "specimen_identifier": specimen.specimen_identifier, "specimen_type": specimen.specimen_type}
