from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from backend.app.domain.reanalysis import (
    create_reanalysis,
    detect_change,
    snapshot_analysis_resources,
)

router = APIRouter(tags=["reanalysis"])


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
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    parent = get_accessible_analysis(analysis_id, db, principal)
    require_role(principal, CASE_WRITE_ROLES)
    trigger_type = str(payload.get("trigger_type") or "MANUAL").upper()
    reason = str(payload.get("reason") or "Laboratory-requested case reanalysis.")
    try:
        child, candidate = create_reanalysis(
            db,
            parent=parent,
            trigger_type=trigger_type,
            requested_by=principal.user_id,
            reason=reason,
            change_event_id=UUID(str(payload["change_event_id"])) if payload.get("change_event_id") else None,
            affected_step=str(payload["earliest_affected_step"]) if payload.get("earliest_affected_step") else None,
        )
        task_id = enqueue_analysis(db, child)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "analysis_id": str(child.id),
        "parent_analysis_id": str(parent.id),
        "analysis_version": child.analysis_version,
        "status": child.status,
        "task_id": task_id,
        "candidate_id": str(candidate.id) if candidate else None,
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
