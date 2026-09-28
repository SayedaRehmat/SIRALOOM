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


def test_transient_provider_error_preserves_bounded_retry_contract():
    from backend.app.workflows.variant import TransientWorkflowError

    assert TransientWorkflowError("temporary provider outage", countdown=0).countdown == 1
    assert TransientWorkflowError("temporary provider outage", countdown=5).countdown == 5
    assert TransientWorkflowError("temporary provider outage", countdown=10_000).countdown == 10_000


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

        # A second redelivery/recovery pass must be a no-op: recovery is
        # idempotent once durable execution state has already been reconciled.
        recovered_again = recover_interrupted_execution(db, analysis_id)
        assert recovered_again is False
        assert db.query(AuditEvent).filter(
            AuditEvent.analysis_id == analysis_id,
            AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
        ).count() == 1

def test_transient_genebe_failure_requeues_annotation_partition_and_checkpoints(monkeypatch):
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.adapters.annotation.genebe import GeneBeError, GeneBeProvider
    from backend.app.config import settings
    from backend.app.domain.schemas import CanonicalVariant
    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import (
        Analysis,
        AnalysisPartition,
        Case,
        Organization,
        User,
        WorkflowStep,
    )
    from backend.app.partition_scheduler import PartitionScheduler
    from backend.app.workflows.variant import (
        TransientWorkflowError,
        _save_batch_checkpoint,
        mark_step,
    )

    class FakeResponse:
        status_code = 503
        text = "temporary GeneBe outage"
        headers = {}

        def raise_for_status(self):
            import httpx

            request = httpx.Request("POST", "https://example.test/variants")
            response = httpx.Response(
                503,
                request=request,
                text=self.text,
                headers=self.headers,
            )
            raise httpx.HTTPStatusError(
                "503 Service Unavailable",
                request=request,
                response=response,
            )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(
        "backend.app.adapters.annotation.genebe.httpx.Client",
        lambda **kwargs: FakeClient(),
    )
    monkeypatch.setattr(settings, "genebe_enabled", True)
    monkeypatch.setattr(settings, "genebe_email", "test@example.local")
    monkeypatch.setattr(settings, "genebe_api_key", "test-key")
    monkeypatch.setattr(settings, "genebe_retry_attempts", 1)

    variant = CanonicalVariant(
        genome_build="GRCh38",
        chromosome="1",
        position=100,
        reference="A",
        alternate="G",
    )

    provider = GeneBeProvider()
    try:
        provider.annotate([variant], {"genome": "hg38"})
    except GeneBeError as exc:
        assert exc.retryable is True
        provider_error = exc
    else:
        raise AssertionError("Expected the injected GeneBe 503 failure")

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
        ],
    )

    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    step_id = uuid4()
    partition_id = uuid4()

    with Session(engine) as db:
        db.add(
            Organization(
                id=organization_id,
                name="Transient Provider Test Laboratory",
                external_identifier=None,
            )
        )
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject=None,
                email="transient@test.local",
                display_name="Transient Test",
                role="ANALYST",
                status="ACTIVE",
            )
        )
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="TRANSIENT-001",
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
                queue_task_id="transient-provider-test",
                reference_build="GRCh38",
                configuration={},
                started_at=None,
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
                input_artifacts=[],
                output_artifacts=[],
                metadata_json={},
            )
        )
        db.add(
            AnalysisPartition(
                id=partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="0:1",
                ordinal=0,
                record_start=0,
                record_end=1,
                variant_count=1,
                status="READY",
                input_artifact_id=None,
                metadata_json={},
                resource_class="LIGHT",
                cpu_request=0.5,
                memory_mb=512,
                attempt=0,
            )
        )
        db.commit()

        scheduler = PartitionScheduler(
            db,
            cpu_capacity=1.0,
            memory_mb=512,
            lease_seconds=300,
        )
        worker_id = f"workflow:{analysis_id}"
        claimed = scheduler.claim_next(analysis_id, "annotate", worker_id)
        assert claimed is not None
        assert claimed.status == "RUNNING"

        attempt = 1
        _save_batch_checkpoint(
            db,
            db.get(WorkflowStep, step_id),
            0,
            1,
            status="RETRYING",
            attempt=attempt,
            metadata={"error": str(provider_error)},
        )
        mark_step(
            db,
            db.get(WorkflowStep, step_id),
            StepStatus.RETRYING,
            error_code="ANNOTATION_PROVIDER_TRANSIENT",
            error_message=str(provider_error),
        )

        failed = scheduler.fail(
            partition_id,
            worker_id,
            error_code="ANNOTATION_PROVIDER_TRANSIENT",
            error_message=str(provider_error),
        )
        assert failed.status == "READY"
        assert failed.lease_owner is None
        assert failed.lease_expires_at is None

        step = db.get(WorkflowStep, step_id)
        assert step.status == StepStatus.RETRYING
        assert step.error_code == "ANNOTATION_PROVIDER_TRANSIENT"
        assert step.metadata_json["batches"]["0:1"]["status"] == "RETRYING"
        assert step.metadata_json["batches"]["0:1"]["attempt"] == 1
        assert step.metadata_json["batches"]["0:1"]["error"] == str(provider_error)

        # The durable checkpoint remains the source of truth for the redelivery:
        # the next execution must claim the same READY partition rather than
        # starting a new partition or losing the failed batch.
        reclaimed = scheduler.claim_next(analysis_id, "annotate", worker_id)
        assert reclaimed is not None
        assert reclaimed.id == partition_id
        assert reclaimed.status == "RUNNING"
        assert reclaimed.attempt == 2

        retry_error = TransientWorkflowError(
            str(provider_error),
            countdown=min(60, 5 * attempt),
        )
        assert retry_error.countdown == 5
