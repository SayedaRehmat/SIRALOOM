"""PostgreSQL integration checks for task-lifetime execution ownership locks."""

import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.infrastructure.db.models import (
    AuditEvent,
    Case,
    CaseExport,
    CaseExportDispatch,
    Organization,
    User,
)


@pytest.mark.integration
def test_case_export_lock_survives_orm_commit_and_releases_with_task_connection():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    from backend.app.infrastructure.queue.celery_app import (
        _claim_case_export_execution,
    )

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, export_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    task_id = f"export-dispatch-{export_id}"
    lock_connection = None
    competing_connection = None
    try:
        # Persist each FK dependency before the dependent row to avoid relying
        # on ORM flush ordering for unrelated entities.
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"Export Lock Integration {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@export-lock.integration.test",
                display_name="Export Lock Integration",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.commit()
        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"EXPORT-LOCK-{export_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()
        with Session(engine) as db:
            db.add(CaseExport(
                id=export_id,
                case_id=case_id,
                requested_by=user_id,
                status="RUNNING",
                queue_task_id=task_id,
            ))
            db.commit()

        lock_connection = engine.connect()
        competing_connection = engine.connect()
        with Session(engine) as db:
            assert _claim_case_export_execution(
                db,
                export_id,
                task_id=task_id,
                allow_running=True,
                lock_connection=lock_connection,
            ) is True
            # The claim's ORM commit must not return the advisory-lock session
            # to the pool. A different PostgreSQL session must still be fenced.
            assert db.in_transaction() is False

        lock_key = int.from_bytes(
            hashlib.sha256(str(export_id).encode("utf-8")).digest()[:8],
            byteorder="big",
            signed=True,
        )
        competing_acquired = competing_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one()
        competing_connection.commit()
        assert competing_acquired is False

        unlocked = lock_connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one()
        lock_connection.commit()
        lock_connection.info.pop(
            "siraloom_case_export_execution_lock_key", None
        )
        assert unlocked is True

        # After task cleanup releases ownership, another worker can acquire it.
        assert competing_connection.execute(
            text("SELECT pg_try_advisory_lock(:lock_key)"),
            {"lock_key": lock_key},
        ).scalar_one() is True
        competing_connection.commit()
        competing_connection.execute(
            text("SELECT pg_advisory_unlock(:lock_key)"),
            {"lock_key": lock_key},
        )
        competing_connection.commit()
    finally:
        if lock_connection is not None:
            lock_key = lock_connection.info.pop(
                "siraloom_case_export_execution_lock_key", None
            )
            try:
                if lock_key is not None:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    )
                    lock_connection.commit()
            except Exception:
                lock_connection.invalidate()
            lock_connection.close()
        if competing_connection is not None:
            competing_connection.close()
        with Session(engine) as db:
            db.query(CaseExport).filter(CaseExport.id == export_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete()
            db.commit()
        engine.dispose()


@pytest.mark.integration
def test_case_export_recovery_uses_postgres_lock_when_celery_result_is_missing(
    monkeypatch,
):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    from backend.app.infrastructure.db import session as session_module
    from backend.app.infrastructure.queue import celery_app as queue

    engine = create_engine(database_url, pool_pre_ping=True)
    make_session = sessionmaker(
        bind=engine, expire_on_commit=False, class_=Session
    )
    organization_id, user_id, case_id, export_id, dispatch_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    task_id = f"expired-export-result-{export_id}"
    try:
        with make_session() as db:
            db.add(Organization(
                id=organization_id,
                name=f"Export Recovery Integration {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@export-recovery.integration.test",
                display_name="Export Recovery Integration",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.commit()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"EXPORT-RECOVERY-{export_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()
            db.add(CaseExport(
                id=export_id,
                case_id=case_id,
                requested_by=user_id,
                status="RUNNING",
                queue_task_id=task_id,
            ))
            db.commit()
            db.add(CaseExportDispatch(
                id=dispatch_id,
                case_export_id=export_id,
                dispatch_generation=1,
                status="PUBLISHED",
                task_id=task_id,
                attempts=1,
            ))
            db.commit()

        monkeypatch.setattr(session_module, "engine", engine)
        monkeypatch.setattr(session_module, "SessionLocal", make_session)
        monkeypatch.setattr(
            queue.celery_app,
            "AsyncResult",
            lambda _task_id: type("Result", (), {"state": "PENDING"})(),
        )

        publication_observations = []

        def publish_after_recovery(replacement_id):
            with make_session() as db:
                export = db.get(CaseExport, export_id)
                old_dispatch = db.get(CaseExportDispatch, dispatch_id)
                replacement = db.get(CaseExportDispatch, replacement_id)
                assert export.status == "QUEUED"
                assert export.queue_task_id == str(replacement_id)
                assert old_dispatch.status == "SUPERSEDED"
                assert replacement.status == "PENDING"

            lock_key = int.from_bytes(
                hashlib.sha256(str(export_id).encode("utf-8")).digest()[:8],
                byteorder="big",
                signed=True,
            )
            with engine.connect() as lock_check:
                acquired = lock_check.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": lock_key},
                ).scalar_one()
                lock_check.commit()
                publication_observations.append(bool(acquired))
                assert acquired is True
                lock_check.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
                lock_check.commit()
            return "replacement-task"

        monkeypatch.setattr(queue, "publish_case_export_dispatch", publish_after_recovery)
        result = queue.recover_orphaned_case_export_dispatches.run()

        assert result == {"inspected": 1, "recovered": 1}
        assert publication_observations == [True]
        with make_session() as db:
            recovery_event = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.case_id == case_id,
                    AuditEvent.event_type == "CASE_EXPORT_DISPATCH_RECOVERED",
                )
            )
            assert recovery_event.payload["recovery_reason"] == "EXECUTION_LOCK_UNHELD"
            assert recovery_event.payload["celery_state"] == "PENDING"
    finally:
        with make_session() as db:
            db.query(AuditEvent).filter(AuditEvent.case_id == case_id).delete(
                synchronize_session=False
            )
            db.query(CaseExportDispatch).filter(
                CaseExportDispatch.case_export_id == export_id
            ).delete(synchronize_session=False)
            db.query(CaseExport).filter(CaseExport.id == export_id).delete(
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
