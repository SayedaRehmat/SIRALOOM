import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.application.analysis import enqueue_analysis
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
def test_postgres_retry_supersedes_old_dispatch_while_legacy_relay_runs(monkeypatch):
    """A retry generation must remain the sole queue owner if an older relay races it."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    analysis_id = uuid4()
    old_dispatch_id = uuid4()

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

    # Keep the enqueue fast path deterministic: the integration assertion is
    # about generation ownership, while publication itself is covered by the
    # dedicated relay integration test above.
    monkeypatch.setattr(
        celery_module,
        "publish_analysis_dispatch",
        lambda _dispatch_id: None,
    )

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def retry_one():
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                results.append(enqueue_analysis(db, db.get(Analysis, analysis_id)))
        except Exception as exc:
            errors.append(exc)

    def relay_old_one():
        try:
            barrier.wait(timeout=10)
            results.append(celery_module.publish_analysis_dispatch(old_dispatch_id))
        except Exception as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=retry_one),
        threading.Thread(target=relay_old_one),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
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
            assert len(dispatches) == 2
            old_dispatch, new_dispatch = dispatches
            assert old_dispatch.dispatch_generation == 1
            assert old_dispatch.status == "SUPERSEDED"
            assert new_dispatch.dispatch_generation == 2
            assert new_dispatch.status == "PENDING"
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
