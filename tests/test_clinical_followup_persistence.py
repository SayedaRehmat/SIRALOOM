from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.api.v1 import clinical_followup, quality
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    ConfirmationRecord,
    FollowUpPlan,
    Organization,
    SecondaryFindingDecision,
    TechnicalQCObservation,
    User,
    Variant,
)


def test_governance_create_routes_flush_generated_timestamps_before_audit(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    principal = Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="lab_director",
        subject="verified-test-subject",
    )

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Governance persistence test",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@example.test",
                display_name="Governance test",
                role="lab_director",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=str(case_id),
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            analysis = Analysis(
                id=analysis_id,
                case_id=case_id,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="test",
                workflow_version="1",
                status="REQUIRES_REVIEW",
                reference_build="GRCh38",
                configuration={},
                created_by=user_id,
                analysis_version=1,
            )
            variant = Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=123,
                reference="A",
                alternate="G",
                normalization_status="NORMALIZED",
                canonical_key=f"GRCh38:1:123:A:G:{variant_id}",
                identifiers={},
            )
            db.add_all([analysis, variant])
            db.commit()

            monkeypatch.setattr(
                clinical_followup,
                "get_accessible_analysis",
                lambda requested_id, session, _principal: session.get(Analysis, requested_id),
            )
            monkeypatch.setattr(
                clinical_followup,
                "_variant_access",
                lambda _analysis, requested_id, session: session.get(Variant, requested_id),
            )
            monkeypatch.setattr(clinical_followup, "require_role", lambda *_args: None)
            monkeypatch.setattr(
                quality,
                "get_accessible_analysis",
                lambda requested_id, session, _principal: session.get(Analysis, requested_id),
            )
            monkeypatch.setattr(quality, "require_role", lambda *_args: None)

            confirmation = clinical_followup.record_confirmation(
                analysis_id,
                variant_id,
                clinical_followup.ConfirmationInput(required=True, status="PENDING"),
                db,
                principal,
            )
            follow_up = clinical_followup.create_followup(
                analysis_id,
                variant_id,
                clinical_followup.FollowUpInput(action_type="confirmatory testing"),
                db,
                principal,
            )
            completed_follow_up = clinical_followup.update_followup(
                UUID(follow_up["id"]),
                clinical_followup.FollowUpInput(
                    action_type="confirmatory testing", status="COMPLETED"
                ),
                db,
                principal,
            )
            assert completed_follow_up["completed_by"] == str(user_id)
            assert completed_follow_up["completed_at"]
            reopened_follow_up = clinical_followup.update_followup(
                UUID(follow_up["id"]),
                clinical_followup.FollowUpInput(
                    action_type="confirmatory testing", status="IN_PROGRESS"
                ),
                db,
                principal,
            )
            assert reopened_follow_up["completed_by"] is None
            assert reopened_follow_up["completed_at"] is None
            secondary = clinical_followup.record_secondary_finding(
                analysis_id,
                variant_id,
                clinical_followup.SecondaryFindingInput(
                    policy_name="LAB_POLICY",
                    policy_version="1",
                    status="DRAFT",
                ),
                db,
                principal,
            )
            qc_observation = quality.record_qc_observation(
                analysis_id,
                quality.QCObservationInput(
                    metric_name="coverage_mean",
                    metric_value=42.0,
                ),
                db,
                principal,
            )

            assert confirmation["created_at"]
            assert follow_up["created_at"]
            assert secondary["created_at"]
            assert secondary["status"] == "DRAFT"
            assert qc_observation["created_at"]
            events = db.scalars(
                select(AuditEvent).where(AuditEvent.analysis_id == analysis_id)
            ).all()
            assert len(events) == 6
            assert all(event.after_state["created_at"] for event in events)
            assert len(db.scalars(select(ConfirmationRecord)).all()) == 1
            assert len(db.scalars(select(FollowUpPlan)).all()) == 1
            assert len(db.scalars(select(SecondaryFindingDecision)).all()) == 1
            assert len(db.scalars(select(TechnicalQCObservation)).all()) == 1
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (clinical_followup.ConfirmationInput, {"status": "REVIEWED"}),
        (
            clinical_followup.FollowUpInput,
            {"action_type": "confirmatory testing", "status": "UNKNOWN"},
        ),
        (
            clinical_followup.SecondaryFindingInput,
            {"policy_name": "LAB_POLICY", "policy_version": "1", "status": "SIGNED"},
        ),
    ],
)
def test_governance_input_rejects_unsupported_states(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)
