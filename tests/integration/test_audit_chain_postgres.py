"""PostgreSQL concurrency proof for the global audit hash-chain append lock."""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import AuditEvent


@pytest.mark.integration
def test_concurrent_audit_appends_do_not_fork_the_hash_chain():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    barrier = threading.Barrier(2)
    actor_prefix = f"audit-chain-{uuid4()}"
    errors, event_ids = [], []

    def append_event(index: int):
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                event_id = AuditService(db).record(
                    event_type="AUDIT_CHAIN_CONCURRENCY_TEST",
                    case_id=None,
                    analysis_id=None,
                    actor_type="SYSTEM",
                    actor_id=f"{actor_prefix}-{index}",
                )
                db.commit()
                event_ids.append(event_id)
        except Exception as exc:  # surfaced in the parent test thread  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=append_event, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        with Session(engine) as db:
            events = list(db.scalars(
                select(AuditEvent).where(AuditEvent.id.in_(event_ids))
            ))
            assert len(events) == 2
            events.sort(key=lambda event: event.occurred_at)
            assert events[1].occurred_at > events[0].occurred_at
            assert events[1].previous_event_hash == events[0].event_hash
    finally:
        with Session(engine) as db:
            db.query(AuditEvent).filter(AuditEvent.id.in_(event_ids)).delete(synchronize_session=False)
            db.commit()
        engine.dispose()
