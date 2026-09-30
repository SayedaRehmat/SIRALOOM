from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.reanalysis import affected_step_for_trigger, create_change_event, detect_change
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisResourceSnapshot,
    Case,
    Notification,
    Organization,
    OrganizationMembership,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
    User,
)


def test_reanalysis_trigger_dependency_contract():
    assert affected_step_for_trigger("ANNOTATION_UPDATE") == "annotate"
    assert affected_step_for_trigger("POPULATION_UPDATE") == "population"
    assert affected_step_for_trigger("EVIDENCE_UPDATE") == "build_evidence"
    assert affected_step_for_trigger("ACMG_RULE_UPDATE") == "acmg_assessment"
    assert affected_step_for_trigger("REFERENCE_UPDATE") == "normalize"
    assert affected_step_for_trigger("MANUAL") == "normalize"


def _engine():
    return create_engine("sqlite+pysqlite:///:memory:")


def test_change_detector_creates_durable_candidate_and_notifications_idempotently():
    engine = _engine()
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__, User.__table__, OrganizationMembership.__table__,
            Case.__table__, Analysis.__table__, AnalysisResourceSnapshot.__table__,
            ReanalysisChangeEvent.__table__, ReanalysisCandidate.__table__, Notification.__table__,
        ],
    )

    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Reanalysis Test Lab", external_identifier=None))
        db.add(User(
            id=user_id, organization_id=organization_id, external_subject=None,
            email="analyst@test.local", display_name="Analyst", role="ANALYST", status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=user_id,
            role="ANALYST", status="ACTIVE",
        ))
        db.add(Case(
            id=case_id, organization_id=organization_id, case_identifier="REAN-001",
            status="ACTIVE", clinical_context={}, language="en", created_by=user_id,
        ))
        db.add(Analysis(
            id=analysis_id, case_id=case_id, parent_analysis_id=None, assay_id=None,
            analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1",
            workflow_version="2.1", status="SUCCEEDED", queue_task_id=None,
            reference_build="GRCh38", configuration={}, started_at=None,
            completed_at=None, created_by=user_id, analysis_version=1,
        ))
        db.add(AnalysisResourceSnapshot(
            id=uuid4(), analysis_id=analysis_id, resource_id=None,
            resource_kind="POPULATION", resource_name="gnomAD",
            provider="gnomAD", version="v3.1.2", checksum="old",
            genome_build="GRCh38", metadata_json={},
        ))
        db.commit()

        candidates = detect_change(
            db, organization_id=organization_id, trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION", resource_name="gnomAD",
            new_version="v4.1", new_checksum="new",
        )
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.earliest_affected_step == "population"
        assert candidate.status == "PENDING"

        notifications = db.query(Notification).filter(
            Notification.candidate_id == candidate.id
        ).all()
        assert len(notifications) == 1
        assert notifications[0].status == "UNREAD"

        # Re-registering the identical change must not create another candidate
        # or another notification.
        again = detect_change(
            db, organization_id=organization_id, trigger_type="POPULATION_UPDATE",
            resource_kind="POPULATION", resource_name="gnomAD",
            new_version="v4.1", new_checksum="new",
        )
        assert again == []
        assert db.query(ReanalysisCandidate).count() == 1
        assert db.query(Notification).count() == 1
        assert db.query(ReanalysisChangeEvent).count() == 1
