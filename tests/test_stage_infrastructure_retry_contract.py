from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, AnalysisPartition, AuditEvent, Case, Organization, User, WorkflowStep
from backend.app.workflows.variant import _schedule_transient_step_retry


@pytest.mark.parametrize(
    ("step_id", "error_code", "event_type"),
    [
        ("population", "POPULATION_STORAGE_RETRYING", "POPULATION_STORAGE_RETRY_SCHEDULED"),
        ("build_evidence", "EVIDENCE_INFRASTRUCTURE_RETRYING", "EVIDENCE_INFRASTRUCTURE_RETRY_SCHEDULED"),
        ("acmg_assessment", "ACMG_INFRASTRUCTURE_RETRYING", "ACMG_INFRASTRUCTURE_RETRY_SCHEDULED"),
    ],
)
def test_stage_infrastructure_failure_persists_retry_checkpoint(
    tmp_path, step_id, error_code, event_type
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (step_id + '-infrastructure-retry.db')}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"{step_id} Retry Lab",
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
                case_identifier=f"{step_id.upper()}-{case_id}",
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
                workflow_version="retry-test",
                status=AnalysisStatus.RUNNING,
                queue_task_id="stage-retry-dispatch",
                reference_build="GRCh38",
                configuration={},
                started_at=now,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.add(WorkflowStep(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id=step_id,
                step_order=4,
                status=StepStatus.RUNNING,
                attempt=1,
                started_at=now,
                last_heartbeat=now,
                input_artifacts=[],
                output_artifacts=[],
                metadata_json={"durable_marker": "preserve-me"},
            ))
            db.commit()

            _schedule_transient_step_retry(
                db,
                analysis_id=analysis_id,
                step_id=step_id,
                error_code=error_code,
                error_message="simulated filesystem/storage interruption",
                event_type=event_type,
                actor_id="infrastructure-retry-test",
                next_step=step_id,
            )

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == step_id,
            ))
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None
            assert step.status == StepStatus.RETRYING
            assert step.error_code == error_code
            assert step.metadata_json["next_step"] == step_id
            assert step.metadata_json["retry_policy"] == "bounded_transient_retry"
            assert step.metadata_json["durable_marker"] == "preserve-me"
            assert db.scalar(select(AuditEvent.id).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == event_type,
            )) is not None
    finally:
        engine.dispose()


def test_retry_exhaustion_blocks_analysis_and_preserves_resumable_partitions(tmp_path):
    from backend.app.infrastructure.queue.celery_app import _finalize_transient_retry_exhaustion

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'retry-exhaustion-review.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    now = datetime.now(timezone.utc)
    task_id = "retry-exhaustion-dispatch"
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Retry Exhaustion Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Retry Exhaustion Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"RETRY-{case_id}",
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
                workflow_version="retry-exhaustion-test",
                status=AnalysisStatus.RUNNING,
                queue_task_id=task_id,
                reference_build="GRCh38",
                configuration={},
                started_at=now,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.add(WorkflowStep(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id="annotate",
                step_order=8,
                status=StepStatus.RETRYING,
                attempt=3,
                started_at=now,
                last_heartbeat=now,
                input_artifacts=[],
                output_artifacts=[],
                metadata_json={"durable_marker": "preserve-me"},
            ))
            for ordinal, status in enumerate(("RUNNING", "READY")):
                db.add(AnalysisPartition(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id="annotate",
                    partition_key=f"partition-{ordinal}",
                    ordinal=ordinal,
                    record_start=ordinal * 100,
                    record_end=(ordinal + 1) * 100,
                    variant_count=100,
                    status=status,
                    lease_owner="worker-1" if status == "RUNNING" else None,
                    lease_token="lease-token" if status == "RUNNING" else None,
                    lease_expires_at=now if status == "RUNNING" else None,
                    started_at=now if status == "RUNNING" else None,
                    metadata_json={"partition_marker": ordinal},
                ))
            db.commit()

            finalized = _finalize_transient_retry_exhaustion(
                db,
                analysis_id,
                "reference provider remained unavailable after bounded retries",
                task_id=task_id,
                error_code="REFERENCE_PROVIDER_RETRY_EXHAUSTED",
                max_retries=3,
            )
            assert finalized is True

            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "annotate",
            ))
            partitions = db.scalars(select(AnalysisPartition).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "annotate",
            ).order_by(AnalysisPartition.ordinal)).all()
            event = db.scalar(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "ANALYSIS_RETRY_EXHAUSTED",
            ))

            assert analysis.status == AnalysisStatus.BLOCKED
            assert analysis.completed_at is None
            assert step.status == StepStatus.REQUIRES_REVIEW
            assert step.error_code == "REFERENCE_PROVIDER_RETRY_EXHAUSTED"
            assert step.metadata_json["durable_marker"] == "preserve-me"
            assert step.metadata_json["retry_exhausted"] is True
            assert step.metadata_json["automatic_fallback"] is False
            assert step.metadata_json["human_action_required"] is True
            assert step.metadata_json["next_step"] == "RESOURCE_OR_INFRASTRUCTURE_REMEDIATION"
            assert len(partitions) == 2
            assert all(partition.status == "READY" for partition in partitions)
            assert all(partition.lease_owner is None for partition in partitions)
            assert all(partition.lease_token is None for partition in partitions)
            assert all(partition.lease_expires_at is None for partition in partitions)
            assert all(partition.error_code == "REFERENCE_PROVIDER_RETRY_EXHAUSTED" for partition in partitions)
            assert all(partition.metadata_json["resume_requires_operator_action"] is True for partition in partitions)
            assert event is not None
            assert event.payload["disposition"] == "BLOCKED"
            assert event.payload["automatic_fallback"] is False
            assert event.payload["resume_requires_operator_action"] is True

            # A stale task generation cannot re-finalize or overwrite the review state.
            assert _finalize_transient_retry_exhaustion(
                db,
                analysis_id,
                "stale retry completion",
                task_id="stale-task-generation",
                error_code="STALE_RETRY",
                max_retries=3,
            ) is False
            assert db.get(Analysis, analysis_id).status == AnalysisStatus.BLOCKED
    finally:
        engine.dispose()
