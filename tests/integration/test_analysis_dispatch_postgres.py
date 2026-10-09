import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.application.analysis import enqueue_analysis, resume_analysis
from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch, AnalysisPartition, Case, Organization, ResourceDeploymentProfile, User
from backend.app.partition_scheduler import PartitionLeaseError, PartitionScheduler, configure_partition


def _set_trial_deployment_profile(engine, organization_id):
    """Keep dispatch-mechanics tests in an explicitly configured trial profile."""
    with Session(engine) as db:
        db.add(ResourceDeploymentProfile(
            id=uuid4(),
            organization_id=organization_id,
            profile_type="TRIAL_PUBLIC",
            profile_version="test-v1",
            status="ACTIVE",
        ))
        db.commit()


@pytest.mark.integration
def test_postgres_concurrent_analysis_start_creates_one_dispatch_generation(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()

    # Persist the dependency graph in separate transactions. This keeps the
    # concurrency test focused on Analysis row locking rather than relying on
    # SQLAlchemy's unit-of-work ordering for unrelated model instances.
    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"integration-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.commit()

    _set_trial_deployment_profile(engine, organization_id)

    with Session(engine) as db:
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Integration Test",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.commit()

    with Session(engine) as db:
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.commit()

    with Session(engine) as db:
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="GERMLINE",
            workflow_id="integration",
            workflow_version="1",
            status=AnalysisStatus.CREATED,
            queue_task_id=None,
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
            analysis_version=1,
        ))
        db.commit()

    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
        lambda _dispatch_id: None,
    )

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def start_one():
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                results.append(enqueue_analysis(db, db.get(Analysis, analysis_id)))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=start_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert not errors
        assert len(results) == 2
        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            assert analysis is not None
            assert analysis.status == AnalysisStatus.QUEUED
            dispatches = db.scalars(
                select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis_id)
            ).all()
            assert len(dispatches) == 1
            assert analysis.queue_task_id == str(dispatches[0].id)
    finally:
        with Session(engine) as db:
            db.query(AnalysisDispatch).filter(
                AnalysisDispatch.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_concurrent_dispatch_relays_publish_once(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    dispatch_id = uuid4()

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"relay-integration-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.commit()

    with Session(engine) as db:
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Relay Integration Test",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.commit()

    with Session(engine) as db:
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.commit()

    with Session(engine) as db:
        db.add(Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="GERMLINE",
            workflow_id="integration",
            workflow_version="1",
            status=AnalysisStatus.QUEUED,
            queue_task_id=str(dispatch_id),
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
            analysis_version=1,
        ))
        db.add(AnalysisDispatch(
            id=dispatch_id,
            analysis_id=analysis_id,
            dispatch_generation=1,
            status="PENDING",
            task_id=None,
            attempts=0,
            last_error=None,
            published_at=None,
        ))
        db.commit()

    import importlib
    from types import SimpleNamespace

    celery_module = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    publish_calls = {"count": 0}
    publish_lock = threading.Lock()

    def fake_apply_async(*, args, task_id):
        with publish_lock:
            publish_calls["count"] += 1
        import time
        time.sleep(0.2)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(
        celery_module,
        "run_analysis_task",
        SimpleNamespace(apply_async=fake_apply_async),
    )
    monkeypatch.setattr(
        celery_module.celery_app,
        "AsyncResult",
        lambda _task_id: SimpleNamespace(state="PENDING"),
    )

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def relay_one():
        try:
            barrier.wait(timeout=10)
            results.append(celery_module.publish_analysis_dispatch(dispatch_id))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=relay_one) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert not errors
        assert results == [str(dispatch_id), str(dispatch_id)]
        assert publish_calls["count"] == 1
        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            dispatch = db.get(AnalysisDispatch, dispatch_id)
            assert analysis is not None
            assert dispatch is not None
            assert analysis.status == AnalysisStatus.QUEUED
            assert analysis.queue_task_id == str(dispatch_id)
            assert dispatch.status == "PUBLISHED"
            assert dispatch.task_id == str(dispatch_id)
            assert dispatch.attempts == 1
    finally:
        with Session(engine) as db:
            db.query(AnalysisDispatch).filter(
                AnalysisDispatch.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_retry_supersedes_old_dispatch_before_legacy_relay_runs(monkeypatch):
    """A retry generation must remain the sole queue owner when an old relay runs afterward."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    old_dispatch_id = uuid4()

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"retry-race-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        _set_trial_deployment_profile(engine, organization_id)

        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Retry Race Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.FAILED,
                queue_task_id=str(old_dispatch_id),
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.add(AnalysisDispatch(
                id=old_dispatch_id,
                analysis_id=analysis_id,
                dispatch_generation=1,
                status="PUBLISHED",
                task_id=str(old_dispatch_id),
                attempts=1,
                last_error=None,
                published_at=None,
            ))
            db.commit()

        import importlib
        from types import SimpleNamespace

        celery_module = importlib.import_module(
            "backend.app.infrastructure.queue.celery_app"
        )
        monkeypatch.setattr(
            celery_module.celery_app,
            "AsyncResult",
            lambda _task_id: SimpleNamespace(state="PENDING"),
        )
        monkeypatch.setattr(
            celery_module,
            "run_analysis_task",
            SimpleNamespace(
                apply_async=lambda *, args, task_id: SimpleNamespace(id=task_id)
            ),
        )

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            enqueue_analysis(db, analysis)

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            dispatches = db.scalars(
                select(AnalysisDispatch)
                .where(AnalysisDispatch.analysis_id == analysis_id)
                .order_by(AnalysisDispatch.dispatch_generation)
            ).all()
            assert analysis.status == AnalysisStatus.QUEUED
            assert len(dispatches) == 2
            assert analysis.queue_task_id == str(dispatches[1].id)

        # The old relay now runs after the retry generation has taken ownership.
        celery_module.publish_analysis_dispatch(old_dispatch_id)

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            dispatches = db.scalars(
                select(AnalysisDispatch)
                .where(AnalysisDispatch.analysis_id == analysis_id)
                .order_by(AnalysisDispatch.dispatch_generation)
            ).all()

            assert analysis is not None
            assert analysis.status == AnalysisStatus.QUEUED
            assert len(dispatches) == 2
            old_dispatch, new_dispatch = dispatches
            assert old_dispatch.status == "SUPERSEDED"
            assert new_dispatch.dispatch_generation == 2
            assert new_dispatch.status == "PUBLISHED"
            assert analysis.queue_task_id == str(new_dispatch.id)
    finally:
        with Session(engine) as db:
            db.query(AnalysisDispatch).filter(
                AnalysisDispatch.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_stale_worker_generation_cannot_claim_after_retry(monkeypatch):
    """An old Celery task must be fenced after a newer retry generation owns the analysis."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    old_dispatch_id = uuid4()
    new_dispatch_id = uuid4()

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"stale-worker-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Stale Worker Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.QUEUED,
                queue_task_id=str(new_dispatch_id),
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=2,
            ))
            db.add(AnalysisDispatch(
                id=old_dispatch_id,
                analysis_id=analysis_id,
                dispatch_generation=1,
                status="SUPERSEDED",
                task_id=str(old_dispatch_id),
                attempts=1,
            ))
            db.add(AnalysisDispatch(
                id=new_dispatch_id,
                analysis_id=analysis_id,
                dispatch_generation=2,
                status="PENDING",
                task_id=None,
                attempts=0,
            ))
            db.commit()

        import importlib
        celery_module = importlib.import_module(
            "backend.app.infrastructure.queue.celery_app"
        )

        with Session(engine) as db:
            claimed = celery_module._claim_analysis_execution(
                db,
                analysis_id,
                task_id=str(old_dispatch_id),
            )
            assert claimed is False

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            assert analysis.status == AnalysisStatus.QUEUED
            assert analysis.queue_task_id == str(new_dispatch_id)

            claimed = celery_module._claim_analysis_execution(
                db,
                analysis_id,
                task_id=str(new_dispatch_id),
            )
            assert claimed is True

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.queue_task_id == str(new_dispatch_id)
    finally:
        with Session(engine) as db:
            db.query(AnalysisDispatch).filter(
                AnalysisDispatch.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()



@pytest.mark.integration
def test_postgres_concurrent_worker_recovery_is_serialized(monkeypatch):
    """Concurrent redeliveries recover one RUNNING execution exactly once."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    step_id = uuid4()
    partition_id = uuid4()

    try:
        from backend.app.infrastructure.db.models import AnalysisPartition, AuditEvent, WorkflowStep
        from backend.app.workflows import variant as variant_module

        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"worker-recovery-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Worker Recovery Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.RUNNING,
                queue_task_id=str(uuid4()),
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.add(WorkflowStep(
                id=step_id,
                analysis_id=analysis_id,
                step_id="validate_input",
                step_order=1,
                status="RUNNING",
                attempt=1,
                metadata_json={"worker": "lost"},
            ))
            db.add(AnalysisPartition(
                id=partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="partition-1",
                ordinal=0,
                record_start=1,
                record_end=10,
                variant_count=10,
                status="RUNNING",
                metadata_json={},
                resource_class="STANDARD",
                cpu_request=1.0,
                memory_mb=1024,
                attempt=1,
                lease_owner="lost-worker",
                lease_expires_at=None,
            ))
            db.commit()

        audit_calls = {"count": 0}
        audit_lock = threading.Lock()
        original_record = variant_module.AuditService.record

        def counted_record(self, **kwargs):
            if kwargs.get("event_type") == "WORKFLOW_WORKER_RECOVERY":
                with audit_lock:
                    audit_calls["count"] += 1
            return original_record(self, **kwargs)

        monkeypatch.setattr(variant_module.AuditService, "record", counted_record)

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def recover_one():
            try:
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    results.append(
                        variant_module.recover_interrupted_execution(db, analysis_id)
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=recover_one) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert sorted(results) == [False, True]
        assert audit_calls["count"] == 1

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            step = db.get(WorkflowStep, step_id)
            partition = db.get(AnalysisPartition, partition_id)
            assert analysis.status == AnalysisStatus.RUNNING
            assert step.status == "RETRYING"
            assert step.error_code == "WORKER_INTERRUPTED"
            assert partition.status == "READY"
            assert partition.lease_owner is None
            assert partition.lease_expires_at is None
            assert partition.error_code == "WORKER_INTERRUPTED"
    finally:
        with Session(engine) as db:
            db.query(AnalysisPartition).filter(
                AnalysisPartition.analysis_id == analysis_id
            ).delete()
            db.query(WorkflowStep).filter(
                WorkflowStep.analysis_id == analysis_id
            ).delete()
            db.query(AuditEvent).filter(
                AuditEvent.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_concurrent_human_gate_resume_creates_one_dispatch(monkeypatch):
    """Concurrent human-gate callbacks must create one durable resume intent."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"human-gate-resume-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Human Gate Resume Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.REQUIRES_REVIEW,
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        monkeypatch.setattr(
            "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
            lambda _dispatch_id: None,
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def resume_one():
            try:
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    results.append(resume_analysis(db, analysis_id))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=resume_one) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert len(results) == 2

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            dispatches = db.scalars(
                select(AnalysisDispatch)
                .where(AnalysisDispatch.analysis_id == analysis_id)
                .order_by(AnalysisDispatch.dispatch_generation)
            ).all()
            assert analysis is not None
            assert analysis.status == AnalysisStatus.QUEUED
            assert len(dispatches) == 1
            assert dispatches[0].dispatch_generation == 1
            assert dispatches[0].status == "PENDING"
            assert analysis.queue_task_id == str(dispatches[0].id)
    finally:
        with Session(engine) as db:
            db.query(AnalysisDispatch).filter(
                AnalysisDispatch.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(ResourceDeploymentProfile.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_partition_capacity_claims_are_serialized():
    """Concurrent partition claims cannot commit leases beyond the global capacity."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_ids = [uuid4(), uuid4()]
    analysis_ids = [uuid4(), uuid4()]

    try:
        from backend.app.infrastructure.db.models import AnalysisPartition
        from backend.app.partition_scheduler import PartitionScheduler, configure_partition

        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"partition-capacity-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Partition Capacity Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

            for case_id, analysis_id in zip(case_ids, analysis_ids):
                db.add(Case(
                    id=case_id,
                    organization_id=organization_id,
                    case_identifier=str(case_id),
                    status="OPEN",
                    clinical_context={},
                    language="en",
                    created_by=user_id,
                ))
                db.commit()
                db.add(Analysis(
                    id=analysis_id,
                    case_id=case_id,
                    parent_analysis_id=None,
                    assay_id=None,
                    analysis_type="GERMLINE",
                    workflow_id="integration",
                    workflow_version="1",
                    status=AnalysisStatus.RUNNING,
                    queue_task_id=None,
                    reference_build="GRCh38",
                    configuration={},
                    started_at=None,
                    completed_at=None,
                    created_by=user_id,
                    analysis_version=1,
                ))
                db.commit()
                partition = AnalysisPartition(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id="annotate",
                    partition_key="partition-1",
                    ordinal=0,
                    record_start=0,
                    record_end=10,
                    variant_count=10,
                    status="READY",
                    metadata_json={},
                )
                configure_partition(partition, "STANDARD")
                db.add(partition)
                db.commit()

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def claim_one(analysis_id, worker_id):
            try:
                with Session(engine) as db:
                    scheduler = PartitionScheduler(
                        db,
                        cpu_capacity=1.0,
                        memory_mb=1024,
                        lease_seconds=60,
                    )
                    barrier.wait(timeout=10)
                    results.append(
                        scheduler.claim_next(analysis_id, "annotate", worker_id)
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=claim_one, args=(analysis_ids[0], "worker-a")),
            threading.Thread(target=claim_one, args=(analysis_ids[1], "worker-b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert len(results) == 2
        assert sum(result is not None for result in results) == 1

        with Session(engine) as db:
            running = db.scalars(
                select(AnalysisPartition).where(
                    AnalysisPartition.analysis_id.in_(analysis_ids),
                    AnalysisPartition.status == "RUNNING",
                )
            ).all()
            assert len(running) == 1
    finally:
        with Session(engine) as db:
            db.query(AnalysisPartition).filter(
                AnalysisPartition.analysis_id.in_(analysis_ids)
            ).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id.in_(analysis_ids)).delete(
                synchronize_session=False
            )
            db.query(Case).filter(Case.id.in_(case_ids)).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user_id).delete(
                synchronize_session=False
            )
            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete(synchronize_session=False)
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_postgres_partition_lease_fencing_rejects_stale_worker_generation():
    """An expired lease reclaimed by the same worker identity fences the old token."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    partition_id = uuid4()
    worker_id = f"workflow:{analysis_id}"

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"lease-fencing-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Lease Fencing Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.RUNNING,
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

            partition = AnalysisPartition(
                id=partition_id,
                analysis_id=analysis_id,
                step_id="annotate",
                partition_key="partition-1",
                ordinal=0,
                record_start=0,
                record_end=10,
                variant_count=10,
                status="READY",
                metadata_json={},
            )
            configure_partition(partition, "STANDARD")
            db.add(partition)
            db.commit()

        with Session(engine) as first_db:
            first_scheduler = PartitionScheduler(
                first_db,
                cpu_capacity=1.0,
                memory_mb=1024,
                lease_seconds=60,
            )
            first_claim = first_scheduler.claim_next(
                analysis_id, "annotate", worker_id
            )
            assert first_claim is not None
            old_token = first_claim.lease_token
            assert old_token

        # Simulate the first worker disappearing after its lease expires.
        with Session(engine) as db:
            partition = db.get(AnalysisPartition, partition_id)
            partition.lease_expires_at = partition.lease_expires_at.replace(
                year=2000
            )
            db.commit()

        with Session(engine) as second_db:
            second_scheduler = PartitionScheduler(
                second_db,
                cpu_capacity=1.0,
                memory_mb=1024,
                lease_seconds=60,
            )
            second_claim = second_scheduler.claim_next(
                analysis_id, "annotate", worker_id
            )
            assert second_claim is not None
            new_token = second_claim.lease_token
            assert new_token
            assert new_token != old_token

        with Session(engine) as stale_db:
            stale_scheduler = PartitionScheduler(stale_db)
            with pytest.raises(PartitionLeaseError):
                stale_scheduler.heartbeat(
                    partition_id, worker_id, old_token
                )
            with pytest.raises(PartitionLeaseError):
                stale_scheduler.succeed(
                    partition_id, worker_id, old_token
                )
            with pytest.raises(PartitionLeaseError):
                stale_scheduler.fail(
                    partition_id,
                    worker_id,
                    old_token,
                    error_code="STALE_WORKER",
                    error_message="stale worker must be fenced",
                )

        with Session(engine) as db:
            partition = db.get(AnalysisPartition, partition_id)
            assert partition.status == "RUNNING"
            assert partition.lease_owner == worker_id
            assert partition.lease_token == new_token
            assert partition.lease_expires_at is not None
    finally:
        with Session(engine) as db:
            db.query(AnalysisPartition).filter(
                AnalysisPartition.id == partition_id
            ).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(
                synchronize_session=False
            )
            db.query(Case).filter(Case.id == case_id).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user_id).delete(
                synchronize_session=False
            )
            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete(synchronize_session=False)
            db.commit()
        engine.dispose()



@pytest.mark.integration
def test_postgres_worker_loss_during_stage_is_recovered_on_redelivery(monkeypatch):
    """A lost worker releases its execution fence; redelivery recovers only unfinished work."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    from backend.app.domain.enums import StepStatus
    from backend.app.infrastructure.db.models import AuditEvent, WorkflowStep
    import importlib
    celery_module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    from backend.app.workflows.variant import recover_interrupted_execution

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    dispatch_id = uuid4()
    running_step_id = uuid4()
    completed_step_id = uuid4()
    running_partition_id = uuid4()
    completed_partition_id = uuid4()
    lost_worker_db = None
    lost_worker_lock_connection = None
    duplicate_lock_connection = None
    redelivery_lock_connection = None

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"worker-loss-stage-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Worker Loss Stage Test",
                role="LAB_DIRECTOR",
                status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="GERMLINE",
                workflow_id="integration",
                workflow_version="1",
                status=AnalysisStatus.QUEUED,
                queue_task_id=str(dispatch_id),
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        # Keep the advisory lock on a dedicated checked-out connection. A
        # SQLAlchemy Session can return its own connection to the pool on commit.
        lost_worker_lock_connection = engine.connect()
        lost_worker_db = Session(engine)
        assert celery_module._claim_analysis_execution(
            lost_worker_db,
            analysis_id,
            task_id=str(dispatch_id),
            lock_connection=lost_worker_lock_connection,
        ) is True

        with Session(engine) as db:
            db.add_all([
                WorkflowStep(
                    id=running_step_id,
                    analysis_id=analysis_id,
                    step_id="annotate",
                    step_order=3,
                    status=StepStatus.RUNNING,
                    attempt=2,
                    input_artifacts=["normalized-vcf"],
                    output_artifacts=[],
                    metadata_json={"next_step": "annotate", "checkpoint": "batch-4"},
                ),
                WorkflowStep(
                    id=completed_step_id,
                    analysis_id=analysis_id,
                    step_id="normalize",
                    step_order=2,
                    status=StepStatus.SUCCEEDED,
                    attempt=1,
                    input_artifacts=["validated-vcf"],
                    output_artifacts=["normalized-vcf"],
                    metadata_json={"next_step": "annotate", "checkpoint": "complete"},
                ),
                AnalysisPartition(
                    id=running_partition_id,
                    analysis_id=analysis_id,
                    step_id="annotate",
                    partition_key="batch-4",
                    ordinal=4,
                    record_start=400,
                    record_end=500,
                    variant_count=100,
                    status="RUNNING",
                    metadata_json={"variant_ids": ["unfinished-variant"]},
                    resource_class="STANDARD",
                    cpu_request=1.0,
                    memory_mb=1024,
                    attempt=2,
                    lease_owner="worker-lost",
                    lease_expires_at=None,
                ),
                AnalysisPartition(
                    id=completed_partition_id,
                    analysis_id=analysis_id,
                    step_id="annotate",
                    partition_key="batch-3",
                    ordinal=3,
                    record_start=300,
                    record_end=400,
                    variant_count=100,
                    status="SUCCEEDED",
                    metadata_json={"variant_ids": ["completed-variant"]},
                    resource_class="STANDARD",
                    cpu_request=1.0,
                    memory_mb=1024,
                    attempt=1,
                    lease_owner=None,
                    lease_expires_at=None,
                ),
            ])
            db.commit()

        # A concurrent redelivery cannot enter while the original worker still
        # owns the PostgreSQL advisory lock.
        duplicate_lock_connection = engine.connect()
        with Session(engine) as duplicate_db:
            assert celery_module._claim_analysis_execution(
                duplicate_db,
                analysis_id,
                task_id=str(dispatch_id),
                allow_running=True,
                lock_connection=duplicate_lock_connection,
            ) is False
        duplicate_lock_connection.close()
        duplicate_lock_connection = None

        # Worker death closes both its database session and the dedicated
        # lock connection; PostgreSQL then releases the execution fence.
        lost_worker_db.close()
        lost_worker_db = None
        # A normal SQLAlchemy Connection.close() returns the connection to its
        # pool; session-level advisory locks intentionally survive that. Invalidate
        # the physical connection to model the server observing worker-process loss.
        lost_worker_lock_connection.invalidate()
        lost_worker_lock_connection.close()
        lost_worker_lock_connection = None

        redelivery_lock_connection = engine.connect()
        with Session(engine) as redelivery_claim_db:
            assert celery_module._claim_analysis_execution(
                redelivery_claim_db,
                analysis_id,
                task_id=str(dispatch_id),
                allow_running=True,
                lock_connection=redelivery_lock_connection,
            ) is True
            with Session(engine) as recovery_db:
                assert recover_interrupted_execution(recovery_db, analysis_id) is True

            with Session(engine) as verify_db:
                analysis = verify_db.get(Analysis, analysis_id)
                running_step = verify_db.get(WorkflowStep, running_step_id)
                completed_step = verify_db.get(WorkflowStep, completed_step_id)
                running_partition = verify_db.get(AnalysisPartition, running_partition_id)
                completed_partition = verify_db.get(AnalysisPartition, completed_partition_id)

                assert analysis.status == AnalysisStatus.RUNNING
                assert running_step.status == StepStatus.RETRYING
                assert running_step.error_code == "WORKER_INTERRUPTED"
                assert running_step.attempt == 2
                assert running_step.metadata_json["next_step"] == "annotate"
                assert running_step.metadata_json["recovery"] == "CELERY_REDELIVERY"
                assert running_partition.status == "READY"
                assert running_partition.lease_owner is None
                assert running_partition.lease_token is None
                assert running_partition.lease_expires_at is None
                assert running_partition.error_code == "WORKER_INTERRUPTED"

                # Durable successful checkpoints are not invalidated or replayed.
                assert completed_step.status == StepStatus.SUCCEEDED
                assert completed_step.output_artifacts == ["normalized-vcf"]
                assert completed_step.metadata_json["checkpoint"] == "complete"
                assert completed_partition.status == "SUCCEEDED"
                assert completed_partition.metadata_json["variant_ids"] == ["completed-variant"]
                assert completed_partition.attempt == 1

                recovery_events = verify_db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.analysis_id == analysis_id,
                        AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
                    )
                ).all()
                assert len(recovery_events) == 1
                assert recovery_events[0].payload["recovered_partitions"] == 1

            with Session(engine) as recovery_db:
                assert recover_interrupted_execution(recovery_db, analysis_id) is False
            with Session(engine) as verify_db:
                assert verify_db.query(AuditEvent).filter(
                    AuditEvent.analysis_id == analysis_id,
                    AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
                ).count() == 1
    finally:
        if lost_worker_db is not None:
            lost_worker_db.close()
        if lost_worker_lock_connection is not None:
            lost_worker_lock_connection.close()
        if duplicate_lock_connection is not None:
            duplicate_lock_connection.close()
        if redelivery_lock_connection is not None:
            redelivery_lock_connection.close()
        with Session(engine) as db:
            db.query(AnalysisPartition).filter(
                AnalysisPartition.analysis_id == analysis_id
            ).delete()
            db.query(WorkflowStep).filter(
                WorkflowStep.analysis_id == analysis_id
            ).delete()
            db.query(AuditEvent).filter(
                AuditEvent.analysis_id == analysis_id
            ).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(ResourceDeploymentProfile).filter(
                ResourceDeploymentProfile.organization_id == organization_id
            ).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
