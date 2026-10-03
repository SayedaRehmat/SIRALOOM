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

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"integration-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Integration Test",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
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
