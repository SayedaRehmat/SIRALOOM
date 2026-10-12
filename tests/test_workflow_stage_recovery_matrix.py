"""Stage-by-stage durable recovery contract for the variant workflow.

These tests exercise the production recover_interrupted_execution() recovery
boundary for every declared workflow step. They deliberately do not claim that
the scientific body of each step has been re-executed: stage-body fault
injection and provider/storage failure tests remain a separate required layer.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    AnalysisPartition,
    AuditEvent,
    Case,
    Organization,
    User,
    WorkflowStep,
)
from backend.app.workflows.variant import WORKFLOW_STEPS, recover_interrupted_execution


@pytest.mark.parametrize(
    "interrupted_step",
    [step_id for step_id, _order in WORKFLOW_STEPS],
)
def test_each_workflow_step_recovers_durably_without_reopening_completed_work(
    tmp_path, interrupted_step
):
    """A worker loss at any declared step must recover that step and its leases.

    Invariants:
    - previously successful workflow steps and partitions remain successful;
    - the interrupted step becomes RETRYING, preserving its durable checkpoint;
    - later steps remain pending and cannot be mistaken for completed work;
    - stale leases are cleared and the interrupted partition becomes schedulable;
    - repeated recovery is a no-op and writes no duplicate recovery audit event.
    """
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / (interrupted_step + '.db')}")
    Base.metadata.create_all(engine)

    organization_id, user_id, case_id, analysis_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    interrupted_order = dict(WORKFLOW_STEPS)[interrupted_step]
    checkpoint = {
        "next_step": interrupted_step,
        "fixture_checkpoint": f"durable:{interrupted_step}",
        "batches": {"0:10": {"status": "SUCCEEDED", "attempt": 1}},
    }
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"Recovery {interrupted_step}",
                external_identifier=str(organization_id),
            ))
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Recovery Test",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"RECOVERY-{interrupted_step}-{case_id}",
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
                workflow_version="recovery-matrix-test",
                status=AnalysisStatus.RUNNING,
                queue_task_id=None,
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(timezone.utc),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))

            for step_id, order in WORKFLOW_STEPS:
                status = (
                    StepStatus.SUCCEEDED if order < interrupted_order
                    else StepStatus.RUNNING if step_id == interrupted_step
                    else StepStatus.PENDING
                )
                db.add(WorkflowStep(
                    id=uuid4(),
                    analysis_id=analysis_id,
                    step_id=step_id,
                    step_order=order,
                    status=status,
                    attempt=2 if step_id == interrupted_step else 1 if order < interrupted_order else 0,
                    input_artifacts=[],
                    output_artifacts=[],
                    metadata_json=dict(checkpoint) if step_id == interrupted_step else {},
                ))

            # Include one already-completed partition and one partition leased
            # by the worker that has now disappeared. Partition state is kept
            # independent from the step checkpoint.
            completed_partition = AnalysisPartition(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id=interrupted_step,
                partition_key="0:10",
                ordinal=0,
                record_start=0,
                record_end=10,
                variant_count=10,
                status="SUCCEEDED",
                metadata_json={"checkpoint": "completed"},
                resource_class="STANDARD",
                cpu_request=1.0,
                memory_mb=1024,
                attempt=1,
            )
            interrupted_partition = AnalysisPartition(
                id=uuid4(),
                analysis_id=analysis_id,
                step_id=interrupted_step,
                partition_key="10:20",
                ordinal=1,
                record_start=10,
                record_end=20,
                variant_count=10,
                status="RUNNING",
                metadata_json={"checkpoint": "in-flight"},
                resource_class="STANDARD",
                cpu_request=1.0,
                memory_mb=1024,
                attempt=2,
                lease_owner="lost-worker",
                lease_token="stale-lease-token",
                lease_expires_at=None,
            )
            db.add_all([completed_partition, interrupted_partition])
            db.commit()

            assert recover_interrupted_execution(db, analysis_id) is True

            interrupted = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == interrupted_step,
            ))
            assert interrupted.status == StepStatus.RETRYING
            assert interrupted.error_code == "WORKER_INTERRUPTED"
            assert interrupted.metadata_json["fixture_checkpoint"] == f"durable:{interrupted_step}"
            assert interrupted.metadata_json["batches"]["0:10"]["status"] == "SUCCEEDED"
            assert interrupted.metadata_json["next_step"] == interrupted_step

            for step_id, order in WORKFLOW_STEPS:
                step = db.scalar(select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_id,
                    WorkflowStep.step_id == step_id,
                ))
                if order < interrupted_order:
                    assert step.status == StepStatus.SUCCEEDED, step_id
                elif step_id == interrupted_step:
                    assert step.status == StepStatus.RETRYING, step_id
                else:
                    assert step.status == StepStatus.PENDING, step_id

            db.refresh(completed_partition)
            db.refresh(interrupted_partition)
            assert completed_partition.status == "SUCCEEDED"
            assert completed_partition.attempt == 1
            assert interrupted_partition.status == "READY"
            assert interrupted_partition.lease_owner is None
            assert interrupted_partition.lease_token is None
            assert interrupted_partition.lease_expires_at is None
            assert interrupted_partition.error_code == "WORKER_INTERRUPTED"

            analysis = db.get(Analysis, analysis_id)
            assert analysis.status == AnalysisStatus.RUNNING
            assert analysis.completed_at is None

            recovery_audits = db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
            ))
            assert recovery_audits == 1

            # Redelivery/recovery racing after the first commit must be
            # idempotent: no RUNNING stage/partition remains to recover.
            assert recover_interrupted_execution(db, analysis_id) is False
            assert db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
            )) == 1
    finally:
        engine.dispose()
