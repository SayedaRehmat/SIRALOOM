from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.session import get_db
from backend.app.infrastructure.db.models import Case, Analysis, WorkflowStep, Variant, Annotation, Assay
from backend.app.application.analysis import create_analysis, enqueue_analysis
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.auth.authorization import CASE_WRITE_ROLES, require_role, get_accessible_analysis
from backend.app.domain.schemas import AnalysisCreate

router = APIRouter(tags=["analyses"])

@router.post("/cases/{case_id}/analyses", status_code=201)
def create(case_id: str, payload: AnalysisCreate, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    cid = UUID(case_id)
    case = db.get(Case, cid)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    from backend.app.auth.principal import require_case_tenant
    require_case_tenant(case, principal); require_role(principal, CASE_WRITE_ROLES)
    if payload.assay_id:
        assay = db.get(Assay, payload.assay_id)
        if not assay or assay.organization_id != principal.organization_id:
            raise HTTPException(status_code=400, detail="Invalid assay_id for this organization")
    try:
        analysis = create_analysis(db, case_id=cid, input_artifact_id=payload.input_artifact_id, assay_id=payload.assay_id, analysis_type=payload.analysis_type, workflow_id=payload.workflow_id, workflow_version=payload.workflow_version, reference_build=payload.reference_build, configuration=payload.configuration, created_by=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"analysis_id": str(analysis.id), "case_id": str(cid), "status": analysis.status, "workflow_id": analysis.workflow_id, "workflow_version": analysis.workflow_version, "reference_build": analysis.reference_build, "assay_id": str(analysis.assay_id) if analysis.assay_id else None, "created_at": analysis.created_at}

@router.post("/analyses/{analysis_id}/start")
def start(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal); require_role(principal, CASE_WRITE_ROLES)
    task_id = enqueue_analysis(db, analysis)
    return {"analysis_id": str(analysis_id), "status": analysis.status, "task_id": task_id}

@router.get("/analyses/{analysis_id}")
def get(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    steps = db.scalars(select(WorkflowStep).where(WorkflowStep.analysis_id == analysis.id).order_by(WorkflowStep.step_order)).all()
    return {
        "analysis_id": str(analysis.id), "case_id": str(analysis.case_id), "status": analysis.status,
        "workflow_id": analysis.workflow_id, "workflow_version": analysis.workflow_version,
        "reference_build": analysis.reference_build,
        "queue_task_id": analysis.queue_task_id,
        "started_at": analysis.started_at, "completed_at": analysis.completed_at,
        "steps": [{"step_id": s.step_id, "status": s.status, "attempt": s.attempt, "last_heartbeat": s.last_heartbeat, "error_code": s.error_code, "error_message": s.error_message, "metadata": s.metadata_json} for s in steps]
    }

@router.get("/analyses/{analysis_id}/variants")
def list_variants(analysis_id: UUID, db: Session = Depends(get_db), principal: Principal = Depends(get_current_principal)):
    get_accessible_analysis(analysis_id, db, principal); aid = analysis_id
    rows = db.scalars(select(Variant).join(Annotation, Annotation.variant_id == Variant.id).where(Annotation.analysis_id == aid).distinct()).all()
    return [{"variant_id": str(v.id), "genome_build": v.genome_build, "chromosome": v.chromosome, "position": v.position, "reference": v.reference, "alternate": v.alternate} for v in rows]
