from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from backend.app.auth.authorization import CASE_WRITE_ROLES, case_access_predicate, require_case_permission, require_role, get_accessible_analysis
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    Notification,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    Resource,
    ResourceDiscovery,
)
from backend.app.infrastructure.db.session import get_db
from backend.app.application.analysis import enqueue_analysis, preflight_analysis_resources
from backend.app.infrastructure.audit.service import AuditService
from backend.app.domain.reanalysis import (
    RESOURCE_TRIGGER_TYPE,
    affected_step_for_trigger,
    create_reanalysis,
    detect_change,
    snapshot_analysis_resources,
)

router = APIRouter(tags=["reanalysis"])
RESOURCE_CHANGE_ROLES = frozenset({
    "platform_admin", "organization_admin", "lab_director", "bioinformatician",
})


class ManualReanalysisRequest(BaseModel):
    """Explicit request contract for a laboratory-initiated full reanalysis."""

    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="Laboratory-requested case reanalysis.", min_length=1, max_length=2000)


def _validate_notification_lineage(row: Notification, db: Session) -> None:
    case = None
    if row.case_id is not None:
        case = db.get(Case, row.case_id)
        if case is None or case.organization_id != row.organization_id:
            raise HTTPException(
                status_code=409,
                detail="Notification case does not belong to its organization",
            )

    analysis = None
    if row.analysis_id is not None:
        analysis = db.get(Analysis, row.analysis_id)
        if analysis is None or (case is not None and analysis.case_id != case.id):
            raise HTTPException(
                status_code=409,
                detail="Notification analysis does not match its case",
            )
        if case is None:
            case = db.get(Case, analysis.case_id)
            if case is None or case.organization_id != row.organization_id:
                raise HTTPException(
                    status_code=409,
                    detail="Notification analysis does not belong to its organization",
                )

    if row.candidate_id is not None:
        candidate = db.get(ReanalysisCandidate, row.candidate_id)
        if candidate is not None:
            candidate_case = db.get(Case, candidate.case_id)
            candidate_parent = (
                analysis
                if analysis is not None and analysis.id == candidate.parent_analysis_id
                else db.get(Analysis, candidate.parent_analysis_id)
            )
        else:
            candidate_case = candidate_parent = None
        if (
            candidate is None
            or candidate.organization_id != row.organization_id
            or candidate_case is None
            or candidate_case.organization_id != row.organization_id
            or candidate_parent is None
            or candidate_parent.case_id != candidate.case_id
            or (case is not None and candidate.case_id != case.id)
            or (
                analysis is not None
                and candidate.parent_analysis_id != analysis.id
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="Notification candidate does not match its organization and case context",
            )
        _validate_candidate_event_lineage(candidate, db)

    if row.notification_type == "RESOURCE_RELEASE_DISCOVERED":
        metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
        try:
            resource_id = UUID(str(metadata.get("resource_id")))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Resource notification is missing a valid resource reference",
            ) from exc
        resource = db.get(Resource, resource_id)
        if resource is None or resource.organization_id not in {
            None,
            row.organization_id,
        }:
            raise HTTPException(
                status_code=409,
                detail="Resource notification does not belong to its organization",
            )
        try:
            discovery_id = UUID(str(metadata.get("discovery_id")))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="Resource notification is missing a valid discovery reference",
            ) from exc
        discovery = db.get(ResourceDiscovery, discovery_id)
        if discovery is None or discovery.resource_id != resource.id:
            raise HTTPException(
                status_code=409,
                detail="Resource notification does not match its discovered release",
            )


def _validate_candidate_event_lineage(candidate: ReanalysisCandidate, db: Session) -> None:
    """Fail closed when a candidate's optional change event crosses governance scope."""
    if candidate.change_event_id is None:
        return
    event = db.get(ReanalysisChangeEvent, candidate.change_event_id)
    if (
        event is None
        or event.organization_id != candidate.organization_id
        or event.trigger_type != candidate.trigger_type
        or RESOURCE_TRIGGER_TYPE.get(str(event.resource_kind).upper()) != event.trigger_type
    ):
        raise HTTPException(
            status_code=409,
            detail="Reanalysis candidate does not match its change event",
        )
    try:
        expected_step = affected_step_for_trigger(candidate.trigger_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail="Reanalysis candidate has an unsupported trigger",
        ) from exc
    if candidate.earliest_affected_step != expected_step:
        raise HTTPException(
            status_code=409,
            detail="Reanalysis candidate recomputation step does not match its trigger",
        )
    if event.resource_id is not None:
        resource = db.get(Resource, event.resource_id)
        if (
            resource is None
            or resource.organization_id not in {None, candidate.organization_id}
        ):
            raise HTTPException(
                status_code=409,
                detail="Reanalysis change event resource does not belong to its organization",
            )


def _require_notification_case_access(
    row: Notification, db: Session, principal: Principal
) -> None:
    """Recheck case grants when a notification is read, including after creation."""
    case = db.get(Case, row.case_id) if row.case_id is not None else None
    if case is None and row.analysis_id is not None:
        analysis = db.get(Analysis, row.analysis_id)
        case = db.get(Case, analysis.case_id) if analysis is not None else None
    if case is None and row.candidate_id is not None:
        candidate = db.get(ReanalysisCandidate, row.candidate_id)
        case = db.get(Case, candidate.case_id) if candidate is not None else None
    if case is not None:
        require_case_permission(case, principal, db, "read")
    elif any(value is not None for value in (row.case_id, row.analysis_id, row.candidate_id)):
        raise HTTPException(status_code=404, detail="Notification not found")


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
    visible_rows = []
    for row in rows:
        _validate_notification_lineage(row, db)
        try:
            _require_notification_case_access(row, db, principal)
        except HTTPException as exc:
            # Notifications created before case access was revoked (or before
            # recipient scoping was enforced) must not poison the whole inbox.
            # The unread item remains durable for authorized case readers.
            if exc.status_code != 404:
                raise
            continue
        visible_rows.append(row)
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
    } for row in visible_rows]


@router.post("/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    row = db.get(Notification, notification_id)
    if not row or row.organization_id != principal.organization_id or row.user_id != principal.user_id:
        raise HTTPException(status_code=404, detail="Notification not found")
    _validate_notification_lineage(row, db)
    _require_notification_case_access(row, db, principal)
    from datetime import datetime, timezone
    if row.status != "READ" or row.read_at is None:
        row.status = "READ"
        row.read_at = row.read_at or datetime.now(timezone.utc)
        db.commit()
    return {"notification_id": str(row.id), "status": row.status}


@router.get("/reanalysis/candidates")
def list_candidates(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    child_analysis = aliased(Analysis)
    rows = db.execute(
        select(
            ReanalysisCandidate,
            child_analysis.status.label("child_analysis_status"),
        )
        .join(Analysis, Analysis.id == ReanalysisCandidate.parent_analysis_id)
        .join(Case, Case.id == ReanalysisCandidate.case_id)
        .outerjoin(child_analysis, child_analysis.id == ReanalysisCandidate.child_analysis_id)
        .where(
            ReanalysisCandidate.organization_id == principal.organization_id,
            case_access_predicate(principal, "read"),
            ReanalysisCandidate.case_id == Analysis.case_id,
            or_(
                ReanalysisCandidate.child_analysis_id.is_(None),
                and_(
                    child_analysis.case_id == ReanalysisCandidate.case_id,
                    child_analysis.parent_analysis_id == ReanalysisCandidate.parent_analysis_id,
                ),
            ),
        )
        .order_by(ReanalysisCandidate.created_at.desc())
        .limit(100)
    ).all()
    for row, _child_analysis_status in rows:
        _validate_candidate_event_lineage(row, db)
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
        "child_analysis_status": child_status,
        "created_at": row.created_at,
        "acted_at": row.acted_at,
    } for row, child_status in rows]


@router.post("/analyses/{analysis_id}/reanalysis")
def request_reanalysis(
    analysis_id: UUID,
    payload: ManualReanalysisRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    parent = get_accessible_analysis(analysis_id, db, principal, "write")
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
        plan = preflight_analysis_resources(
            db,
            analysis=child,
            organization_id=principal.organization_id,
        )
    except (ValueError, KeyError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if plan is not None and not plan.is_ready:
        db.commit()
        db.refresh(child)
        return {
            "analysis_id": str(child.id),
            "parent_analysis_id": str(parent.id),
            "analysis_version": child.analysis_version,
            "status": child.status,
            "task_id": None,
            "resource_plan_status": plan.status,
            "resource_issues": [
                {
                    "capability": issue.capability,
                    "required": issue.required,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in plan.issues
            ],
            "candidate_id": str(candidate.id) if candidate else None,
        }

    try:
        task_id = enqueue_analysis(db, child)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This reanalysis child is not in a retryable execution state.",
                "analysis_id": str(child.id),
                "status": child.status,
            },
        ) from exc
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
    _validate_candidate_event_lineage(candidate, db)
    if candidate.status not in {"PENDING", "STARTED"}:
        raise HTTPException(status_code=409, detail="This reanalysis candidate has already been completed.")

    parent = get_accessible_analysis(candidate.parent_analysis_id, db, principal, "write")
    if candidate.case_id != parent.case_id:
        raise HTTPException(
            status_code=409,
            detail="Reanalysis candidate case does not match its parent analysis",
        )
    if parent.status != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="Only a successfully completed parent analysis can be reanalyzed.")

    child = db.get(Analysis, candidate.child_analysis_id) if candidate.child_analysis_id else None
    if child is not None and (
        child.case_id != parent.case_id or child.parent_analysis_id != parent.id
    ):
        raise HTTPException(
            status_code=409,
            detail="Reanalysis child does not match its candidate parent and case",
        )

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
        plan = preflight_analysis_resources(
            db,
            analysis=child,
            organization_id=principal.organization_id,
        )
    except (ValueError, KeyError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if plan is not None and not plan.is_ready:
        candidate.status = "PENDING"
        candidate.acted_at = None
        db.add(candidate)
        db.commit()
        db.refresh(child)
        return {
            "analysis_id": str(child.id),
            "parent_analysis_id": str(parent.id),
            "analysis_version": child.analysis_version,
            "status": child.status,
            "task_id": None,
            "resource_plan_status": plan.status,
            "resource_issues": [
                {
                    "capability": issue.capability,
                    "required": issue.required,
                    "code": issue.code,
                    "message": issue.message,
                }
                for issue in plan.issues
            ],
            "candidate_id": str(candidate.id),
            "earliest_affected_step": candidate.earliest_affected_step,
        }

    try:
        task_id = enqueue_analysis(db, child)
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "This reanalysis child is not in a retryable execution state.",
                "analysis_id": str(child.id),
                "candidate_id": str(candidate.id),
                "status": child.status,
            },
        ) from exc
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
    require_role(principal, RESOURCE_CHANGE_ROLES)
    trigger_type = str(payload.get("trigger_type") or "").upper()
    resource_kind = str(payload.get("resource_kind") or "").upper()
    resource_name = str(payload.get("resource_name") or "").strip()
    if not trigger_type or not resource_kind or not resource_name:
        raise HTTPException(status_code=400, detail="trigger_type, resource_kind and resource_name are required")
    if RESOURCE_TRIGGER_TYPE.get(resource_kind) != trigger_type:
        raise HTTPException(
            status_code=422,
            detail="resource_kind and trigger_type do not form a supported resource-change pair",
        )

    try:
        resource_id = UUID(str(payload["resource_id"])) if payload.get("resource_id") else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="resource_id must be a valid UUID") from exc
    if resource_id is not None:
        resource = db.get(Resource, resource_id)
        if resource is None or resource.organization_id not in {None, principal.organization_id}:
            raise HTTPException(status_code=404, detail="Resource not found")
        if str(resource.resource_type).upper() != resource_kind or resource.name != resource_name:
            raise HTTPException(
                status_code=422,
                detail="resource_id must match resource_kind and resource_name",
            )
    candidates = detect_change(
        db,
        organization_id=principal.organization_id,
        trigger_type=trigger_type,
        resource_kind=resource_kind,
        resource_name=resource_name,
        new_version=payload.get("new_version"),
        new_checksum=payload.get("new_checksum"),
        resource_id=resource_id,
        commit=False,
    )
    try:
        AuditService(db).record(
            event_type="REANALYSIS_RESOURCE_CHANGE_REGISTERED",
            case_id=None,
            analysis_id=None,
            actor_type="HUMAN",
            actor_id=str(principal.user_id),
            subject_type="RESOURCE",
            subject_id=str(resource_id) if resource_id is not None else f"{resource_kind}:{resource_name}",
            operation="REGISTER_CHANGE_EVENT",
            after_state={
                "trigger_type": trigger_type,
                "resource_kind": resource_kind,
                "resource_name": resource_name,
                "resource_id": str(resource_id) if resource_id is not None else None,
                "new_version": payload.get("new_version"),
                "candidate_count": len(candidates),
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "change_registered": True,
        "candidates_created": len(candidates),
    }


@router.post("/analyses/{analysis_id}/provenance/snapshot")
def snapshot(
    analysis_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    analysis = get_accessible_analysis(analysis_id, db, principal, "write")
    require_role(principal, CASE_WRITE_ROLES)
    if analysis.status != "SUCCEEDED":
        raise HTTPException(status_code=409, detail="Only completed analyses can be snapshotted.")
    count = snapshot_analysis_resources(db, analysis, commit=False)
    AuditService(db).record(
        event_type="ANALYSIS_RESOURCE_PROVENANCE_SNAPSHOTTED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="ANALYSIS_RESOURCE_SNAPSHOT",
        subject_id=str(analysis.id),
        operation="SNAPSHOT",
        after_state={"snapshot_count": count},
    )
    db.commit()
    return {"analysis_id": str(analysis.id), "snapshot_count": count}
