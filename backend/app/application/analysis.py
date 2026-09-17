from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Analysis, Artifact
from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.queue.celery_app import run_analysis_task


def create_analysis(
    db: Session,
    *,
    case_id,
    input_artifact_id,
    assay_id=None,
    analysis_type,
    workflow_id,
    workflow_version,
    reference_build,
    configuration,
    created_by,
):
    artifact = db.get(Artifact, input_artifact_id)

    if not artifact:
        raise ValueError("Input artifact not found")

    if artifact.case_id != case_id:
        raise ValueError("Input artifact does not belong to this case")

    cfg = dict(configuration)
    cfg["input_artifact_id"] = str(input_artifact_id)

    analysis = Analysis(
        id=uuid4(),
        case_id=case_id,
        assay_id=assay_id,
        analysis_type=analysis_type,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        status=AnalysisStatus.CREATED,
        reference_build=reference_build,
        configuration=cfg,
        created_by=created_by,
    )

    db.add(analysis)

    AuditService(db).record(
        event_type="WORKFLOW_CREATED",
        case_id=case_id,
        analysis_id=analysis.id,
        actor_type="HUMAN",
        actor_id=str(created_by),
        subject_type="ANALYSIS",
        subject_id=str(analysis.id),
        operation="CREATE",
        after_state={
            "workflow_id": workflow_id,
            "workflow_version": workflow_version,
        },
    )

    db.commit()

    return analysis


def enqueue_analysis(db: Session, analysis: Analysis):
    if (
        analysis.status in {
            AnalysisStatus.QUEUED,
            AnalysisStatus.RUNNING,
        }
        and analysis.queue_task_id
    ):
        return analysis.queue_task_id

    analysis.status = AnalysisStatus.QUEUED

    db.commit()

    task = run_analysis_task.delay(str(analysis.id))

    analysis.queue_task_id = task.id

    db.commit()

    AuditService(db).record(
        event_type="WORKFLOW_QUEUED",
        case_id=analysis.case_id,
        analysis_id=analysis.id,
        actor_type="SYSTEM",
        actor_id="queue",
        payload={
            "task_id": task.id,
            "idempotent": False,
        },
    )

    db.commit()

    return task.id
