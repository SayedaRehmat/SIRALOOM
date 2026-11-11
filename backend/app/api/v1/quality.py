from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, FiniteFloat
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
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
from backend.app.infrastructure.db.assay_validation import AssayValidationDecision, AssayValidationSubmission
from backend.app.domain.assay_validation import AssayValidationError, current_approved_validation, latest_validation_decision, normalize_validation_submission, validation_payload_sha256
from backend.app.infrastructure.db.session import get_db
from backend.app.domain.quality_provenance import qc_observation_snapshot, validate_qc_source_artifact
from backend.app.quality import assess_metrics, normalize_rules

router = APIRouter(tags=["technical-quality"])
ASSAY_ADMIN_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director"})

class AssayInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    assay_type: str = Field(min_length=1, max_length=100)
    configuration: dict = Field(default_factory=dict)
    status: str = Field(default="ACTIVE", max_length=50)

class AssayValidationSubmissionInput(BaseModel):
    validation_type: str = Field(min_length=1, max_length=20)
    protocol_identifier: str = Field(min_length=1, max_length=300)
    protocol_version: str = Field(min_length=1, max_length=100)
    intended_use: str = Field(min_length=1, max_length=5000)
    specimen_types: list[str] = Field(min_length=1)
    variant_classes: list[str] = Field(min_length=1)
    reference_builds: list[str] = Field(min_length=1)
    workflow_id: str = Field(min_length=1, max_length=200)
    workflow_version: str = Field(min_length=1, max_length=100)
    pipeline_components: list[dict] = Field(min_length=1)
    performance_specifications: list[dict] = Field(min_length=1)
    study_design_summary: str = Field(min_length=1, max_length=12000)
    sample_count: int = Field(gt=0)
    evidence_manifest: list[dict] = Field(min_length=1)


class AssayValidationDecisionInput(BaseModel):
    decision: str = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=5000)
    evidence_reference: str | None = Field(default=None, max_length=2000)
    effective_at: datetime | None = None
    expires_at: datetime | None = None

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

def _lock_analysis_for_qc_write(db, analysis):
    """Serialize QC mutations with report sign-out on the analysis row."""
    db.refresh(analysis, with_for_update=True)

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
    name = body.name.strip()
    version = body.version.strip()
    assay_type = body.assay_type.strip()
    if not name or not version or not assay_type:
        raise HTTPException(422, "Assay name, version and type must be non-empty after trimming")
    existing = db.scalars(
        select(Assay.id).where(
            Assay.organization_id == principal.organization_id,
            Assay.name == name,
            Assay.version == version,
        )
    ).all()
    if existing:
        raise HTTPException(409, "An assay with this organization, name and version already exists")
    row = Assay(
        id=uuid4(),
        organization_id=principal.organization_id,
        name=name,
        version=version,
        assay_type=assay_type,
        configuration=body.configuration,
        status=body.status,
    )
    db.add(row)
    AuditService(db).record(event_type="ASSAY_PROFILE_CREATED", case_id=None, analysis_id=None, actor_type="HUMAN",
        actor_id=str(principal.user_id), subject_type="ASSAY", subject_id=str(row.id), operation="CREATE", after_state=_assay(row))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "An assay with this organization, name and version already exists") from exc
    return _assay(row)

@router.get("/assays")
def list_assays(db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, READ_ROLES)
    rows=list(db.scalars(select(Assay).where(Assay.organization_id==principal.organization_id).order_by(Assay.name, Assay.version)))
    return {"assays": [_assay(x) for x in rows]}

def _validation_submission(row, decision=None):
    return {
        "id": str(row.id), "assay_id": str(row.assay_id), "revision": row.revision,
        "validation_type": row.validation_type, "protocol_identifier": row.protocol_identifier,
        "protocol_version": row.protocol_version, "intended_use": row.intended_use,
        "specimen_types": row.specimen_types or [], "variant_classes": row.variant_classes or [],
        "reference_builds": row.reference_builds or [], "workflow_id": row.workflow_id,
        "workflow_version": row.workflow_version, "pipeline_components": row.pipeline_components or [],
        "performance_specifications": row.performance_specifications or [],
        "study_design_summary": row.study_design_summary, "sample_count": row.sample_count,
        "evidence_manifest": row.evidence_manifest or [], "payload_sha256": row.payload_sha256,
        "submitted_by": str(row.submitted_by), "submitted_at": row.submitted_at.isoformat(),
        "latest_decision": ({
            "id": str(decision.id), "decision": decision.decision, "reason": decision.reason,
            "evidence_reference": decision.evidence_reference,
            "effective_at": decision.effective_at.isoformat() if decision.effective_at else None,
            "expires_at": decision.expires_at.isoformat() if decision.expires_at else None,
            "actor_id": str(decision.actor_id), "created_at": decision.created_at.isoformat(),
        } if decision else None),
    }


@router.post("/assays/{assay_id}/validations", status_code=201)
def submit_assay_validation(assay_id: UUID, body: AssayValidationSubmissionInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, ASSAY_ADMIN_ROLES)
    assay = db.get(Assay, assay_id)
    if assay is None or assay.organization_id != principal.organization_id:
        raise HTTPException(404, "Assay not found")
    db.refresh(assay, with_for_update=True)
    try:
        payload = normalize_validation_submission(body.model_dump())
    except AssayValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    latest_revision = db.scalar(select(func.max(AssayValidationSubmission.revision)).where(AssayValidationSubmission.assay_id == assay.id)) or 0
    previous = db.scalar(select(AssayValidationSubmission).where(AssayValidationSubmission.assay_id == assay.id).order_by(AssayValidationSubmission.revision.desc()).limit(1))
    row = AssayValidationSubmission(
        id=uuid4(), organization_id=assay.organization_id, assay_id=assay.id,
        revision=int(latest_revision) + 1, **payload,
        payload_sha256=validation_payload_sha256(payload),
        supersedes_id=previous.id if previous else None, submitted_by=principal.user_id,
    )
    db.add(row)
    db.flush()
    AuditService(db).record(
        event_type="ASSAY_VALIDATION_SUBMITTED", case_id=None, analysis_id=None,
        actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="ASSAY_VALIDATION",
        subject_id=str(row.id), operation="SUBMIT",
        after_state={"assay_id": str(assay.id), "revision": row.revision, "validation_type": row.validation_type,
                     "protocol_identifier": row.protocol_identifier, "protocol_version": row.protocol_version,
                     "payload_sha256": row.payload_sha256, "scope": {"specimen_types": row.specimen_types,
                     "variant_classes": row.variant_classes, "reference_builds": row.reference_builds,
                     "workflow_id": row.workflow_id, "workflow_version": row.workflow_version},
                     "sample_count": row.sample_count, "evidence_count": len(row.evidence_manifest)},
    )
    db.commit()
    db.refresh(row)
    return _validation_submission(row)


@router.get("/assays/{assay_id}/validations")
def list_assay_validations(assay_id: UUID, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, READ_ROLES)
    assay = db.get(Assay, assay_id)
    if assay is None or assay.organization_id != principal.organization_id:
        raise HTTPException(404, "Assay not found")
    rows = db.scalars(select(AssayValidationSubmission).where(
        AssayValidationSubmission.assay_id == assay.id,
        AssayValidationSubmission.organization_id == principal.organization_id,
    ).order_by(AssayValidationSubmission.revision.desc())).all()
    active = current_approved_validation(db, assay_id=assay.id, organization_id=principal.organization_id)
    return {"assay_id": str(assay.id),
            "current_approval_submission_id": str(active[0].id) if active else None,
            "submissions": [_validation_submission(row, latest_validation_decision(db, row.id)) for row in rows]}


@router.post("/assay-validations/{submission_id}/decision")
def decide_assay_validation(submission_id: UUID, body: AssayValidationDecisionInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    require_role(principal, frozenset({"lab_director"}))
    decision_name = body.decision.strip().upper()
    if decision_name not in {"APPROVE", "REJECT", "SUSPEND", "WITHDRAW"}:
        raise HTTPException(400, "Decision must be APPROVE, REJECT, SUSPEND or WITHDRAW")
    submission = db.get(AssayValidationSubmission, submission_id)
    if submission is None or submission.organization_id != principal.organization_id:
        raise HTTPException(404, "Assay validation submission not found")
    db.refresh(submission, with_for_update=True)
    latest = latest_validation_decision(db, submission.id)
    if latest is not None and (latest.decision != "APPROVE" or decision_name not in {"SUSPEND", "WITHDRAW"}):
        raise HTTPException(409, "This validation submission has already received a terminal decision")
    if latest is None and decision_name in {"SUSPEND", "WITHDRAW"}:
        raise HTTPException(409, "Only an approved validation can be suspended or withdrawn")
    if decision_name == "APPROVE":
        if submission.submitted_by == principal.user_id:
            raise HTTPException(403, "The validation submitter cannot approve their own submission")
        if any(str(item.get("result", "")).upper() != "PASS" for item in (submission.performance_specifications or [])):
            raise HTTPException(409, "Validation cannot be approved while any performance criterion is FAIL or NOT_ASSESSED")
        if body.evidence_reference is None or not body.evidence_reference.strip():
            raise HTTPException(422, "Approval requires a controlled approval evidence reference")
        if body.effective_at is None or body.expires_at is None:
            raise HTTPException(422, "Approval requires explicit effective and expiry timestamps")
        if body.effective_at.tzinfo is None or body.expires_at.tzinfo is None:
            raise HTTPException(422, "Approval timestamps must include timezone information")
        if body.expires_at <= body.effective_at:
            raise HTTPException(422, "Approval expiry must be later than its effective time")
    row = AssayValidationDecision(
        id=uuid4(), submission_id=submission.id, decision=decision_name, reason=body.reason.strip(),
        evidence_reference=body.evidence_reference.strip() if body.evidence_reference else None,
        effective_at=body.effective_at, expires_at=body.expires_at, actor_id=principal.user_id,
    )
    db.add(row)
    db.flush()
    if decision_name == "APPROVE":
        previous_approval = current_approved_validation(db, assay_id=submission.assay_id, organization_id=submission.organization_id)
        if previous_approval is not None and previous_approval[0].id != submission.id:
            db.add(AssayValidationDecision(
                id=uuid4(), submission_id=previous_approval[0].id, decision="SUPERSEDE",
                reason="Superseded by a later approved assay validation submission",
                evidence_reference=body.evidence_reference.strip(), actor_id=principal.user_id,
            ))
    AuditService(db).record(
        event_type="ASSAY_VALIDATION_" + decision_name, case_id=None, analysis_id=None,
        actor_type="HUMAN", actor_id=str(principal.user_id), subject_type="ASSAY_VALIDATION",
        subject_id=str(submission.id), operation=decision_name,
        after_state={"decision_id": str(row.id), "decision": decision_name, "reason": row.reason,
                     "evidence_reference": row.evidence_reference,
                     "effective_at": row.effective_at.isoformat() if row.effective_at else None,
                     "expires_at": row.expires_at.isoformat() if row.expires_at else None},
        reason=row.reason,
    )
    db.commit()
    db.refresh(row)
    return {"decision_id": str(row.id), "submission_id": str(submission.id),
            "decision": row.decision, "created_at": row.created_at.isoformat()}

@router.post("/analyses/{analysis_id}/quality/observations", status_code=201)
def record_qc_observation(analysis_id: UUID, body: QCObservationInput, db=Depends(get_db), principal: Principal=Depends(get_current_principal)):
    analysis=get_accessible_analysis(analysis_id, db, principal, "write")
    require_role(principal, CASE_WRITE_ROLES)
    _lock_analysis_for_qc_write(db, analysis)
    if body.artifact_id is not None:
        artifact = require_analysis_artifact(analysis, body.artifact_id, db)
        try:
            validate_qc_source_artifact(artifact, analysis)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
        try:
            validate_qc_source_artifact(artifact, analysis)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    latest_metrics: dict[str, float | None] = {}
    for observation in observations:
        latest_metrics[observation.metric_name] = observation.metric_value
    try:
        current_observation_snapshot = qc_observation_snapshot(db, analysis, observations)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="QC observation source artifact lineage is invalid",
        ) from exc

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
    _lock_analysis_for_qc_write(db, analysis)
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
