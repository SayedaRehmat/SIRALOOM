from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.reanalysis import mark_reanalysis_completed
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Organization,
    ReanalysisCandidate,
)


def test_reanalysis_candidate_closes_only_when_child_completes():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, Case.__table__, Analysis.__table__,
            ReanalysisCandidate.__table__, AuditEvent.__table__,
        ],
    )
    organization_id, case_id, parent_id, child_id, candidate_id = [uuid4() for _ in range(5)]
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Completion Lab", external_identifier=None))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="COMP-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=None,
        ))
        db.add(Analysis(
            id=parent_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=datetime.now(timezone.utc), created_by=None, analysis_version=1,
        ))
        db.add(Analysis(
            id=child_id, case_id=case_id, parent_analysis_id=parent_id, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=datetime.now(timezone.utc), created_by=None, analysis_version=2,
        ))
        db.add(ReanalysisCandidate(
            id=candidate_id, organization_id=organization_id, case_id=case_id,
            parent_analysis_id=parent_id, child_analysis_id=child_id,
            change_event_id=None, trigger_type="POPULATION_UPDATE",
            earliest_affected_step="population", reason="gnomAD changed",
            status="STARTED", acted_at=datetime.now(timezone.utc),
        ))
        db.commit()

        child = db.get(Analysis, child_id)
        assert mark_reanalysis_completed(db, child) is True
        candidate = db.get(ReanalysisCandidate, candidate_id)
        assert candidate.status == "COMPLETED"
        assert candidate.acted_at is not None
        event = db.scalar(select(AuditEvent).where(
            AuditEvent.analysis_id == child_id,
            AuditEvent.event_type == "REANALYSIS_COMPLETED",
        ))
        assert event is not None
        assert event.payload["parent_analysis_id"] == str(parent_id)

        # Completion is idempotent; a second terminal provenance attempt cannot
        # create another completion event.
        assert mark_reanalysis_completed(db, child) is False
        assert db.query(AuditEvent).filter(
            AuditEvent.analysis_id == child_id,
            AuditEvent.event_type == "REANALYSIS_COMPLETED",
        ).count() == 1
