from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from backend.app.auth.authorization import get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Assay, TechnicalQCObservation, QCAssessment
from backend.app.infrastructure.db.session import get_db
from backend.app.quality import assess_metrics

router = APIRouter(tags=["technical-quality"])

class AssayInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    assay_type: str = Field(min_length=1, max_length=100)
    configuration: dict = Field(default_factory=dict)
    status: str = Field(default="ACTIVE", max_length=50)

class QCObservationInput(BaseModel):
    metric_name: str = Field(min_length=1, max_length=150)
    metric_value: float | None = None
    metric_unit: str | None = Field(default=None, max_length=50)
    source: str = Field(default="LAB_QC", max_length=100)
    source_version: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)

class QCAssessmentInput(BaseModel):
    metrics: dict[str, float | int | None]
    reviewer_note: str | None = Field(default=None, max_length=5000)


def _assay(a):
    return {"id": str(a.id), "name": a.name, "version": a.version, "assay_type": a.assay_type,
            "configuration": a.configuration or {}, "status": a.status}

def _obs(o):
    return {"id": str(o.id), "analysis_id": str(o.analysis_id), "artifact_id": str(o.artifact_id) if o.artifact_id else None,
            "metric_name": o.metric_name, "metric_value": o.metric_value, "metric_unit": o.metric_unit,
            "status": o.status, "source": o.source, "source_version": o.source_version,
            "metadata": o.metadata_json or {}, "created_at": o.created_at.isoformat()}

@router.post("/assays", status_code=201)
def create_assay(body: AssayInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    row = Assay(id=uuid4(), organization_id=principal.organization_id, name=body.name.strip(), version=body.version.strip(),
                assay_type=body.assay_type.strip(), configuration=body.configuration, status=body.status)
    db.add(row)
    AuditService(db).record(event_type="ASSAY_PROFILE_CREATED", case_id=None, analysis_id=None, actor_type="HUMAN",
        actor_id=str(principal.user_id), subject_type="ASSAY", subject_id=str(row.id), operation="CREATE", after_state=_assay(row))
    db.commit(); return _assay(row)

@router.get("/assays")
def list_assays(db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    rows=list(db.scalars(select(Assay).where(Assay.organization_id==principal.organization_id).order_by(Assay.name, Assay.version)))
    return {"assays": [_assay(x) for x in rows]}

@router.post("/analyses/{analysis_id}/quality/observations", status_code=201)
def record_qc_observation(analysis_id: UUID, body: QCObservationInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal)
    row=TechnicalQCObservation(id=uuid4(), analysis_id=analysis.id, metric_name=body.metric_name.strip(), metric_value=body.metric_value,
        metric_unit=body.metric_unit, source=body.source, source_version=body.source_version, metadata_json=body.metadata)
    db.add(row)
    AuditService(db).record(event_type="TECHNICAL_QC_OBSERVATION_RECORDED", case_id=analysis.case_id, analysis_id=analysis.id,
        actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="TECHNICAL_QC", subject_id=str(row.id), operation="CREATE", after_state=_obs(row))
    db.commit(); return _obs(row)

@router.get("/analyses/{analysis_id}/quality")
def get_quality(analysis_id: UUID, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal)
    observations=list(db.scalars(select(TechnicalQCObservation).where(TechnicalQCObservation.analysis_id==analysis.id).order_by(TechnicalQCObservation.created_at)))
    assessments=list(db.scalars(select(QCAssessment).where(QCAssessment.analysis_id==analysis.id).order_by(QCAssessment.created_at.desc())))
    assay=db.get(Assay, analysis.assay_id) if analysis.assay_id else None
    return {"analysis_id": str(analysis.id), "assay": _assay(assay) if assay else None,
            "observations": [_obs(x) for x in observations],
            "assessments": [{"id":str(x.id),"status":x.status,"gate_status":x.gate_status,"profile_name":x.profile_name,
                             "profile_version":x.profile_version,"metrics":x.metrics_json or {},"evaluated_rules":x.evaluated_rules or [],
                             "reviewer_note":x.reviewer_note,"reviewed_by":x.reviewed_by,"reviewed_at":x.reviewed_at.isoformat() if x.reviewed_at else None,
                             "created_at":x.created_at.isoformat()} for x in assessments]}

@router.post("/analyses/{analysis_id}/quality/assess")
def assess_quality(analysis_id: UUID, body: QCAssessmentInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal)
    assay=db.get(Assay, analysis.assay_id) if analysis.assay_id else None
    if assay and assay.organization_id != principal.organization_id:
        raise HTTPException(403,"Assay is not accessible")
    config=assay.configuration if assay else {}
    try:
        result=assess_metrics(body.metrics, config)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    row=QCAssessment(id=uuid4(),analysis_id=analysis.id,assay_id=assay.id if assay else None,status=result["status"],
        profile_name=assay.name if assay else None,profile_version=assay.version if assay else None,metrics_json=body.metrics,
        evaluated_rules=result["metrics"],gate_status=result["status"],reviewer_note=body.reviewer_note,
        reviewed_by=str(principal.user_id),reviewed_at=datetime.now(timezone.utc))
    db.add(row)
    AuditService(db).record(event_type="TECHNICAL_QC_ASSESSMENT_RECORDED",case_id=analysis.case_id,analysis_id=analysis.id,
        actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="QC_ASSESSMENT",subject_id=str(row.id),operation="CREATE",
        after_state={"status":result["status"],"rule_count":result["rule_count"],"profile":row.profile_name,"profile_version":row.profile_version},reason=body.reviewer_note)
    db.commit()
    return {"assessment_id":str(row.id),**result,"gate_status":result["status"],"profile_name":row.profile_name,"profile_version":row.profile_version}
