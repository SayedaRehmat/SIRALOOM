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
        raise ValueError(
            "resource_profile_id conflicts with configuration.resource_profile_id"
        )
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
    """Resolve and persist the governed resource plan before queueing.

    Existing callers that do not declare a resource profile retain the legacy
    behavior. New laboratory/trial analyses opt into the governed contract by
    setting configuration.resource_profile_id.
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
    previous_resource_plan = configuration.get("resource_plan") or {}
    stage_plan = build_workflow_stage_resource_plan(plan)
    configuration["resource_plan"] = plan.snapshot()
    configuration["resource_stage_plan"] = stage_plan
    analysis.configuration = configuration

    # Mirror the preflight projection into the durable workflow-step records.
    # The resource plan remains the authoritative selection snapshot; this
    # projection makes the blocked/limited stage visible to the same workflow
    # APIs that expose execution state, without replacing an already-running
    # or completed step.
    existing_steps = {
        step.step_id: step
        for step in db.scalars(
            select(WorkflowStep).where(WorkflowStep.analysis_id == analysis.id)
        ).all()
    }
    for stage in stage_plan:
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
            metadata["next_step"] = "resource_setup"
            metadata["workflow_action"] = "WAIT_FOR_RESOURCE"
            metadata["resource_blocked"] = True
        elif (
            stage["status"] != "BLOCKED"
            and step.status == "BLOCKED"
            and metadata.get("resource_blocked") is True
        ):
            # A previously resource-blocked stage becomes runnable only after
            # a fresh preflight proves that its required resource is ready.
            # Do not alter failures/review states that were not caused by
            # resource preflight.
            step.status = "PENDING"
            metadata.pop("next_step", None)
            metadata.pop("workflow_action", None)
            metadata.pop("resource_blocked", None)
        step.metadata_json = metadata
        db.add(step)
    db.flush()

    if not plan.is_ready:
        analysis.status = AnalysisStatus.BLOCKED
        analysis.completed_at = None
        db.add(analysis)
        db.flush()
    elif (
        analysis.status == AnalysisStatus.BLOCKED
        and previous_resource_plan.get("status") == "BLOCKED"
    ):
        # Resource recovery is a resumable state transition, not a new
        # analysis. Once required resources qualify, return the analysis to
        # CREATED so the normal start path can create exactly one dispatch.
        analysis.status = AnalysisStatus.CREATED
        analysis.completed_at = None
        db.add(analysis)
        db.flush()

    return plan


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

    db.refresh(locked, with_for_update=True)
    analysis = locked
    if analysis.status == AnalysisStatus.QUEUED:
        return analysis.queue_task_id
    if analysis.status == AnalysisStatus.RUNNING:
        return analysis.queue_task_id

    if analysis.status == AnalysisStatus.BLOCKED:
        configuration = dict(analysis.configuration or {})
        resource_plan = configuration.get("resource_plan") or {}
        if not configuration.get("resource_profile_id") or resource_plan.get("status") != "BLOCKED":
            raise ValueError(
                f"Analysis cannot be started from status {analysis.status}"
            )
    elif analysis.status not in {
        AnalysisStatus.CREATED,
        AnalysisStatus.FAILED,
        AnalysisStatus.RESOURCE_FAILURE,
        # Human gates are durable workflow pauses, not terminal analysis states.
        # A completed human action creates a new dispatch generation so the
        # worker resumes from the first unfinished workflow step.
        AnalysisStatus.REQUIRES_REVIEW,
    }:
        raise ValueError(
            f"Analysis cannot be started from status {analysis.status}"
        )

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
    analysis.queue_task_id = str(dispatch.id)
    db.add(dispatch)
    db.add(analysis)
    db.commit()
    db.refresh(dispatch)
    db.refresh(analysis)

    try:
        from backend.app.infrastructure.queue.celery_app import publish_analysis_dispatch
        return publish_analysis_dispatch(dispatch.id)
    except Exception as exc:
        dispatch.last_error = str(exc)
        dispatch.attempts += 1
        db.add(dispatch)
        db.commit()
        return None
