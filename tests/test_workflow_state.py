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
    completed_step_id = uuid4()
    completed_partition_id = uuid4()
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
            WorkflowStep(
                id=completed_step_id,
                analysis_id=analysis_id,
                step_id="validate_input",
                step_order=1,
                status=StepStatus.SUCCEEDED,
                attempt=2,
                last_heartbeat=stale_time,
                started_at=stale_time,
                completed_at=stale_time,
                input_artifacts=["input-artifact"],
                output_artifacts=["validated-artifact"],
                error_code=None,
                error_message=None,
                metadata_json={"next_step": "normalize", "preserved": True},
            )
        )
        db.add(
            AnalysisPartition(
                id=completed_partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="10:20",
                ordinal=1,
                record_start=10,
                record_end=20,
                variant_count=10,
                status="SUCCEEDED",
                input_artifact_id=None,
                metadata_json={"variant_ids": ["completed-variant"]},
                resource_class="LIGHT",
                cpu_request=0.5,
                memory_mb=512,
                attempt=3,
                lease_owner=None,
                lease_expires_at=None,
                started_at=stale_time,
                completed_at=stale_time,
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

        completed_step_before = db.get(WorkflowStep, completed_step_id)
        completed_partition_before = db.get(AnalysisPartition, completed_partition_id)
        assert completed_step_before.status == StepStatus.SUCCEEDED
        assert completed_step_before.attempt == 2
        assert completed_step_before.output_artifacts == ["validated-artifact"]
        assert completed_step_before.metadata_json["preserved"] is True
        assert completed_partition_before.status == "SUCCEEDED"
        assert completed_partition_before.attempt == 3
        assert completed_partition_before.metadata_json["variant_ids"] == ["completed-variant"]
        assert completed_partition_before.lease_owner is None
        assert completed_partition_before.lease_expires_at is None

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

        # Completed scientific work must remain immutable across worker recovery:
        # only RUNNING state is reconciled after a lost worker.
        completed_step_after = db.get(WorkflowStep, completed_step_id)
        completed_partition_after = db.get(AnalysisPartition, completed_partition_id)
        assert completed_step_after.status == StepStatus.SUCCEEDED
        assert completed_step_after.attempt == 2
        assert completed_step_after.output_artifacts == ["validated-artifact"]
        assert completed_step_after.metadata_json["preserved"] is True
        assert completed_partition_after.status == "SUCCEEDED"
        assert completed_partition_after.attempt == 3
        assert completed_partition_after.metadata_json["variant_ids"] == ["completed-variant"]
        assert completed_partition_after.lease_owner is None
        assert completed_partition_after.lease_expires_at is None

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


def test_celery_task_retries_transient_workflow_error_with_production_countdown(monkeypatch):
    from uuid import uuid4

    from backend.app.infrastructure.db import session as db_session
    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    analysis_id = str(uuid4())
    transient = variant_module.TransientWorkflowError(
        "temporary annotation provider outage",
        countdown=25,
    )
    calls = {}

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == uuid4_from_string(analysis_id)
        raise transient

    class RetryRequested(BaseException):
        pass

    def fake_retry(*, exc, countdown):
        calls["exc"] = exc
        calls["countdown"] = countdown
        raise RetryRequested()

    def uuid4_from_string(value):
        from uuid import UUID

        return UUID(value)

    class FakeClaimSession:
        def get(self, model, received_analysis_id, **kwargs):
            from backend.app.domain.enums import AnalysisStatus
            assert kwargs == {"with_for_update": True}
            return type("Analysis", (), {"id": received_analysis_id, "status": AnalysisStatus.QUEUED})()

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        lambda: FakeClaimSession(),
    )
    monkeypatch.setattr(variant_module, "run_variant_analysis", fake_run_variant_analysis)
    monkeypatch.setattr(celery_module.run_analysis_task, "retry", fake_retry)

    try:
        celery_module.run_analysis_task.run(analysis_id)
    except RetryRequested:
        pass
    else:
        raise AssertionError("Expected Celery retry to raise its retry control exception")
    assert calls["exc"] is transient
    assert calls["countdown"] == 25


def test_celery_redelivery_recovers_before_resuming_analysis(monkeypatch):
    from uuid import UUID, uuid4

    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    analysis_id = str(uuid4())
    events = []

    class FakeClaimSession:
        class Analysis:
            from backend.app.domain.enums import AnalysisStatus
            status = AnalysisStatus.QUEUED

        def get(self, model, received_analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return self.Analysis()

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            events.append("claim_session_closed")

    class FakeRecoverySession:
        def close(self):
            events.append("recovery_session_closed")

    class FakeAnalysisSession:
        class Analysis:
            status = "RUNNING"

        def get(self, model, received_analysis_id):
            events.append(("analysis_lookup", model.__name__, received_analysis_id))
            return self.Analysis()

        def close(self):
            events.append("analysis_session_closed")

    sessions = iter([FakeClaimSession(), FakeRecoverySession(), FakeAnalysisSession()])

    def fake_session_local():
        return next(sessions)

    def fake_recover(db, received_analysis_id):
        assert isinstance(db, FakeRecoverySession)
        assert received_analysis_id == UUID(analysis_id)
        events.append("recovery")

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == UUID(analysis_id)
        events.append("resume_analysis")

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(variant_module, "recover_interrupted_execution", fake_recover)
    monkeypatch.setattr(variant_module, "run_variant_analysis", fake_run_variant_analysis)

    task = celery_module.run_analysis_task
    task.push_request(delivery_info={"redelivered": True})
    try:
        result = task.run(analysis_id)
    finally:
        task.pop_request()

    assert result == {"analysis_id": analysis_id, "status": "RUNNING"}
    assert events.index("recovery") < events.index("resume_analysis")
    assert events.index("resume_analysis") < events.index(("analysis_lookup", "Analysis", UUID(analysis_id)))
    assert events.count("recovery") == 1
    assert events.count("resume_analysis") == 1

def test_celery_redelivery_with_real_durable_recovery_state(monkeypatch):
    from uuid import UUID, uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from backend.app.domain.enums import AnalysisStatus, StepStatus
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
    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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
    running_step_id = uuid4()
    completed_step_id = uuid4()
    running_partition_id = uuid4()
    completed_partition_id = uuid4()

    with Session(engine) as db:
        db.add(
            Organization(
                id=organization_id,
                name="Celery Durable Recovery Test Laboratory",
                external_identifier=None,
            )
        )
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject=None,
                email="celery-recovery@test.local",
                display_name="Celery Recovery Test",
                role="ANALYST",
                status="ACTIVE",
            )
        )
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="CELERY-RECOVERY-001",
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
                queue_task_id="redelivered-worker-task",
                reference_build="GRCh38",
                configuration={"input_artifact_id": str(uuid4())},
                started_at=None,
                completed_at=None,
                created_by=user_id,
            )
        )
        db.add(
            WorkflowStep(
                id=completed_step_id,
                analysis_id=analysis_id,
                step_id="validate_input",
                step_order=1,
                status=StepStatus.SUCCEEDED,
                attempt=2,
                input_artifacts=["input-artifact"],
                output_artifacts=["validated-artifact"],
                metadata_json={"next_step": "normalize", "preserved": True},
            )
        )
        db.add(
            WorkflowStep(
                id=running_step_id,
                analysis_id=analysis_id,
                step_id="annotate",
                step_order=3,
                status=StepStatus.RUNNING,
                attempt=1,
                input_artifacts=["normalized-artifact"],
                output_artifacts=[],
                metadata_json={"next_step": "annotate"},
            )
        )
        db.add(
            AnalysisPartition(
                id=completed_partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="10:20",
                ordinal=1,
                record_start=10,
                record_end=20,
                variant_count=10,
                status="SUCCEEDED",
                input_artifact_id=None,
                metadata_json={"variant_ids": ["completed-variant"]},
                resource_class="LIGHT",
                cpu_request=0.5,
                memory_mb=512,
                attempt=3,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        db.add(
            AnalysisPartition(
                id=running_partition_id,
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
                lease_expires_at=None,
            )
        )
        db.commit()

    sessions = iter([Session(engine), Session(engine), Session(engine)])

    def fake_session_local():
        return next(sessions)

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == analysis_id

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            running_step = db.get(WorkflowStep, running_step_id)
            completed_step = db.get(WorkflowStep, completed_step_id)
            running_partition = db.get(AnalysisPartition, running_partition_id)
            completed_partition = db.get(AnalysisPartition, completed_partition_id)

            # This assertion is deliberately inside the resumed worker call:
            # Celery redelivery must recover durable state before scientific
            # execution is allowed to continue.
            assert analysis.status == AnalysisStatus.RUNNING
            assert running_step.status == StepStatus.RETRYING
            assert running_step.error_code == "WORKER_INTERRUPTED"
            assert running_step.metadata_json["next_step"] == "annotate"
            assert running_partition.status == "READY"
            assert running_partition.lease_owner is None

            # Completed scientific work is not replayed or mutated.
            assert completed_step.status == StepStatus.SUCCEEDED
            assert completed_step.attempt == 2
            assert completed_step.output_artifacts == ["validated-artifact"]
            assert completed_step.metadata_json["preserved"] is True
            assert completed_partition.status == "SUCCEEDED"
            assert completed_partition.attempt == 3
            assert completed_partition.metadata_json["variant_ids"] == ["completed-variant"]
            assert completed_partition.lease_owner is None

            assert db.query(AuditEvent).filter(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
            ).count() == 1

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(
        variant_module,
        "run_variant_analysis",
        fake_run_variant_analysis,
    )

    task = celery_module.run_analysis_task
    task.push_request(delivery_info={"redelivered": True})
    try:
        result = task.run(str(analysis_id))
    finally:
        task.pop_request()

    assert result == {
        "analysis_id": str(analysis_id),
        "status": AnalysisStatus.RUNNING,
    }

    # The task's recovery session and final status session were both closed.
    # Re-open independently to verify the durable state after the task returns.
    with Session(engine) as db:
        assert db.get(WorkflowStep, running_step_id).status == StepStatus.RETRYING
        assert db.get(AnalysisPartition, running_partition_id).status == "READY"
        assert db.get(Analysis, analysis_id).status == AnalysisStatus.RUNNING


def test_celery_recovery_requeues_partition_for_scheduler_resume():
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.domain.enums import AnalysisStatus, StepStatus
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
    from backend.app.partition_scheduler import PartitionScheduler
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
    completed_partition_id = uuid4()

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name="Recovery Scheduler Test Laboratory",
            external_identifier=None,
        ))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=None,
            email="recovery-scheduler@test.local",
            display_name="Recovery Scheduler Test",
            role="ANALYST",
            status="ACTIVE",
        ))
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="RECOVERY-SCHEDULER-001",
            status="ACTIVE",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="siraloom.variant",
            workflow_version="1.0",
            status=AnalysisStatus.RUNNING,
            queue_task_id="scheduler-recovery-test",
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
        ))
        db.add(WorkflowStep(
            id=step_id,
            analysis_id=analysis_id,
            step_id="annotate",
            step_order=3,
            status=StepStatus.RUNNING,
            attempt=2,
            input_artifacts=["normalized-artifact"],
            output_artifacts=[],
            metadata_json={
                "next_step": "annotate",
                "batches": {
                    "0:10": {
                        "start": 0,
                        "end": 10,
                        "status": "RUNNING",
                        "attempt": 2,
                    }
                },
            },
        ))
        db.add(AnalysisPartition(
            id=completed_partition_id,
            analysis_id=analysis_id,
            step_id="annotate",
            partition_key="10:20",
            ordinal=1,
            record_start=10,
            record_end=20,
            variant_count=10,
            status="SUCCEEDED",
            input_artifact_id=None,
            metadata_json={"variant_ids": ["already-complete"]},
            resource_class="LIGHT",
            cpu_request=0.5,
            memory_mb=512,
            attempt=4,
            lease_owner=None,
            lease_expires_at=None,
        ))
        db.add(AnalysisPartition(
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
            metadata_json={"variant_ids": ["resumable"]},
            resource_class="LIGHT",
            cpu_request=0.5,
            memory_mb=512,
            attempt=2,
            lease_owner="workflow:lost-worker",
            lease_expires_at=None,
        ))
        db.commit()

        assert recover_interrupted_execution(db, analysis_id) is True

        step = db.get(WorkflowStep, step_id)
        partition = db.get(AnalysisPartition, partition_id)
        completed = db.get(AnalysisPartition, completed_partition_id)
        assert step.status == StepStatus.RETRYING
        assert step.metadata_json["batches"]["0:10"]["status"] == "RUNNING"
        assert partition.status == "READY"
        assert partition.lease_owner is None

        scheduler = PartitionScheduler(
            db,
            cpu_capacity=0.5,
            memory_mb=512,
            lease_seconds=300,
        )
        reclaimed = scheduler.claim_next(
            analysis_id,
            "annotate",
            f"workflow:{analysis_id}",
        )

        assert reclaimed is not None
        assert reclaimed.id == partition_id
        assert reclaimed.status == "RUNNING"
        assert reclaimed.attempt == 3
        assert reclaimed.lease_owner == f"workflow:{analysis_id}"

        # Recovery must not make already completed scientific work eligible
        # for execution again.
        assert completed.status == "SUCCEEDED"
        assert completed.attempt == 4
        assert completed.metadata_json["variant_ids"] == ["already-complete"]

        assert db.query(AuditEvent).filter(
            AuditEvent.analysis_id == analysis_id,
            AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
        ).count() == 1

def test_partition_scheduler_reports_capacity_exhaustion_without_claiming_work():
    from uuid import uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import Analysis, AnalysisPartition, Case, Organization, User
    from backend.app.partition_scheduler import PartitionScheduler

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[Organization.__table__, User.__table__, Case.__table__, Analysis.__table__, AnalysisPartition.__table__],
    )

    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Capacity Test Laboratory", external_identifier=None))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=None,
            email="capacity@test.local",
            display_name="Capacity Test",
            role="ANALYST",
            status="ACTIVE",
        ))
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="CAPACITY-001",
            status="ACTIVE",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="siraloom.variant",
            workflow_version="1.0",
            status=AnalysisStatus.RUNNING,
            queue_task_id="capacity-test",
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
        ))
        db.add(AnalysisPartition(
            id=uuid4(),
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
            resource_class="STANDARD",
            cpu_request=1.0,
            memory_mb=1024,
            attempt=0,
        ))
        db.add(AnalysisPartition(
            id=uuid4(),
            analysis_id=analysis_id,
            step_id="annotate",
            partition_key="1:2",
            ordinal=1,
            record_start=1,
            record_end=2,
            variant_count=1,
            status="READY",
            input_artifact_id=None,
            metadata_json={},
            resource_class="STANDARD",
            cpu_request=1.0,
            memory_mb=1024,
            attempt=0,
        ))
        db.commit()

        scheduler = PartitionScheduler(
            db,
            cpu_capacity=1.0,
            memory_mb=1024,
            lease_seconds=300,
        )
        worker_id = f"workflow:{analysis_id}"

        first = scheduler.claim_next(analysis_id, "annotate", worker_id)
        assert first is not None
        assert first.status == "RUNNING"

        second = scheduler.claim_next(analysis_id, "annotate", "workflow:other-worker")
        assert second is None

        remaining = db.query(AnalysisPartition).filter(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.partition_key == "1:2",
        ).one()
        assert remaining.status == "READY"
        assert remaining.lease_owner is None
        assert remaining.attempt == 0
        assert scheduler.capacity()["cpu_used"] == 1.0
        assert scheduler.capacity()["memory_mb_used"] == 1024


def test_worker_recovery_returns_false_when_analysis_is_missing():
    from uuid import uuid4

    from backend.app.workflows.variant import recover_interrupted_execution

    class MissingAnalysisSession:
        def __init__(self):
            self.get_calls = 0
            self.commit_calls = 0

        def get(self, model, analysis_id):
            self.get_calls += 1
            assert analysis_id == requested_id
            return None

        def commit(self):
            self.commit_calls += 1

    requested_id = uuid4()
    db = MissingAnalysisSession()

    assert recover_interrupted_execution(db, requested_id) is False
    assert db.get_calls == 1
    assert db.commit_calls == 0


def test_celery_redelivery_then_exhausted_transient_persists_terminal_state(monkeypatch):
    from uuid import uuid4

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from backend.app.domain.enums import AnalysisStatus, StepStatus
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
    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name="Redelivery Exhaustion Test Laboratory",
            external_identifier=None,
        ))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=None,
            email="redelivery-exhaustion@test.local",
            display_name="Redelivery Exhaustion Test",
            role="ANALYST",
            status="ACTIVE",
        ))
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="REDELIVERY-EXHAUSTION-001",
            status="ACTIVE",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="siraloom.variant",
            workflow_version="1.0",
            status=AnalysisStatus.RUNNING,
            queue_task_id="redelivery-exhaustion-test",
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
        ))
        db.add(WorkflowStep(
            id=step_id,
            analysis_id=analysis_id,
            step_id="annotate",
            step_order=3,
            status=StepStatus.RUNNING,
            attempt=2,
            input_artifacts=["normalized-artifact"],
            output_artifacts=[],
            metadata_json={"next_step": "annotate"},
        ))
        db.add(AnalysisPartition(
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
            attempt=2,
            lease_owner="workflow:lost-worker",
            lease_expires_at=None,
        ))
        db.commit()

    sessions = iter([Session(engine), Session(engine), Session(engine)])

    def fake_session_local():
        return next(sessions)

    transient = variant_module.TransientWorkflowError(
        "provider remained unavailable after recovery",
        countdown=60,
    )

    def fail_after_recovery(received_analysis_id):
        assert received_analysis_id == analysis_id
        with Session(engine) as db:
            assert db.get(WorkflowStep, step_id).status == StepStatus.RETRYING
            assert db.get(AnalysisPartition, partition_id).status == "READY"
        raise transient

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(
        variant_module,
        "run_variant_analysis",
        fail_after_recovery,
    )

    task = celery_module.run_analysis_task
    task.push_request(
        retries=task.max_retries,
        delivery_info={"redelivered": True},
    )
    try:
        try:
            task.run(str(analysis_id))
        except variant_module.TransientWorkflowError as exc:
            assert exc is transient
        else:
            raise AssertionError("Expected exhausted transient error to propagate")
    finally:
        task.pop_request()

    with Session(engine) as db:
        analysis = db.get(Analysis, analysis_id)
        step = db.get(WorkflowStep, step_id)
        partition = db.get(AnalysisPartition, partition_id)
        recovery_audit = db.scalars(select(AuditEvent).where(
            AuditEvent.analysis_id == analysis_id,
            AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
        )).all()
        exhaustion_audit = db.scalars(select(AuditEvent).where(
            AuditEvent.analysis_id == analysis_id,
            AuditEvent.event_type == "ANNOTATION_RETRY_EXHAUSTED",
        )).all()

        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.completed_at is not None
        assert step.status == StepStatus.FAILED
        assert step.error_code == "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
        assert step.metadata_json["retry_exhausted"] is True
        assert partition.status == "FAILED"
        assert partition.lease_owner is None
        assert partition.error_code == "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
        assert len(recovery_audit) == 1
        assert len(exhaustion_audit) == 1

def test_celery_first_delivery_skips_interrupted_worker_recovery(monkeypatch):
    from uuid import UUID, uuid4

    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    analysis_id = str(uuid4())
    events = []

    from backend.app.domain.enums import AnalysisStatus

    class FakeAnalysis:
        def __init__(self):
            self.status = AnalysisStatus.QUEUED

    fake_analysis = FakeAnalysis()

    class FakeSession:
        def get(self, model, received_analysis_id, **kwargs):
            if kwargs:
                assert kwargs == {"with_for_update": True}
                events.append("claim_lookup")
                return fake_analysis
            events.append(("analysis_lookup", model.__name__, received_analysis_id))
            return fake_analysis

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            events.append("analysis_session_closed")

    def fake_session_local():
        return FakeSession()

    def fake_recover(*_args):
        events.append("recovery")

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == UUID(analysis_id)
        events.append("run_analysis")

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(variant_module, "recover_interrupted_execution", fake_recover)
    monkeypatch.setattr(variant_module, "run_variant_analysis", fake_run_variant_analysis)

    task = celery_module.run_analysis_task
    task.push_request(delivery_info={})
    try:
        result = task.run(analysis_id)
    finally:
        task.pop_request()

    assert result == {"analysis_id": analysis_id, "status": "RUNNING"}
    assert fake_analysis.status == AnalysisStatus.RUNNING
    assert "recovery" not in events
    assert events.count("run_analysis") == 1
    assert events.index("run_analysis") < events.index(("analysis_lookup", "Analysis", UUID(analysis_id)))


def test_celery_redelivery_closes_recovery_session_when_recovery_fails(monkeypatch):
    from uuid import UUID, uuid4

    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    analysis_id = str(uuid4())
    events = []

    class RecoveryFailure(RuntimeError):
        pass

    from backend.app.domain.enums import AnalysisStatus

    class FakeClaimSession:
        class Analysis:
            status = AnalysisStatus.QUEUED

        def get(self, model, received_analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return self.Analysis()

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            events.append("claim_session_closed")

    class FakeRecoverySession:
        def close(self):
            events.append("recovery_session_closed")

    sessions = iter([FakeClaimSession(), FakeRecoverySession()])

    def fake_session_local():
        return next(sessions)

    def fake_recover(db, received_analysis_id):
        assert isinstance(db, FakeRecoverySession)
        assert received_analysis_id == UUID(analysis_id)
        events.append("recovery")
        raise RecoveryFailure("durable recovery failed")

    def fail_if_analysis_resumes(_analysis_id):
        raise AssertionError("analysis must not resume after recovery failure")

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(variant_module, "recover_interrupted_execution", fake_recover)
    monkeypatch.setattr(variant_module, "run_variant_analysis", fail_if_analysis_resumes)

    task = celery_module.run_analysis_task
    task.push_request(delivery_info={"redelivered": True})
    try:
        try:
            task.run(analysis_id)
        except RecoveryFailure:
            pass
        else:
            raise AssertionError("Expected durable recovery failure to propagate")
    finally:
        task.pop_request()

    assert events == [
        "claim_session_closed",
        "recovery",
        "recovery_session_closed",
    ]


def test_celery_retry_exhaustion_persists_terminal_failure():
    from uuid import uuid4

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from backend.app.domain.enums import AnalysisStatus, StepStatus
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
    from backend.app.infrastructure.queue import celery_app as celery_module

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

    with Session(engine) as db:
        db.add(
            Organization(
                id=organization_id,
                name="Retry Exhaustion Test Laboratory",
                external_identifier=None,
            )
        )
        db.add(
            User(
                id=user_id,
                organization_id=organization_id,
                external_subject="retry-exhaustion-user",
                email="retry-exhaustion@example.test",
                display_name="Retry Exhaustion User",
                role="ANALYST",
                status="ACTIVE",
            )
        )
        db.add(
            Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier="retry-exhaustion-case",
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
                analysis_type="VARIANT",
                workflow_id="variant-analysis",
                workflow_version="v1",
                status=AnalysisStatus.RUNNING,
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
            )
        )
        db.add(
            WorkflowStep(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id="annotate",
                step_order=3,
                status=StepStatus.RETRYING,
                attempt=3,
                metadata_json={"next_step": "annotate"},
            )
        )
        db.add(
            AnalysisPartition(
                id=uuid4(),
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
                resource_class="STANDARD",
                cpu_request=1.0,
                memory_mb=1024,
                attempt=3,
                lease_owner=None,
                lease_expires_at=None,
                error_code=None,
                error_message=None,
                started_at=None,
                completed_at=None,
            )
        )
        db.commit()

        assert celery_module._finalize_transient_retry_exhaustion(
            db,
            analysis_id,
            "provider remained unavailable after bounded retries",
        ) is True

        analysis = db.get(Analysis, analysis_id)
        step = db.scalar(
            select(WorkflowStep).where(WorkflowStep.analysis_id == analysis_id)
        )
        partition = db.scalar(
            select(AnalysisPartition).where(AnalysisPartition.analysis_id == analysis_id)
        )
        audit = db.scalars(
            select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ANNOTATION_RETRY_EXHAUSTED",
            )
        ).all()

        assert analysis.status == AnalysisStatus.FAILED
        assert analysis.completed_at is not None
        assert step.status == StepStatus.FAILED
        assert step.error_code == "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
        assert step.metadata_json["retry_exhausted"] is True
        assert partition.status == "FAILED"
        assert partition.error_code == "ANNOTATION_PROVIDER_RETRY_EXHAUSTED"
        assert audit


def test_celery_retry_exhaustion_finalizes_before_propagating_transient(monkeypatch):
    from uuid import UUID, uuid4

    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    analysis_id = str(uuid4())
    transient = variant_module.TransientWorkflowError(
        "provider remained unavailable",
        countdown=60,
    )
    events = []

    from backend.app.domain.enums import AnalysisStatus

    class FakeClaimSession:
        class Analysis:
            status = AnalysisStatus.QUEUED

        def get(self, model, received_analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return self.Analysis()

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            events.append("claim_session_closed")

    class FakeTerminalSession:
        def close(self):
            events.append("terminal_session_closed")

    sessions = iter([FakeClaimSession(), FakeTerminalSession()])

    def fake_session_local():
        return next(sessions)

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == UUID(analysis_id)
        events.append("run_analysis")
        raise transient

    def fake_finalize(db, received_analysis_id, error_message):
        assert isinstance(db, FakeTerminalSession)
        assert received_analysis_id == UUID(analysis_id)
        assert error_message == str(transient)
        events.append("finalize")

    def fail_if_retry_called(*_args, **_kwargs):
        raise AssertionError("Celery retry must not be scheduled after max_retries")

    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        fake_session_local,
    )
    monkeypatch.setattr(
        celery_module,
        "_finalize_transient_retry_exhaustion",
        fake_finalize,
    )
    monkeypatch.setattr(
        variant_module,
        "run_variant_analysis",
        fake_run_variant_analysis,
    )
    monkeypatch.setattr(
        celery_module.run_analysis_task,
        "retry",
        fail_if_retry_called,
    )

    task = celery_module.run_analysis_task
    task.push_request(
        retries=task.max_retries,
        delivery_info={},
    )
    try:
        try:
            task.run(analysis_id)
        except variant_module.TransientWorkflowError as exc:
            assert exc is transient
        else:
            raise AssertionError("Expected exhausted transient error to propagate")
    finally:
        task.pop_request()

    assert events == [
        "claim_session_closed",
        "run_analysis",
        "finalize",
        "terminal_session_closed",
    ]

def test_celery_successful_retry_resumes_durable_annotation_state(monkeypatch):
    from uuid import UUID, uuid4

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from backend.app.domain.enums import AnalysisStatus, StepStatus
    from backend.app.infrastructure.db import session as db_session
    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import (
        Analysis,
        AnalysisPartition,
        Case,
        Organization,
        User,
        WorkflowStep,
    )
    from backend.app.infrastructure.queue import celery_app as celery_module
    from backend.app.workflows import variant as variant_module

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_session, "SessionLocal", lambda: Session(engine))
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
        db.add(Organization(
            id=organization_id,
            name="Successful Retry Test Laboratory",
            external_identifier=None,
        ))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=None,
            email="successful-retry@test.local",
            display_name="Successful Retry Test",
            role="ANALYST",
            status="ACTIVE",
        ))
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier="SUCCESSFUL-RETRY-001",
            status="ACTIVE",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="siraloom.variant",
            workflow_version="1.0",
            status=AnalysisStatus.QUEUED,
            queue_task_id="successful-retry-test",
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
        ))
        db.add(WorkflowStep(
            id=step_id,
            analysis_id=analysis_id,
            step_id="annotate",
            step_order=3,
            status=StepStatus.RUNNING,
            attempt=1,
            input_artifacts=["normalized-artifact"],
            output_artifacts=[],
            metadata_json={
                "batches": {
                    "0:1": {
                        "start": 0,
                        "end": 1,
                        "status": "RUNNING",
                        "attempt": 1,
                    }
                }
            },
        ))
        db.add(AnalysisPartition(
            id=partition_id,
            analysis_id=analysis_id,
            step_id="annotate",
            partition_key="0:1",
            ordinal=0,
            record_start=0,
            record_end=1,
            variant_count=1,
            status="RUNNING",
            input_artifact_id=None,
            metadata_json={"variant_ids": [str(uuid4())]},
            resource_class="LIGHT",
            cpu_request=0.5,
            memory_mb=512,
            attempt=1,
            lease_owner="workflow:successful-retry",
            lease_expires_at=None,
        ))
        db.commit()

    transient = variant_module.TransientWorkflowError(
        "temporary provider outage",
        countdown=5,
    )
    retry_requested = []

    def fake_run_variant_analysis(received_analysis_id):
        assert received_analysis_id == analysis_id
        with Session(engine) as db:
            step = db.get(WorkflowStep, step_id)
            partition = db.get(AnalysisPartition, partition_id)
            if step.metadata_json["batches"]["0:1"]["status"] == "RUNNING":
                step.status = StepStatus.RETRYING
                step.error_code = "ANNOTATION_PROVIDER_TRANSIENT"
                step.error_message = str(transient)
                metadata = dict(step.metadata_json or {})
                batches = dict(metadata.get("batches") or {})
                batch = dict(batches.get("0:1") or {})
                batch["status"] = "RETRYING"
                batches["0:1"] = batch
                metadata["batches"] = batches
                step.metadata_json = metadata
                partition.status = "READY"
                partition.lease_owner = None
                partition.lease_expires_at = None
                db.commit()
                raise transient

            assert step.status == StepStatus.RETRYING
            assert step.metadata_json["batches"]["0:1"]["status"] == "RETRYING"
            assert partition.status == "READY"

            partition.status = "SUCCEEDED"
            partition.attempt = 2
            step.status = StepStatus.SUCCEEDED
            step.output_artifacts = ["annotation-artifact"]
            metadata = dict(step.metadata_json or {})
            batches = dict(metadata.get("batches") or {})
            batch = dict(batches.get("0:1") or {})
            batch["status"] = "SUCCEEDED"
            batches["0:1"] = batch
            metadata["batches"] = batches
            step.metadata_json = metadata
            analysis = db.get(Analysis, analysis_id)
            analysis.status = AnalysisStatus.SUCCEEDED
            db.commit()

    class RetryRequested(BaseException):
        pass

    def fake_retry(*, exc, countdown):
        retry_requested.append((exc, countdown))
        raise RetryRequested()

    monkeypatch.setattr(variant_module, "run_variant_analysis", fake_run_variant_analysis)
    monkeypatch.setattr(celery_module.run_analysis_task, "retry", fake_retry)

    task = celery_module.run_analysis_task

    task.push_request(retries=0, delivery_info={})
    try:
        try:
            task.run(str(analysis_id))
        except RetryRequested:
            pass
        else:
            raise AssertionError("Expected the first transient attempt to schedule a retry")
    finally:
        task.pop_request()

    assert retry_requested == [(transient, 5)]

    with Session(engine) as db:
        assert db.get(WorkflowStep, step_id).status == StepStatus.RETRYING
        assert db.get(AnalysisPartition, partition_id).status == "READY"

    task.push_request(retries=1, delivery_info={})
    try:
        result = task.run(str(analysis_id))
    finally:
        task.pop_request()

    assert result == {
        "analysis_id": str(analysis_id),
        "status": AnalysisStatus.SUCCEEDED,
    }

    with Session(engine) as db:
        step = db.get(WorkflowStep, step_id)
        partition = db.get(AnalysisPartition, partition_id)
        analysis = db.get(Analysis, analysis_id)
        assert step.status == StepStatus.SUCCEEDED
        assert step.output_artifacts == ["annotation-artifact"]
        assert step.metadata_json["batches"]["0:1"]["status"] == "SUCCEEDED"
        assert partition.status == "SUCCEEDED"
        assert partition.attempt == 2
        assert partition.lease_owner is None
        assert analysis.status == AnalysisStatus.SUCCEEDED

def test_workflow_next_step_prefers_active_execution_over_older_failure():
    from backend.app.api.v1.analyses import _resolve_workflow_next_step

    steps = [
        {"step_id": "validate_input", "status": "SUCCEEDED", "next_step": "normalize"},
        {"step_id": "normalize", "status": "FAILED", "next_step": "VALID_VCF_REQUIRED"},
        {"step_id": "annotate", "status": "RUNNING", "next_step": "annotate"},
    ]

    assert _resolve_workflow_next_step(steps) == "annotate"


def test_workflow_next_step_preserves_explicit_blocker_when_no_active_step():
    from backend.app.api.v1.analyses import _resolve_workflow_next_step

    steps = [
        {"step_id": "validate_input", "status": "SUCCEEDED", "next_step": "normalize"},
        {"step_id": "normalize", "status": "BLOCKED", "next_step": "REFERENCE_REQUIRED"},
        {"step_id": "annotate", "status": "PENDING", "next_step": "annotate"},
    ]

    assert _resolve_workflow_next_step(steps) == "REFERENCE_REQUIRED"


def test_workflow_next_step_reports_completion_only_when_every_step_succeeded():
    from backend.app.api.v1.analyses import _resolve_workflow_next_step

    steps = [
        {"step_id": "validate_input", "status": "SUCCEEDED", "next_step": "normalize"},
        {"step_id": "normalize", "status": "SUCCEEDED", "next_step": "annotate"},
    ]

    assert _resolve_workflow_next_step(steps) == "ANALYSIS_COMPLETE"
