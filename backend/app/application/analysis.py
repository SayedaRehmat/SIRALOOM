from __future__ import annotations

from uuid import UUID, uuid4
from types import SimpleNamespace

# Backward-compatible patch seam for existing application tests and callers.
# The actual publisher is resolved lazily by enqueue_analysis.
run_analysis_task = SimpleNamespace(delay=lambda analysis_id: None)

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch, Artifact, WorkflowStep
from backend.app.domain.resource_profile_resolver import (
    AnalysisResourcePlan,
    build_workflow_stage_resource_plan,
    resolve_analysis_resource_profile,
)



def create_analysis(
    db: Session,
    *,
    case_id: UUID,
    input_artifact_id: UUID,
    assay_id: UUID | None,
    analysis_type: str,
    workflow_id: str,
    workflow_version: str,
    reference_build: str,
    configuration: dict,
    created_by: UUID | None,
    resource_profile_id: str | None = None,
    commit: bool = True,
) -> Analysis:
    artifact = db.get(Artifact, input_artifact_id)

    if artifact is None:
        raise ValueError("Input artifact not found")

    if artifact.case_id != case_id:
        raise ValueError("Input artifact does not belong to this case")

    analysis_configuration = dict(configuration or {})
    configured_profile_id = analysis_configuration.get("resource_profile_id")
    if resource_profile_id and configured_profile_id and str(resource_profile_id) != str(configured_profile_id):
        raise ValueError("resource_profile_id conflicts with configuration.resource_profile_id")
    if resource_profile_id:
        analysis_configuration["resource_profile_id"] = str(resource_profile_id)
    analysis_configuration["input_artifact_id"] = str(input_artifact_id)

    analysis = Analysis(
        id=uuid4(),
        case_id=case_id,
        parent_analysis_id=None,
        assay_id=assay_id,
        analysis_type=analysis_type,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        status=AnalysisStatus.CREATED,
        queue_task_id=None,
        reference_build=reference_build,
        configuration=analysis_configuration,
        started_at=None,
        completed_at=None,
        created_by=created_by,
    )

    db.add(analysis)
    if commit:
        db.commit()
        db.refresh(analysis)

    return analysis


def preflight_analysis_resources(
    db: Session,
    *,
    analysis: Analysis,
    organization_id: UUID,
) -> AnalysisResourcePlan | None:
    """Resolve and persist an immutable scientific resource plan before dispatch.

    Analyses without a resource_profile_id retain legacy behavior. Profile-bound
    analyses must resolve required resources before they are runnable.
    """
    configuration = dict(analysis.configuration or {})
    profile_id = configuration.get("resource_profile_id")
    if not profile_id:
        return None

    plan = resolve_analysis_resource_profile(
        db,
        organization_id=organization_id,
        profile_id=str(profile_id),
        analysis_reference_build=analysis.reference_build,
    )
    previous_resource_plan = dict(configuration.get("resource_plan") or {})
    configuration["resource_plan"] = plan.snapshot()
    configuration["resource_stage_plan"] = build_workflow_stage_resource_plan(plan)
    analysis.configuration = configuration

    existing_steps = {
        step.step_id: step
        for step in db.scalars(
            select(WorkflowStep).where(WorkflowStep.analysis_id == analysis.id)
        ).all()
    }
    for stage in configuration["resource_stage_plan"]:
        step = existing_steps.get(str(stage["step_id"]))
        if step is None:
            step = WorkflowStep(
                id=uuid4(),
                analysis_id=analysis.id,
                step_id=str(stage["step_id"]),
                step_order=int(stage["order"]),
                status="PENDING",
                attempt=0,
                input_artifacts=[],
                output_artifacts=[],
                metadata_json={},
            )
            db.add(step)
        metadata = dict(step.metadata_json or {})
        metadata["resource_readiness"] = stage
        if stage["status"] == "BLOCKED" and step.status in {"PENDING", "BLOCKED"}:
            step.status = "BLOCKED"
            metadata["resource_blocked"] = True
            metadata["next_step"] = "resource_setup"
            metadata["workflow_action"] = "WAIT_FOR_RESOURCE"
        elif stage["status"] != "BLOCKED" and step.status == "BLOCKED" and metadata.get("resource_blocked"):
            step.status = "PENDING"
            metadata.pop("resource_blocked", None)
            metadata.pop("next_step", None)
            metadata.pop("workflow_action", None)
        step.metadata_json = metadata
        db.add(step)

    db.flush()

    if not plan.is_ready:
        analysis.status = AnalysisStatus.BLOCKED
        analysis.completed_at = None
        db.add(analysis)
        db.flush()
    elif analysis.status == AnalysisStatus.BLOCKED and previous_resource_plan.get("status") == "BLOCKED":
        analysis.status = AnalysisStatus.CREATED
        analysis.completed_at = None
        db.add(analysis)
        db.flush()

    return plan


def _create_dispatch_locked(
    db: Session,
    analysis: Analysis,
) -> AnalysisDispatch:
    """Create the next durable execution intent while the analysis row is locked."""
    next_generation = (
        db.scalar(
            select(func.coalesce(func.max(AnalysisDispatch.dispatch_generation), 0))
            .where(AnalysisDispatch.analysis_id == analysis.id)
        )
        or 0
    ) + 1

    dispatch = AnalysisDispatch(
        id=uuid4(),
        analysis_id=analysis.id,
        dispatch_generation=next_generation,
        status="PENDING",
        task_id=None,
        attempts=0,
        last_error=None,
        published_at=None,
    )
    analysis.status = AnalysisStatus.QUEUED
    # Reserve the deterministic Celery task identity before publication. This
    # lets the worker reject any stale task from an older retry generation even
    # if that broker message arrives after a newer retry has been queued.
    analysis.queue_task_id = str(dispatch.id)
    db.add(dispatch)
    db.add(analysis)
    return dispatch


def _publish_dispatch_after_commit(
    db: Session,
    dispatch: AnalysisDispatch,
) -> str | None:
    db.commit()
    db.refresh(dispatch)
    try:
        from backend.app.infrastructure.queue.celery_app import publish_analysis_dispatch
        return publish_analysis_dispatch(dispatch.id)
    except Exception as exc:
        # The dispatch remains a durable PENDING intent. The periodic outbox
        # relay can retry publication without requiring the human/API caller
        # to remain alive after the database transaction commits.
        dispatch.last_error = str(exc)
        dispatch.attempts += 1
        db.add(dispatch)
        db.commit()
        return None


def enqueue_analysis(
    db: Session,
    analysis: Analysis,
) -> str | None:
    """Serialize start requests and persist one execution intent per start.

    The analysis row is the serialization point for concurrent callers. A
    caller that arrives after another caller has already queued the analysis
    reuses the durable queue pointer instead of creating a second dispatch.
    """
    locked = db.get(Analysis, analysis.id, with_for_update=True)
    if locked is None:
        raise ValueError("Analysis not found")

    # The caller may already have loaded this Analysis into its identity map
    # before waiting on the row lock. Session.get() can then return that stale
    # instance without issuing a SELECT, which would defeat the serialization
    # boundary. Refresh while the row lock is held so the status and queue
    # pointer reflect the committed state of the winner.
    db.refresh(locked, with_for_update=True)
    analysis = locked
    if analysis.status == AnalysisStatus.QUEUED:
        return analysis.queue_task_id
    if analysis.status == AnalysisStatus.RUNNING:
        return analysis.queue_task_id

    if analysis.status not in {
        AnalysisStatus.CREATED,
        AnalysisStatus.FAILED,
        AnalysisStatus.RESOURCE_FAILURE,
    }:
        raise ValueError(
            f"Analysis cannot be started from status {analysis.status}"
        )

    dispatch = _create_dispatch_locked(db, analysis)
    return _publish_dispatch_after_commit(db, dispatch)


def resume_analysis(
    db: Session,
    analysis: Analysis | UUID,
) -> str | None:
    """Resume an analysis after a completed human gate using the durable outbox.

    Human-gate completion commonly leaves the analysis in REQUIRES_REVIEW.
    The row lock makes repeated/concurrent resume requests idempotent, while
    the dispatch row closes the DB-commit-to-broker-publication crash window.
    Callers must invoke this only after their gate-specific validation has
    established that resumption is authorized.
    """
    analysis_id = analysis.id if isinstance(analysis, Analysis) else analysis
    locked = db.get(Analysis, analysis_id, with_for_update=True)
    if locked is None:
        raise ValueError("Analysis not found")

    # Force a fresh read after acquiring the lock because the caller may have
    # loaded the analysis before another worker completed the same human gate.
    db.refresh(locked, with_for_update=True)

    if locked.status in {AnalysisStatus.QUEUED, AnalysisStatus.RUNNING}:
        return locked.queue_task_id

    if locked.status != AnalysisStatus.REQUIRES_REVIEW:
        raise ValueError(
            f"Analysis cannot be resumed from status {locked.status}"
        )

    dispatch = _create_dispatch_locked(db, locked)
    return _publish_dispatch_after_commit(db, dispatch)
