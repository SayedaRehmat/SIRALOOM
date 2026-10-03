from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import CASE_WRITE_ROLES, require_role, get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisResourceSnapshot,
    Notification,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.application.analysis import enqueue_analysis
from backend.app.infrastructure.audit.service import AuditService
from backend.app.domain.reanalysis import (
    create_reanalysis,
    detect_change,
    snapshot_analysis_resources,
)

router = APIRouter(tags=["reanalysis"])


class ManualReanalysisRequest(BaseModel):
    """Explicit request contract for a laboratory-initiated full reanalysis."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="Laboratory-requested case reanalysis.", min_length=1, max_length=2000)


@router.get("/notifications")
def notifications(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows = db.scalars(
        select(Notification)
        .where(
            Notification.organization_id == principal.organization_id,
            Notification.user_id == principal.user_id,
        )
        .order_by(Notification.created_at.desc())
        .limit(100)
    ).all()
    return [{
        "notification_id": str(row.id),
        "notification_type": row.notification_type,
        "status": row.status,
        "title": row.title,
        "body": row.body,
        "case_id": str(row.case_id) if row.case_id else None,
        "analysis_id": str(row.analysis_id) if row.analysis_id else None,
        "candidate_id": str(row.candidate_id) if row.candidate_id else None,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
        "read_at": row.read_at,
    } for row in rows]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    row = db.get(Notification, notification_id)
    if not row or row.organization_id != principal.organization_id or row.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    from datetime import datetime, timezone
    row.status = "READ"
    row.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"notification_id": str(row.id), "status": row.status}


@router.get("/reanalysis/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    rows = db.scalars(
        select(ReanalysisCandidate)
        .where(ReanalysisCandidate.organization_id == principal.organization_id)
        .order_by(ReanalysisCandidate.created_at.desc())
        .limit(100)
    ).all()
    return [{
        "candidate_id": str(row.id),
        "case_id": str(row.case_id),
        "parent_analysis_id": str(row.parent_analysis_id),
        "child_analysis_id": str(row.child_analysis_id) if row.child_analysis_id else None,
        "change_event_id": str(row.change_event_id) if row.change_event_id else None,
        "trigger_type": row.trigger_type,
        "earliest_affected_step": row.earliest_affected_step,
        "reason": row.reason,
        "status": row.status,
        "created_at": row.created_at,
        "acted_at": row.acted_at,
    } for row in rows]


@router.post("/analyses/{analysis_id}/reanalysis")
def request_reanalysis(
    analysis_id: UUID,
    payload: ManualReanalysisRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    parent = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, CASE_WRITE_ROLES)
    reason = payload.reason
    try:
        child, candidate = create_reanalysis(
            db,
            parent=parent,
            trigger_type="MANUAL",
            requested_by=principal.user_id,
            reason=reason,
            change_event_id=None,
            affected_step=None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Manual requests are idempotent for the same parent/version. Never enqueue
    # an already active or completed child a second time.
    if str(child.status) in {"QUEUED", "RUNNING", "SUCCEEDED"}:
        return {
            "analysis_id": str(child.id),
            "parent_analysis_id": str(parent.id),
            "analysis_version": child.analysis_version,
            "status": child.status,
            "task_id": child.queue_task_id,
            "candidate_id": str(candidate.id) if candidate else None,
        }

    try:
        task_id = enqueue_analysis(db, child)
    except Exception as exc:
        AuditService(db).record(
            event_type="REANALYSIS_QUEUE_FAILURE",
            case_id=child.case_id,
            analysis_id=child.id,
            actor_type="SYSTEM",
            actor_id="api",
            operation="QUEUE_REANALYSIS",
            reason=str(exc),
            after_state={
                "analysis_status": str(child.status),
                "queue_task_id": child.queue_task_id,
            },
            payload={"error_type": type(exc).__name__},
        )
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Reanalysis was created but could not be queued. Retry the request.",
                "analysis_id": str(child.id),
            },
        ) from exc

    return {
        "analysis_id": str(child.id),
        "parent_analysis_id": str(parent.id),
        "analysis_version": child.analysis_version,
        "status": child.status,
        "task_id": task_id,
        "candidate_id": str(candidate.id) if candidate else None,
    }


@router.post("/reanalysis/candidates/{candidate_id}/execute")
def execute_reanalysis_candidate(
    candidate_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    """Execute one reviewed change candidate without stranding it on queue failure."""
    require_role(principal, CASE_WRITE_ROLES)
    candidate = db.get(ReanalysisCandidate, candidate_id)
    if not candidate or candidate.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Reanalysis candidate not found")
    if candidate.status not in {"PENDING", "STARTED"}:
        raise HTTPException(status_code=409, detail="This reanalysis candidate has already been completed.")

    parent = get_accessible_analysis(candidate.parent_analysis_id, db, principal)
    if parent.status != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="Only a successfully completed parent analysis can be reanalyzed.")

    child = db.get(Analysis, candidate.child_analysis_id) if candidate.child_analysis_id else None

    if child is None:
        try:
            child, linked_candidate = create_reanalysis(
                db,
                parent=parent,
                trigger_type=candidate.trigger_type,
                requested_by=principal.user_id,
                reason=candidate.reason,
                change_event_id=candidate.change_event_id,
                affected_step=candidate.earliest_affected_step,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        candidate = linked_candidate or candidate

    # A candidate can be retried after queue infrastructure failure. Once the
    # child is queued/running/completed, return its durable state instead of
    # dispatching a second task.
    if str(child.status) in {"QUEUED", "RUNNING", "SUCCEEDED"}:
        return {
            "analysis_id": str(child.id),
            "parent_analysis_id": str(parent.id),
            "analysis_version": child.analysis_version,
            "status": child.status,
            "task_id": child.queue_task_id,
            "candidate_id": str(candidate.id),
            "earliest_affected_step": candidate.earliest_affected_step,
        }

    try:
        task_id = enqueue_analysis(db, child)
    except Exception as exc:
        candidate.status = "PENDING"
        candidate.acted_at = None
        db.add(candidate)
        AuditService(db).record(
            event_type="REANALYSIS_QUEUE_FAILURE",
            case_id=child.case_id,
            analysis_id=child.id,
            actor_type="SYSTEM",
            actor_id="api",
            operation="QUEUE_REANALYSIS_CANDIDATE",
            reason=str(exc),
            payload={
                "candidate_id": str(candidate.id),
                "child_analysis_id": str(child.id),
                "error_type": type(exc).__name__,
            },
        )
        db.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Reanalysis was created but could not be queued. The candidate remains pending for retry.",
                "analysis_id": str(child.id),
                "candidate_id": str(candidate.id),
            },
        ) from exc

    return {
        "analysis_id": str(child.id),
        "parent_analysis_id": str(parent.id),
        "analysis_version": child.analysis_version,
        "status": child.status,
        "task_id": task_id,
        "candidate_id": str(candidate.id),
        "earliest_affected_step": candidate.earliest_affected_step,
    }


@router.post("/reanalysis/change-events")
def register_change(
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, CASE_WRITE_ROLES)
    trigger_type = str(payload.get("trigger_type") or "").upper()
    resource_kind = str(payload.get("resource_kind") or "").upper()
    resource_name = str(payload.get("resource_name") or "").strip()
    if not trigger_type or not resource_kind or not resource_name:
        raise HTTPException(status_code=400, detail="trigger_type, resource_kind and resource_name are required")

    resource_id = UUID(str(payload["resource_id"])) if payload.get("resource_id") else None
    candidates = detect_change(
        db,
        organization_id=principal.organization_id,
        trigger_type=trigger_type,
        resource_kind=resource_kind,
        resource_name=resource_name,
        new_version=payload.get("new_version"),
        new_checksum=payload.get("new_checksum"),
        resource_id=resource_id,
    )
    return {
        "candidates_created": len(candidates),
        "candidate_ids": [str(x.id) for x in candidates],
    }


@router.post("/analyses/{analysis_id}/provenance/snapshot")
def snapshot(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal)
    if analysis.status != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="Only completed analyses can be snapshotted.")
    count = snapshot_analysis_resources(db, analysis)
    return {"analysis_id": str(analysis.id), "snapshot_count": count}
