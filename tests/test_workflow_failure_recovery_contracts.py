"""Failure/retry contracts for workflow stages with durable side effects.

These tests complement the all-stage worker-loss state matrix. They exercise
production retry-state persistence and ensure report generation failures remain
retryable rather than being silently converted into terminal analysis failures.
"""
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Organization,
    User,
    WorkflowStep,
)
from backend.app.workflows.variant import _schedule_transient_step_retry


def test_report_stage_failure_is_durable_and_retryable(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'report-retry.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Report Retry Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Report Retry Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"REPORT-RETRY-{case_id}",
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
                queue_task_id="dispatch-report-retry",
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
                step_id="report",
                step_order=9,
                status=StepStatus.RUNNING,
                attempt=1,
                input_artifacts=["reviewed-classifications"],
                output_artifacts=[],
                metadata_json={
                    "next_step": "report",
                    "durable_checkpoint": "report-inputs-ready",
                },
            ))
            db.commit()

            _schedule_transient_step_retry(
                db,
                analysis_id=analysis_id,
                step_id="report",
                error_code="REPORT_GENERATION_RETRYING",
                error_message="Injected PDF artifact-store failure",
                event_type="REPORT_GENERATION_RETRY_SCHEDULED",
                actor_id="reporting",
                next_step="report",
            )

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "report",
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert step.status == StepStatus.RETRYING
            assert step.error_code == "REPORT_GENERATION_RETRYING"
            assert step.error_message == "Injected PDF artifact-store failure"
            assert step.input_artifacts == ["reviewed-classifications"]
            assert step.metadata_json["durable_checkpoint"] == "report-inputs-ready"
            assert step.metadata_json["next_step"] == "report"
            assert step.metadata_json["retry_policy"] == "bounded_transient_retry"

            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "REPORT_GENERATION_RETRY_SCHEDULED",
            ))
            assert event is not None
            assert event.payload["error_code"] == "REPORT_GENERATION_RETRYING"
            assert event.payload["next_step"] == "report"
    finally:
        engine.dispose()
