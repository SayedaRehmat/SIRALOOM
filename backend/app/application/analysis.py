from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, Artifact
from backend.app.infrastructure.queue.celery_app import run_analysis_task


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
) -> str:
    if analysis.status not in {
        AnalysisStatus.CREATED,
        AnalysisStatus.FAILED,
    }:
        raise ValueError(
            f"Analysis cannot be started from status {analysis.status}"
        )

    task = run_analysis_task.delay(str(analysis.id))

    analysis.status = AnalysisStatus.QUEUED
    analysis.queue_task_id = task.id

    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    return task.id
