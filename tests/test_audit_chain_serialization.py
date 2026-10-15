from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import AuditEvent


def test_audit_events_link_to_the_prior_durable_hash():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        audit = AuditService(db)
        audit.record(
            event_type="TEST_FIRST",
            case_id=None,
            analysis_id=None,
            actor_type="SYSTEM",
            actor_id="audit-chain-test",
        )
        db.commit()
        first = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "TEST_FIRST"))
        assert first is not None

        audit.record(
            event_type="TEST_SECOND",
            case_id=None,
            analysis_id=None,
            actor_type="SYSTEM",
            actor_id="audit-chain-test",
        )
        db.commit()
        second = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "TEST_SECOND"))

        assert second is not None
        assert second.previous_event_hash == first.event_hash
        assert first.event_hash != second.event_hash

    engine.dispose()
