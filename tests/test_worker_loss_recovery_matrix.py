from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    Case,
    Organization,
    User,
    WorkflowStep,
)
from backend.app.workflows.variant import recover_interrupted_execution


RECOVERABLE_STAGE_IDS = [
    "validate_input",
    "normalize",
    "annotate",
    "population",
    "build_evidence",
    "acmg_assessment",
    "review",
    "reportability",
    "report",
    "export_provenance",
]


def test_worker_loss_recovery_matrix_resets_every_stage_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'worker-loss-matrix.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Worker Recovery Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Worker Recovery Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"RECOVERY-{case_id}",
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
                workflow_version="recovery-test",
                status=AnalysisStatus.RUNNING,
                queue_task_id="durable-dispatch-id",
                reference_build="GRCh38",
                configuration={},
                started_at=now,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.flush()

            for order, stage_id in enumerate(RECOVERABLE_STAGE_IDS, start=1):
                db.add(WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=stage_id,
                    step_order=order,
                    status=StepStatus.RUNNING,
                    attempt=2,
                    started_at=now,
                    last_heartbeat=now,
                    input_artifacts=[],
                    output_artifacts=[],
                    metadata_json={"stage_marker": stage_id},
                ))
            db.add(AnalysisPartition(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id="population",
                partition_key="0:100",
                ordinal=0,
                record_start=0,
                record_end=100,
                variant_count=100,
                status="RUNNING",
                metadata_json={"stage_marker": "population"},
                resource_class="STANDARD",
                cpu_request=1.0,
                memory_mb=1024,
                attempt=2,
                lease_owner="worker-that-died",
                lease_token="expired-lease-token",
                lease_expires_at=now,
                started_at=now,
            ))
            db.commit()

            assert recover_interrupted_execution(db, analysis_id) is True
            recovered_steps = db.scalars(
                select(WorkflowStep)
                .where(WorkflowStep.analysis_id == analysis_id)
                .order_by(WorkflowStep.step_order)
            ).all()
            assert [step.step_id for step in recovered_steps] == RECOVERABLE_STAGE_IDS
            for step in recovered_steps:
                assert step.status == StepStatus.RETRYING
                assert step.error_code == "WORKER_INTERRUPTED"
                assert step.metadata_json["next_step"] == step.step_id
                assert step.metadata_json["recovery"] == "CELERY_REDELIVERY"

            partition = db.scalar(select(AnalysisPartition).where(
                AnalysisPartition.analysis_id == analysis_id,
                AnalysisPartition.step_id == "population",
            ))
            assert partition.status == "READY"
            assert partition.lease_owner is None
            assert partition.lease_token is None
            assert partition.lease_expires_at is None
            assert partition.error_code == "WORKER_INTERRUPTED"
            assert db.get(Analysis, analysis_id).status == AnalysisStatus.RUNNING

            # A repeated redelivery must not emit another recovery transition
            # or rewrite the already recovered stage/partition state.
            assert recover_interrupted_execution(db, analysis_id) is False
    finally:
        engine.dispose()
