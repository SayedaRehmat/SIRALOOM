"""API-level tests for guarded human workflow gates."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.domain.workflow_human_gate import HumanGateDecision
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisDispatch,
    AuditEvent,
    Case,
    Classification,
    Organization,
    User,
    Variant,
    WorkflowStep,
)


def _seed_gate(db, *, step_id: str, with_classification: bool):
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4() for _ in range(5)
    )
    db.add(Organization(id=organization_id, name="Gate Lab", external_identifier="gate-lab"))
    db.add(
        User(
            id=user_id,
            organization_id=organization_id,
            external_subject="gate-reviewer",
            email="reviewer@example.test",
            display_name="Gate Reviewer",
            role="LAB_REVIEWER",
            status="ACTIVE",
        )
    )
    db.flush()
    db.add(
        Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=f"GATE-{step_id}",
            status="OPEN",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
    )
    db.add(
        Analysis(
            id=analysis_id,
            case_id=case_id,
            parent_analysis_id=None,
            assay_id=None,
            analysis_type="GERMLINE",
            workflow_id="variant",
            workflow_version="1",
            status=AnalysisStatus.REQUIRES_REVIEW,
            queue_task_id=None,
            reference_build="GRCh38",
            configuration={},
            started_at=None,
            completed_at=None,
            created_by=user_id,
        )
    )
    db.add(
        WorkflowStep(
            id=uuid4(),
            analysis_id=analysis_id,
            step_id=step_id,
            step_order=6,
            status=StepStatus.REQUIRES_REVIEW,
            attempt=1,
            input_artifacts=[],
            output_artifacts=[],
            metadata_json={"human_gate": {"cycle": 1, "allow_accept": True}},
        )
    )
    if with_classification:
        db.add(
            Variant(
                id=variant_id,
                genome_build="GRCh38",
                chromosome="1",
                position=12345,
                reference="A",
                alternate="G",
                normalization_status="NORMALIZED",
                canonical_key=f"GRCh38:1:12345:A:G:{variant_id}",
                identifiers={},
            )
        )
        db.flush()
        db.add(
            Classification(
                id=uuid4(),
                variant_id=variant_id,
                analysis_id=analysis_id,
                framework_name="ACMG/AMP",
                framework_version="2015",
                specification_provider=None,
                specification_id=None,
                specification_version=None,
                result="VUS",
                criterion_ids=[],
                metadata_json={},
                state="DRAFT",
                review_status="PENDING",
                version=1,
            )
        )
    db.commit()
    return SimpleNamespace(
        organization_id=organization_id,
        user_id=user_id,
        case_id=case_id,
        analysis_id=analysis_id,
    )


def _wire_route(monkeypatch, db, seeded, published):
    from backend.app.api.v1 import workflow as workflow_api
    from backend.app.infrastructure.queue import celery_app

    monkeypatch.setattr(
        workflow_api,
        "get_accessible_analysis",
        lambda analysis_id, session, _principal: session.get(Analysis, analysis_id),
    )
    monkeypatch.setattr(workflow_api, "require_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        celery_app,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
    )
    principal = SimpleNamespace(
        organization_id=seeded.organization_id,
        user_id=seeded.user_id,
    )
    return workflow_api, principal


def test_review_gate_cannot_be_accepted_without_final_approved_classification(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    published = []

    with Session(engine) as db:
        seeded = _seed_gate(db, step_id="review", with_classification=False)
        workflow_api, principal = _wire_route(monkeypatch, db, seeded, published)
        payload = workflow_api.HumanGateRequest(
            decision=HumanGateDecision.ACCEPT,
            reason="Attempted review release without classification approval.",
            expected_attempt=1,
        )

        with pytest.raises(HTTPException) as exc_info:
            workflow_api.resolve_human_gate_endpoint(
                seeded.analysis_id, "review", payload, db, principal
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail["code"] == "CLASSIFICATION_REVIEW_INCOMPLETE"
        assert db.scalar(select(AnalysisDispatch.id)) is None
        assert db.scalar(select(AuditEvent.id)) is None
        assert published == []

    engine.dispose()


def test_accepting_acmg_gate_audits_and_resumes_through_durable_dispatch(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    published = []

    with Session(engine) as db:
        seeded = _seed_gate(db, step_id="acmg_assessment", with_classification=True)
        workflow_api, principal = _wire_route(monkeypatch, db, seeded, published)
        payload = workflow_api.HumanGateRequest(
            decision=HumanGateDecision.ACCEPT,
            reason="Reviewed the persisted classification and evidence.",
            expected_attempt=1,
        )

        result = workflow_api.resolve_human_gate_endpoint(
            seeded.analysis_id, "acmg_assessment", payload, db, principal
        )

        assert result["status"] == StepStatus.SUCCEEDED
        assert result["next_step"] == "review"
        assert result["workflow_resume_queued"] is True
        assert db.get(Analysis, seeded.analysis_id).status == AnalysisStatus.QUEUED
        assert db.scalar(select(AnalysisDispatch.id)) is not None
        assert db.query(AnalysisDispatch).count() == 1
        assert db.query(AuditEvent).filter_by(event_type="WORKFLOW_HUMAN_GATE_RESOLVED").count() == 1
        assert len(published) == 1

        # A repeated decision cannot pass the gate again or enqueue another run.
        with pytest.raises(HTTPException) as exc_info:
            workflow_api.resolve_human_gate_endpoint(
                seeded.analysis_id, "acmg_assessment", payload, db, principal
            )
        assert exc_info.value.status_code == 409
        assert db.query(AnalysisDispatch).count() == 1
        assert len(published) == 1

    engine.dispose()
