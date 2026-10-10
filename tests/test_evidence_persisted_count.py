from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Evidence
from backend.app.workflows.variant import _count_persisted_evidence


def test_persisted_evidence_count_includes_rows_from_previous_attempts():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Evidence.__table__])
    analysis_id = uuid4()

    try:
        with Session(engine) as db:
            assert _count_persisted_evidence(db, analysis_id) == 0

            db.add(
                Evidence(
                    id=uuid4(),
                    variant_id=uuid4(),
                    analysis_id=analysis_id,
                    evidence_type="ANNOTATION",
                    statement="A persisted annotation observation exists.",
                    direction="SUPPORTING",
                    source_name="test-provider",
                    source_version="test-release",
                    resource_id=None,
                    source_record_id="test-record",
                    request_fingerprint="request-fingerprint",
                    response_sha256="response-sha256",
                    request_metadata={},
                    observed_at=None,
                    observation_ids=[],
                    payload={"fixture": True},
                    created_by_type="SYSTEM",
                    created_by_id="test",
                    evidence_fingerprint="persisted-evidence-fingerprint",
                )
            )
            db.commit()

            # This row represents evidence committed by an earlier attempt whose
            # batch-success checkpoint was lost during worker interruption.
            assert _count_persisted_evidence(db, analysis_id) == 1
    finally:
        engine.dispose()
