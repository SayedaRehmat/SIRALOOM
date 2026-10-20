"""Failure/retry contracts for workflow stages with durable side effects.

These tests complement the all-stage worker-loss state matrix. They exercise
production retry-state persistence for stages whose durable writes can fail.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
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
from backend.app.workflows.variant import _route_step_to_human_review, _schedule_transient_step_retry


@pytest.mark.parametrize(
    ("stage_id", "error_code", "event_type", "actor_id"),
    [
        ("report", "REPORT_GENERATION_RETRYING", "REPORT_GENERATION_RETRY_SCHEDULED", "reporting"),
        ("population", "POPULATION_PERSISTENCE_RETRYING", "POPULATION_PERSISTENCE_RETRY_SCHEDULED", "gnomad"),
        ("build_evidence", "EVIDENCE_PERSISTENCE_RETRYING", "EVIDENCE_PERSISTENCE_RETRY_SCHEDULED", "siraloom-evidence"),
        ("acmg_assessment", "ACMG_PERSISTENCE_RETRYING", "ACMG_PERSISTENCE_RETRY_SCHEDULED", "siraloom-acmg-specification-engine"),
    ],
)
def test_stage_persistence_failure_is_durable_and_retryable(
    tmp_path, stage_id, error_code, event_type, actor_id
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (stage_id + '-retry.db')}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    step_order = {
        "population": 4,
        "build_evidence": 5,
        "acmg_assessment": 6,
        "report": 9,
    }[stage_id]
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Stage Retry Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Stage Retry Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"STAGE-RETRY-{stage_id}-{case_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="test",
                status=AnalysisStatus.RUNNING,
                queue_task_id="dispatch-stage-retry",
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()
            db.add(WorkflowStep(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id=stage_id,
                step_order=step_order,
                status=StepStatus.RUNNING,
                attempt=1,
                input_artifacts=["durable-stage-inputs"],
                output_artifacts=[],
                metadata_json={
                    "next_step": stage_id,
                    "durable_checkpoint": f"{stage_id}-inputs-ready",
                },
            ))
            db.commit()

            _schedule_transient_step_retry(
                db,
                analysis_id=analysis_id,
                step_id=stage_id,
                error_code=error_code,
                error_message="Injected persistence failure",
                event_type=event_type,
                actor_id=actor_id,
                next_step=stage_id,
            )

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == stage_id,
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert step.status == StepStatus.RETRYING
            assert step.error_code == error_code
            assert step.error_message == "Injected persistence failure"
            assert step.input_artifacts == ["durable-stage-inputs"]
            assert step.metadata_json["durable_checkpoint"] == f"{stage_id}-inputs-ready"
            assert step.metadata_json["next_step"] == stage_id
            assert step.metadata_json["retry_policy"] == "bounded_transient_retry"

            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == event_type,
            ))
            assert event is not None
            assert event.payload["error_code"] == error_code
            assert event.payload["next_step"] == stage_id
    finally:
        engine.dispose()



def test_missing_clingen_resource_routes_acmg_to_resumable_human_review(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'acmg-resource-review.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4(), uuid4(), uuid4(), uuid4())
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="ACMG Review Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="ACMG Review Test", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"ACMG-REVIEW-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.RUNNING, queue_task_id="missing-clingen-test",
                reference_build="GRCh38", configuration={},
                started_at=datetime.now(timezone.utc), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            db.add(WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="acmg_assessment",
                step_order=6, status=StepStatus.RUNNING, attempt=1,
                input_artifacts=[], output_artifacts=[],
                metadata_json={"next_step": "acmg_assessment"},
            ))
            db.commit()

            _route_step_to_human_review(
                db,
                analysis_id=analysis_id,
                step_id="acmg_assessment",
                error_code="CLINGEN_SPECIFICATION_UNAVAILABLE",
                error_message="No approved ClinGen specification is available.",
                event_type="ACMG_RESOURCE_REQUIRES_REVIEW",
                actor_id="acmg-resource",
                next_step="review",
                payload={"resource_gap": True},
            )

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "acmg_assessment",
            ))
            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ACMG_RESOURCE_REQUIRES_REVIEW",
            ))
            assert analysis.status == AnalysisStatus.REQUIRES_REVIEW
            assert analysis.completed_at is None
            assert step.status == StepStatus.REQUIRES_REVIEW
            assert step.error_code == "CLINGEN_SPECIFICATION_UNAVAILABLE"
            assert step.metadata_json["next_step"] == "review"
            assert step.metadata_json["human_action_required"] is True
            assert event is not None
            assert event.payload["resource_gap"] is True
            assert event.payload["human_action_required"] is True

            # Model the authorized reviewer supplying an explicit manual
            # classification and accepting the gate. This must create one durable
            # dispatch so the workflow can resume; it must not sign out a report.
            variant_id = uuid4()
            db.add(Variant(
                id=variant_id, genome_build="GRCh38", chromosome="1",
                position=12345, reference="A", alternate="G",
                normalization_status="NORMALIZED",
                canonical_key=f"GRCh38:1:12345:A:G:{variant_id}",
                identifiers={},
            ))
            db.flush()
            db.add(Classification(
                id=uuid4(), variant_id=variant_id, analysis_id=analysis_id,
                framework_name="ACMG/AMP", framework_version="2015",
                specification_provider=None, specification_id=None,
                specification_version=None, result="VUS", criterion_ids=[],
                metadata_json={"decision_mode": "MANUAL"},
                state="FINAL", review_status="APPROVED", version=1,
            ))
            db.commit()

            from types import SimpleNamespace
            from backend.app.api.v1 import workflow as workflow_api
            from backend.app.infrastructure.queue import celery_app

            published = []
            monkeypatch = pytest.MonkeyPatch()
            try:
                monkeypatch.setattr(
                    workflow_api, "get_accessible_analysis",
                    lambda requested_id, session, _principal, *_args: session.get(Analysis, requested_id),
                )
                monkeypatch.setattr(workflow_api, "require_role", lambda *_args, **_kwargs: None)
                monkeypatch.setattr(
                    celery_app, "publish_analysis_dispatch",
                    lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
                )
                principal = SimpleNamespace(
                    organization_id=organization_id, user_id=user_id,
                )
                result = workflow_api.resolve_human_gate_endpoint(
                    analysis_id,
                    "acmg_assessment",
                    workflow_api.HumanGateRequest(
                        decision=workflow_api.HumanGateDecision.ACCEPT,
                        reason="Manual classification reviewed and approved after missing ClinGen specification.",
                        expected_attempt=1,
                    ),
                    db,
                    principal,
                )
                assert result["status"] == StepStatus.SUCCEEDED
                assert result["next_step"] == "review"
                assert result["workflow_resume_queued"] is True
                assert db.get(Analysis, analysis_id).status == AnalysisStatus.QUEUED
                assert db.query(AnalysisDispatch).filter_by(analysis_id=analysis_id).count() == 1
                assert db.query(AuditEvent).filter_by(
                    analysis_id=analysis_id,
                    event_type="WORKFLOW_HUMAN_GATE_RESOLVED",
                ).count() == 1
                assert len(published) == 1
            finally:
                monkeypatch.undo()
    finally:
        engine.dispose()
