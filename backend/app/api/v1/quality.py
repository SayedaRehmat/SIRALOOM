from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, FiniteFloat
from sqlalchemy import or_, select
from backend.app.auth.authorization import (
    CASE_WRITE_ROLES,
    READ_ROLES,
    REVIEW_ROLES,
    get_accessible_analysis,
    require_analysis_artifact,
    require_role,
)
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Artifact, Assay, TechnicalQCObservation, QCAssessment
from backend.app.infrastructure.db.session import get_db
from backend.app.domain.quality_provenance import qc_observation_snapshot
from backend.app.quality import assess_metrics, normalize_rules

router = APIRouter(tags=["technical-quality"])
ASSAY_ADMIN_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director"})

class AssayInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    assay_type: str = Field(min_length=1, max_length=100)
    configuration: dict = Field(default_factory=dict)
    status: str = Field(default="ACTIVE", max_length=50)

class QCObservationInput(BaseModel):
    artifact_id: UUID | None = None
    metric_name: str = Field(min_length=1, max_length=150)
    metric_value: FiniteFloat | None = None
    metric_unit: str | None = Field(default=None, max_length=50)
    source: str = Field(default="LAB_QC", max_length=100)
    source_version: str | None = Field(default=None, max_length=100)
    metadata: dict = Field(default_factory=dict)

class QCAssessmentInput(BaseModel):
    metrics: dict[str, FiniteFloat | int | None]
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
    require_role(principal, ASSAY_ADMIN_ROLES)
    if body.status not in {"ACTIVE", "INACTIVE"}:
        raise HTTPException(400, "Assay status must be ACTIVE or INACTIVE")
    try:
        rules = normalize_rules(body.configuration)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, f"Invalid assay QC configuration: {exc}") from exc
    if body.status == "ACTIVE" and not rules:
        raise HTTPException(400, "An active assay QC profile requires at least one valid QC rule")
    row = Assay(id=uuid4(), organization_id=principal.organization_id, name=body.name.strip(), version=body.version.strip(),
                assay_type=body.assay_type.strip(), configuration=body.configuration, status=body.status)
    db.add(row)
    AuditService(db).record(event_type="ASSAY_PROFILE_CREATED", case_id=None, analysis_id=None, actor_type="HUMAN",
        actor_id=str(principal.user_id), subject_type="ASSAY", subject_id=str(row.id), operation="CREATE", after_state=_assay(row))
    db.commit(); return _assay(row)

@router.get("/assays")
def list_assays(db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, READ_ROLES)
    rows=list(db.scalars(select(Assay).where(Assay.organization_id==principal.organization_id).order_by(Assay.name, Assay.version)))
    return {"assays": [_assay(x) for x in rows]}

@router.post("/analyses/{analysis_id}/quality/observations", status_code=201)
def record_qc_observation(analysis_id: UUID, body: QCObservationInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal, "write")
    require_role(principal, CASE_WRITE_ROLES)
    if body.artifact_id is not None:
        require_analysis_artifact(analysis, body.artifact_id, db)
    row=TechnicalQCObservation(id=uuid4(), analysis_id=analysis.id, artifact_id=body.artifact_id,
        metric_name=body.metric_name.strip(), metric_value=body.metric_value,
        metric_unit=body.metric_unit, source=body.source, source_version=body.source_version, metadata_json=body.metadata)
    db.add(row)
    # _obs includes the insert-generated created_at value in the audit snapshot.
    db.flush()
    AuditService(db).record(event_type="TECHNICAL_QC_OBSERVATION_RECORDED", case_id=analysis.case_id, analysis_id=analysis.id,
        actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="TECHNICAL_QC", subject_id=str(row.id), operation="CREATE", after_state=_obs(row))
    db.commit(); return _obs(row)

@router.get("/analyses/{analysis_id}/quality")
def get_quality(analysis_id: UUID, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, READ_ROLES)
    observations=list(db.scalars(select(TechnicalQCObservation).where(TechnicalQCObservation.analysis_id==analysis.id).order_by(TechnicalQCObservation.created_at, TechnicalQCObservation.id)))
    assessments=list(db.scalars(select(QCAssessment).where(QCAssessment.analysis_id==analysis.id).order_by(QCAssessment.created_at.desc())))
    for observation in observations:
        if observation.artifact_id is not None:
            require_analysis_artifact(analysis, observation.artifact_id, db)
    assay=db.get(Assay, analysis.assay_id) if analysis.assay_id else None
    if assay is not None and assay.organization_id != principal.organization_id:
        raise HTTPException(409, "Analysis assay reference is outside its organization")
    qc_artifacts = list(db.scalars(
        select(Artifact)
        .where(
            Artifact.case_id == analysis.case_id,
            or_(Artifact.analysis_id.is_(None), Artifact.analysis_id == analysis.id),
            Artifact.artifact_type.in_(("VCF", "NORMALIZED_VCF")),
            Artifact.validation_status.in_(("VALID", "VALIDATED")),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    ))
    for artifact in qc_artifacts:
        require_analysis_artifact(analysis, artifact.id, db)
    latest_metrics: dict[str, float | None] = {}
    for observation in observations:
        latest_metrics[observation.metric_name] = observation.metric_value
    current_observation_snapshot = qc_observation_snapshot(db, analysis, observations)

    def assessment_is_current(assessment: QCAssessment) -> bool:
        if (
            assay is None
            or assessment.observation_snapshot is None
            or assessment.observation_snapshot != current_observation_snapshot
            or (assessment.metrics_json or {}) != latest_metrics
            or assessment.assay_id != assay.id
            or assessment.profile_name != assay.name
            or assessment.profile_version != assay.version
            or not assessment.reviewed_by
            or not assessment.reviewed_at
        ):
            return False
        try:
            current_result = assess_metrics(assessment.metrics_json or {}, assay.configuration)
        except (KeyError, TypeError, ValueError):
            return False
        return (
            current_result["status"] == assessment.status == assessment.gate_status
            and current_result["metrics"] == (assessment.evaluated_rules or [])
        )

    return {"analysis_id": str(analysis.id), "assay": _assay(assay) if assay else None,
            "available_artifacts": [{"artifact_id": str(a.id), "filename": a.filename,
                                     "artifact_type": a.artifact_type, "sha256": a.sha256}
                                    for a in qc_artifacts],
            "observations": [_obs(x) for x in observations],
            "assessments": [{"id":str(x.id),"status":x.status,"gate_status":x.gate_status,"profile_name":x.profile_name,
                             "profile_version":x.profile_version,"metrics":x.metrics_json or {},"evaluated_rules":x.evaluated_rules or [],
                             "observation_snapshot":x.observation_snapshot,
                             "is_current":assessment_is_current(x),
                             "clinical_gate_status":x.gate_status if assessment_is_current(x) else "REASSESSMENT_REQUIRED",
                             "reviewer_note":x.reviewer_note,"reviewed_by":x.reviewed_by,"reviewed_at":x.reviewed_at.isoformat() if x.reviewed_at else None,
                             "created_at":x.created_at.isoformat()} for x in assessments]}

@router.post("/analyses/{analysis_id}/quality/assess")
def assess_quality(analysis_id: UUID, body: QCAssessmentInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal, "review")
    require_role(principal, REVIEW_ROLES)
    assay=db.get(Assay, analysis.assay_id) if analysis.assay_id else None
    if assay and assay.organization_id != principal.organization_id:
        raise HTTPException(403,"Assay is not accessible")
    config=assay.configuration if assay else {}
    observations=list(db.scalars(
        select(TechnicalQCObservation)
        .where(TechnicalQCObservation.analysis_id == analysis.id)
        .order_by(TechnicalQCObservation.created_at, TechnicalQCObservation.id)
    ))
    persisted_metrics: dict[str, float | None] = {}
    for observation in observations:
        persisted_metrics[observation.metric_name] = observation.metric_value
    try:
        observation_snapshot = qc_observation_snapshot(db, analysis, observations)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.metrics != persisted_metrics:
        raise HTTPException(
            409,
            "QC assessment metrics must match the latest persisted technical QC observations",
        )
    try:
        result=assess_metrics(body.metrics, config)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    row=QCAssessment(id=uuid4(),analysis_id=analysis.id,assay_id=assay.id if assay else None,status=result["status"],
        profile_name=assay.name if assay else None,profile_version=assay.version if assay else None,metrics_json=body.metrics,
        evaluated_rules=result["metrics"],observation_snapshot=observation_snapshot,
        gate_status=result["status"],reviewer_note=body.reviewer_note,
        reviewed_by=str(principal.user_id),reviewed_at=datetime.now(timezone.utc))
    db.add(row)
    AuditService(db).record(event_type="TECHNICAL_QC_ASSESSMENT_RECORDED",case_id=analysis.case_id,analysis_id=analysis.id,
        actor_type="HUMAN",actor_id=str(principal.user_id),subject_type="QC_ASSESSMENT",subject_id=str(row.id),operation="CREATE",
        after_state={"status":result["status"],"rule_count":result["rule_count"],"profile":row.profile_name,"profile_version":row.profile_version},reason=body.reviewer_note)
    db.commit()
    return {"assessment_id":str(row.id),**result,"gate_status":result["status"],"profile_name":row.profile_name,"profile_version":row.profile_version}
