import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.application.analysis import enqueue_analysis, resume_analysis
from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch, Case, Organization, User


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
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
