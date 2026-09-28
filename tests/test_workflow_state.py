from backend.app.domain.enums import AnalysisStatus, StepStatus


def test_resource_failure_is_a_first_class_workflow_state():
    assert AnalysisStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"
    assert StepStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"


def test_celery_worker_recovery_contract_is_configured():
    from backend.app.infrastructure.queue.celery_app import run_analysis_task

    assert run_analysis_task.acks_late is True
    assert run_analysis_task.reject_on_worker_lost is True


def test_worker_recovery_preserves_explicit_retry_state_contract():
    from backend.app.domain.enums import StepStatus

    assert StepStatus.RETRYING.value == "RETRYING"
    assert StepStatus.RUNNING.value == "RUNNING"


def test_interrupted_worker_recovery_requeues_running_step_and_partition():
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import (
        Analysis,
        AnalysisPartition,
        AuditEvent,
        Case,
        Organization,
        User,
        WorkflowStep,
    )
    from backend.app.workflows.variant import recover_interrupted_execution

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            Case.__table__,
            Analysis.__table__,
            WorkflowStep.__table__,
            AnalysisPartition.__table__,
            AuditEvent.__table__,
        ],
    )

    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    step_id = uuid4()
    partition_id = uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=5)

    with Session(engine) as db:
        db.add(
            Organization(
                id=organization_id,
                name="Recovery Test Laboratory",
                external_identifier=None,
            )
        )
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject=None,
                email="recovery@test.local",
                display_name="Recovery Test",
                role="ANALYST",
                status="ACTIVE",
            )
        )
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="RECOVERY-001",
                status="ACTIVE",
                clinical_context={},
                language="en",
                created_by=user_id,
            )
        )
        db.add(
            Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="siraloom.variant",
                workflow_version="1.0",
                status=AnalysisStatus.RUNNING,
                queue_task_id="lost-worker-task",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(uuid4())},
                started_at=stale_time,
                completed_at=None,
                created_by=user_id,
            )
        )
        db.add(
            WorkflowStep(
                id=step_id,
                analysis_id=analysis_id,
                step_id="annotate",
                step_order=3,
                status=StepStatus.RUNNING,
                attempt=1,
                last_heartbeat=stale_time,
                started_at=stale_time,
                completed_at=None,
                input_artifacts=[],
                output_artifacts=[],
                error_code=None,
                error_message=None,
                metadata_json={},
            )
        )
        db.add(
            AnalysisPartition(
                id=partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="0:10",
                ordinal=0,
                record_start=0,
                record_end=10,
                variant_count=10,
                status="RUNNING",
                input_artifact_id=None,
                metadata_json={},
                resource_class="LIGHT",
                cpu_request=0.5,
                memory_mb=512,
                attempt=1,
                lease_owner="workflow:lost-worker",
                lease_expires_at=stale_time + timedelta(seconds=900),
                started_at=stale_time,
                completed_at=None,
            )
        )
        db.commit()

        recovered = recover_interrupted_execution(db, analysis_id)

        assert recovered is True
        step = db.get(WorkflowStep, step_id)
        partition = db.get(AnalysisPartition, partition_id)
        analysis = db.get(Analysis, analysis_id)

        assert step.status == StepStatus.RETRYING
        assert step.error_code == "WORKER_INTERRUPTED"
        assert step.metadata_json["next_step"] == "annotate"
        assert partition.status == "READY"
        assert partition.lease_owner is None
        assert partition.lease_expires_at is None
        assert analysis.status == AnalysisStatus.RUNNING

        audit = db.query(AuditEvent).filter(
            AuditEvent.analysis_id == analysis_id,
            AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
        ).one()
        assert audit.payload["recovered_partitions"] == 1
