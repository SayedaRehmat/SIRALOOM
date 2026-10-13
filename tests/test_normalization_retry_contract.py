from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, AuditEvent, Case, Organization, User, WorkflowStep
from backend.app.workflows.variant import _schedule_transient_step_retry


def test_normalization_persistence_failure_preserves_checkpoint_for_retry(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'normalization-retry.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4(), uuid4(), uuid4(), uuid4())
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="Normalization Retry Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Normalization Retry", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"NORM-RETRY-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status=AnalysisStatus.RUNNING, queue_task_id="normalization-retry",
                reference_build="GRCh38", configuration={},
                started_at=datetime.now(timezone.utc), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.flush()
            db.add(WorkflowStep(
                id=uuid4(), analysis_id=analysis_id, step_id="normalize",
                step_order=2, status=StepStatus.RUNNING, attempt=1,
                input_artifacts=["source-vcf"], output_artifacts=[],
                metadata_json={"next_step": "normalize", "durable_checkpoint": "source-validated"},
            ))
            db.commit()

            _schedule_transient_step_retry(
                db, analysis_id=analysis_id, step_id="normalize",
                error_code="NORMALIZATION_PERSISTENCE_RETRYING",
                error_message="injected storage failure",
                event_type="NORMALIZATION_RETRY_SCHEDULED",
                actor_id="siraloom-normalizer", next_step="normalize",
            )

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "NORMALIZATION_RETRY_SCHEDULED",
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert step.status == StepStatus.RETRYING
            assert step.error_code == "NORMALIZATION_PERSISTENCE_RETRYING"
            assert step.metadata_json["durable_checkpoint"] == "source-validated"
            assert step.metadata_json["next_step"] == "normalize"
            assert step.metadata_json["retry_policy"] == "bounded_transient_retry"
            assert event is not None
            assert event.payload["error_code"] == "NORMALIZATION_PERSISTENCE_RETRYING"
    finally:
        engine.dispose()
