from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    AuditEvent,
    Case,
    CaseExport,
    CaseExportDispatch,
    Organization,
    User,
)
from backend.app.infrastructure.queue import celery_app as queue


def _seed_running_export(*, generation: int = 1):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    make_session = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    db = make_session()
    organization = Organization(id=uuid4(), name="Lab")
    user = User(
        id=uuid4(),
        organization_id=organization.id,
        display_name="Auditor",
        role="AUDITOR",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=organization.id,
        case_identifier="CASE-EXPORT-RECOVERY",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    export = CaseExport(
        id=uuid4(),
        case_id=case.id,
        requested_by=user.id,
        status="RUNNING",
        queue_task_id="failed-export-task",
    )
    dispatch = CaseExportDispatch(
        id=uuid4(),
        case_export_id=export.id,
        dispatch_generation=generation,
        status="PUBLISHED",
        task_id=export.queue_task_id,
        attempts=1,
    )
    db.add_all([organization, user, case, export, dispatch])
    db.commit()
    return engine, make_session, export.id, dispatch.id


@pytest.mark.parametrize("task_state", ["PENDING", "STARTED", "RETRY", "UNKNOWN"])
def test_running_export_is_not_recovered_from_nonterminal_task_state(
    monkeypatch, task_state
):
    engine, make_session, export_id, _dispatch_id = _seed_running_export()
    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal", make_session
    )
    monkeypatch.setattr(
        queue.celery_app,
        "AsyncResult",
        lambda _task_id: type("Result", (), {"state": task_state})(),
    )
    monkeypatch.setattr(
        queue,
        "publish_case_export_dispatch",
        lambda _dispatch_id: pytest.fail("nonterminal task must not be duplicated"),
    )

    result = queue.recover_orphaned_case_export_dispatches.run()

    with make_session() as verify:
        export = verify.get(CaseExport, export_id)
        assert export.status == "RUNNING"
        assert export.queue_task_id == "failed-export-task"
        assert verify.scalars(select(AuditEvent)).all() == []
    assert result == {"inspected": 1, "recovered": 0}
    engine.dispose()


def test_failed_running_export_gets_one_durable_replacement_dispatch(monkeypatch):
    engine, make_session, export_id, old_dispatch_id = _seed_running_export()
    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal", make_session
    )
    monkeypatch.setattr(
        queue.celery_app,
        "AsyncResult",
        lambda _task_id: type("Result", (), {"state": "FAILURE"})(),
    )
    published = []

    def publish(dispatch_id):
        published.append(dispatch_id)
        return "replacement-task"

    monkeypatch.setattr(queue, "publish_case_export_dispatch", publish)

    result = queue.recover_orphaned_case_export_dispatches.run()
    duplicate_result = queue.recover_orphaned_case_export_dispatches.run()

    with make_session() as verify:
        export = verify.get(CaseExport, export_id)
        old_dispatch = verify.get(CaseExportDispatch, old_dispatch_id)
        dispatches = verify.scalars(
            select(CaseExportDispatch)
            .where(CaseExportDispatch.case_export_id == export_id)
            .order_by(CaseExportDispatch.dispatch_generation)
        ).all()
        events = verify.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "CASE_EXPORT_DISPATCH_RECOVERED"
            )
        ).all()
        assert export.status == "QUEUED"
        assert export.queue_task_id == str(dispatches[1].id)
        assert old_dispatch.status == "SUPERSEDED"
        assert [(row.dispatch_generation, row.status) for row in dispatches] == [
            (1, "SUPERSEDED"),
            (2, "PENDING"),
        ]
        assert len(events) == 1
        assert events[0].payload["previous_task_id"] == "failed-export-task"
        assert events[0].payload["celery_state"] == "FAILURE"
        assert len(dispatches) == 2
    assert published == [dispatches[1].id]
    assert result == {"inspected": 1, "recovered": 1}
    assert duplicate_result == {"inspected": 0, "recovered": 0}
    engine.dispose()


def test_failed_export_at_recovery_limit_becomes_audited_terminal_failure(
    monkeypatch,
):
    engine, make_session, export_id, dispatch_id = _seed_running_export(generation=4)
    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal", make_session
    )
    monkeypatch.setattr(
        queue.celery_app,
        "AsyncResult",
        lambda _task_id: type("Result", (), {"state": "REVOKED"})(),
    )
    monkeypatch.setattr(
        queue,
        "publish_case_export_dispatch",
        lambda _dispatch_id: pytest.fail("retry limit must stop dispatch"),
    )

    result = queue.recover_orphaned_case_export_dispatches.run()

    with make_session() as verify:
        export = verify.get(CaseExport, export_id)
        dispatch = verify.get(CaseExportDispatch, dispatch_id)
        event = verify.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "CASE_EXPORT_FAILED")
        )
        assert export.status == "FAILED"
        assert export.error_code == "CASE_EXPORT_RETRY_EXHAUSTED"
        assert export.error_message == (
            "Case export failed after the configured number of attempts. "
            "Contact a laboratory administrator."
        )
        assert dispatch.status == "FAILED"
        assert event is not None
        assert event.operation == "RETRY_EXHAUSTED"
        assert event.payload["dispatch_generation"] == 4
        assert event.payload["celery_state"] == "REVOKED"
    assert result == {"inspected": 1, "recovered": 0}
    engine.dispose()
