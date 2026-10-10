from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.application.analysis import resume_analysis
from backend.app.auth.authorization import REVIEW_ROLES, get_accessible_analysis, require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_human_gate import HumanGateDecision, resolve_human_gate
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis,
    Classification,
    Report,
    ReportabilityDecision,
    WorkflowStep,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(tags=["workflow"])


class HumanGateRequest(BaseModel):
    decision: HumanGateDecision
    reason: str = Field(min_length=1)
    expected_attempt: int = Field(ge=1)
    inputs_changed: bool = False


def _classification_gate_ready(db: Session, analysis_id: UUID) -> bool:
    rows = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == analysis_id)
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )
    latest: dict[UUID, Classification] = {}
    for row in rows:
        latest.setdefault(row.variant_id, row)
    return bool(latest) and all(
        row.state == "FINAL" and row.review_status == "APPROVED"
        for row in latest.values()
    )


def _reportability_gate_ready(db: Session, analysis_id: UUID) -> bool:
    rows = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == analysis_id)
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )
    latest: dict[UUID, Classification] = {}
    for row in rows:
        latest.setdefault(row.variant_id, row)
    if not latest:
        return False
    for variant_id in latest:
        decision = db.scalar(
            select(ReportabilityDecision)
            .where(
                ReportabilityDecision.analysis_id == analysis_id,
                ReportabilityDecision.variant_id == variant_id,
            )
            .order_by(ReportabilityDecision.version.desc())
        )
        if decision is None or decision.status != "FINAL":
            return False
    return True


def _acceptance_allowed(db: Session, analysis: Analysis, step: WorkflowStep) -> None:
    """Reject unsafe generic overrides and require the domain object to exist."""
    if step.step_id == "acmg_assessment":
        has_classification = db.scalar(
            select(Classification.id)
            .where(Classification.analysis_id == analysis.id)
            .limit(1)
        )
        if has_classification is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACMG_MANUAL_CLASSIFICATION_REQUIRED",
                    "message": "The ACMG automation gate cannot be accepted without a persisted human classification. Add the required evidence/criterion assessments first, then resolve the gate.",
                    "next_step": "acmg_assessment",
                },
            )
    elif step.step_id == "review":
        if not _classification_gate_ready(db, analysis.id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "CLASSIFICATION_REVIEW_INCOMPLETE",
                    "message": "All latest classifications must be FINAL and APPROVED before the review gate can be released.",
                    "next_step": "review",
                },
            )
    elif step.step_id == "reportability":
        if not _reportability_gate_ready(db, analysis.id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REPORTABILITY_REVIEW_INCOMPLETE",
                    "message": "Every latest reportability decision must be FINAL before the reportability gate can be released.",
                    "next_step": "reportability",
                },
            )
    elif step.step_id == "export_provenance":
        final_report = db.scalar(
            select(Report.id)
            .where(Report.analysis_id == analysis.id, Report.status == "FINAL")
            .order_by(Report.report_version.desc())
            .limit(1)
        )
        if final_report is None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REPORT_SIGNOUT_REQUIRED",
                    "message": "A final signed-out report is required before provenance export can be released.",
                    "next_step": "report_finalization",
                },
            )
    else:
        # Generic acceptance is deliberately fail-closed for early technical
        # stages. Those stages must explicitly declare a human-safe acceptance
        # contract when their workflow implementation introduces such a gate.
        allowed = bool((step.metadata_json or {}).get("human_gate", {}).get("allow_accept"))
        if not allowed:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "HUMAN_GATE_NOT_DECLARED",
                    "message": f"Workflow step {step.step_id} has no declared human-safe acceptance contract; technical/resource conditions cannot be overridden generically.",
                    "next_step": step.step_id,
                },
            )


@router.post("/analyses/{analysis_id}/workflow/{step_id}/human-gate")
def resolve_human_gate_endpoint(
    analysis_id: UUID,
    step_id: str,
    payload: HumanGateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, REVIEW_ROLES)
    step = db.scalar(
        select(WorkflowStep)
        .where(WorkflowStep.analysis_id == analysis.id, WorkflowStep.step_id == step_id)
        .with_for_update()
    )
    if step is None:
        raise HTTPException(status_code=404, detail="Workflow step not found")
    if step.status != StepStatus.REQUIRES_REVIEW:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_STEP_NOT_WAITING_FOR_REVIEW",
                "message": f"Step {step_id} is {step.status}, not REQUIRES_REVIEW.",
                "current_status": step.status,
            },
        )
    if step.attempt != payload.expected_attempt:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "WORKFLOW_GATE_VERSION_CONFLICT",
                "message": "The workflow step changed since the reviewer opened the gate.",
                "expected_attempt": payload.expected_attempt,
                "current_attempt": step.attempt,
            },
        )

    if payload.decision is HumanGateDecision.REJECT_AND_RETRY and not payload.inputs_changed:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "RETRY_INPUT_CHANGE_REQUIRED",
                "message": "Reject-and-retry requires a documented input/context/resource change; otherwise the worker would repeat the same condition indefinitely.",
            },
        )

    if payload.decision in {HumanGateDecision.ACCEPT, HumanGateDecision.OVERRIDE}:
        _acceptance_allowed(db, analysis, step)

    try:
        transition = resolve_human_gate(
            step_id,
            payload.decision,
            current_status=step.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.now(timezone.utc)
    current_metadata = dict(step.metadata_json or {})
    prior_gate = dict(current_metadata.get("human_gate") or {})
    cycle = int(prior_gate.get("cycle") or 0) + 1
    current_metadata["human_gate"] = {
        **prior_gate,
        "cycle": cycle,
        "decision": transition.decision.value,
        "reason": payload.reason.strip(),
        "actor_id": str(principal.user_id),
        "resolved_at": now.isoformat(),
        "workflow_action": transition.workflow_action.value,
        "next_step": transition.next_step,
        "inputs_changed": payload.inputs_changed,
        "allow_accept": True,
    }
    current_metadata["next_step"] = transition.next_step
    step.status = transition.resulting_status
    step.updated_at = now
    step.last_heartbeat = now
    step.error_code = None if transition.resulting_status is StepStatus.SUCCEEDED else step.error_code
    step.error_message = None if transition.resulting_status is StepStatus.SUCCEEDED else step.error_message
    step.metadata_json = current_metadata
    db.add(step)

    AuditService(db).record(
        event_type="WORKFLOW_HUMAN_GATE_RESOLVED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="WORKFLOW_STEP",
        subject_id=f"{analysis.id}:{step_id}",
        operation="RESOLVE_HUMAN_GATE",
        before_state={"status": StepStatus.REQUIRES_REVIEW.value, "attempt": payload.expected_attempt},
        after_state={
            "status": transition.resulting_status.value,
            "decision": transition.decision.value,
            "next_step": transition.next_step,
            "cycle": cycle,
        },
        reason=payload.reason.strip(),
        payload={"inputs_changed": payload.inputs_changed},
    )

    if transition.resulting_status is StepStatus.REQUIRES_REVIEW:
        analysis.status = AnalysisStatus.REQUIRES_REVIEW
        analysis.completed_at = None
        db.add(analysis)
        db.commit()
        return {
            "analysis_id": str(analysis.id),
            "step_id": step_id,
            "status": step.status,
            "workflow_action": transition.workflow_action.value,
            "next_step": transition.next_step,
            "cycle": cycle,
            "workflow_resume_queued": False,
        }

    analysis.status = AnalysisStatus.REQUIRES_REVIEW
    analysis.completed_at = None
    db.add(analysis)
    db.commit()
    resume_queued = resume_analysis(db, analysis) is not None or analysis.status == AnalysisStatus.QUEUED
    return {
        "analysis_id": str(analysis.id),
        "step_id": step_id,
        "status": step.status,
        "workflow_action": transition.workflow_action.value,
        "next_step": transition.next_step,
        "cycle": cycle,
        "workflow_resume_queued": resume_queued,
    }
