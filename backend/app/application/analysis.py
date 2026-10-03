from __future__ import annotations

from uuid import UUID, uuid4
from types import SimpleNamespace

# Backward-compatible patch seam for existing application tests and callers.
# The actual publisher is resolved lazily by enqueue_analysis.
run_analysis_task = SimpleNamespace(delay=lambda analysis_id: None)

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch, Artifact



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
) -> Analysis:
    artifact = db.get(Artifact, input_artifact_id)

    if artifact is None:
        raise ValueError("Input artifact not found")

    if artifact.case_id != case_id:
        raise ValueError("Input artifact does not belong to this case")

    analysis_configuration = dict(configuration or {})
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
    db.commit()
    db.refresh(analysis)

    return analysis


def enqueue_analysis(
    db: Session,
    analysis: Analysis,
) -> str | None:
    """Persist an execution intent before publishing to Celery.

    The analysis transition and dispatch intent commit atomically. Publication
    is a separate step, so a broker outage cannot leave a QUEUED analysis with
    no durable record that it still needs publication.
    """
    if analysis.status not in {
        AnalysisStatus.CREATED,
        AnalysisStatus.FAILED,
        AnalysisStatus.RESOURCE_FAILURE,
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
    analysis.queue_task_id = None
    db.add(dispatch)
    db.add(analysis)
    db.commit()
    db.refresh(dispatch)
    db.refresh(analysis)

    # Fast path: publish immediately. If the broker is unavailable the durable
    # PENDING row remains and the periodic relay will retry it.
    try:
        from backend.app.infrastructure.queue.celery_app import publish_analysis_dispatch
        return publish_analysis_dispatch(dispatch.id)
    except Exception as exc:
        dispatch.last_error = str(exc)
        dispatch.attempts += 1
        db.add(dispatch)
        db.commit()
        return None
