from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import AnalysisPartition, WorkflowStep
from backend.app.partition_scheduler import PartitionScheduler, configure_partition
from backend.app.infrastructure.db.models import Analysis, Case, Organization, User


def make_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'m14.db'}")
    Base.metadata.create_all(engine)
    return engine


def seed_analysis(db):
    oid, uid, cid, aid = uuid4(), uuid4(), uuid4(), uuid4()
    db.add(Organization(id=oid, name="Org", external_identifier=None))
    db.add(User(id=uid, organization_id=oid, display_name="u", role="ADMIN", status="ACTIVE"))
    db.add(Case(id=cid, organization_id=oid, case_identifier="C1", status="READY", created_by=uid))
    db.add(Analysis(id=aid, case_id=cid, analysis_type="GERMLINE", workflow_id="w", workflow_version="1", status=AnalysisStatus.RUNNING, reference_build="GRCh38", configuration={}))
    db.commit()
    return aid


def test_scheduler_enforces_cpu_and_memory_capacity(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        aid = seed_analysis(db)
        for i in range(3):
            p = AnalysisPartition(id=uuid4(), analysis_id=aid, step_id="annotate", partition_key=str(i), ordinal=i, record_start=i*10, record_end=i*10+10, variant_count=10, status="READY", metadata_json={})
            configure_partition(p, "STANDARD")
            db.add(p)
        db.commit()
        scheduler = PartitionScheduler(db, cpu_capacity=2, memory_mb=2048, lease_seconds=60)
        a = scheduler.claim_next(aid, "annotate", "w1")
        b = scheduler.claim_next(aid, "annotate", "w2")
        c = scheduler.claim_next(aid, "annotate", "w3")
        assert a and b
        assert c is None
        cap = scheduler.capacity()
        assert cap["cpu_used"] == 2.0
        assert cap["memory_mb_used"] == 2048


def test_scheduler_lease_recovery_and_retry_limit(tmp_path):
    engine = make_db(tmp_path)
    with Session(engine) as db:
        aid = seed_analysis(db)
        p = AnalysisPartition(id=uuid4(), analysis_id=aid, step_id="annotate", partition_key="0", ordinal=0, record_start=0, record_end=10, variant_count=10, status="READY", metadata_json={})
        configure_partition(p, "STANDARD")
        db.add(p); db.commit()
        scheduler = PartitionScheduler(db, cpu_capacity=1, memory_mb=1024, lease_seconds=1)
        claimed = scheduler.claim_next(aid, "annotate", "w1")
        assert claimed and claimed.attempt == 1
        claimed.lease_expires_at = claimed.lease_expires_at - timedelta(seconds=10)
        db.commit()
        recovered = scheduler.claim_next(aid, "annotate", "w2")
        assert recovered and recovered.lease_owner == "w2" and recovered.attempt == 2
        scheduler.fail(recovered.id, "w2", recovered.lease_token, error_code="TEMP", error_message="retry")
        assert db.get(AnalysisPartition, recovered.id).status == "READY"


def test_worker_recovery_requeues_annotation_partition_without_reopening_completed_work(tmp_path):
    """A recovered stage must be schedulable again while successful partitions stay terminal."""
    from backend.app.workflows.variant import recover_interrupted_execution

    engine = make_db(tmp_path)
    with Session(engine) as db:
        aid = seed_analysis(db)
        step = WorkflowStep(
            id=uuid4(),
            analysis_id=aid,
            step_id="annotate",
            step_order=3,
            status=StepStatus.RUNNING,
            attempt=2,
            input_artifacts=["normalized-vcf"],
            output_artifacts=[],
            metadata_json={"checkpoint": "batch-4", "batches": {"0:10": {"status": "SUCCEEDED"}}},
        )
        interrupted = AnalysisPartition(
            id=uuid4(), analysis_id=aid, step_id="annotate",
            partition_key="10:20", ordinal=1, record_start=10, record_end=20,
            variant_count=10, status="RUNNING", metadata_json={"resource_id": "resource-v1"},
            resource_class="STANDARD", cpu_request=1.0, memory_mb=1024,
            attempt=1, lease_owner="lost-worker", lease_token="stale-token",
            lease_expires_at=None,
        )
        completed = AnalysisPartition(
            id=uuid4(), analysis_id=aid, step_id="annotate",
            partition_key="0:10", ordinal=0, record_start=0, record_end=10,
            variant_count=10, status="SUCCEEDED", metadata_json={"resource_id": "resource-v1"},
            resource_class="STANDARD", cpu_request=1.0, memory_mb=1024,
            attempt=1,
        )
        db.add_all([step, interrupted, completed])
        db.commit()

        assert recover_interrupted_execution(db, aid) is True
        db.refresh(step)
        db.refresh(interrupted)
        db.refresh(completed)

        assert step.status == StepStatus.RETRYING
        assert step.metadata_json["checkpoint"] == "batch-4"
        assert step.metadata_json["batches"]["0:10"]["status"] == "SUCCEEDED"
        assert interrupted.status == "READY"
        assert interrupted.lease_owner is None
        assert interrupted.lease_token is None
        assert interrupted.lease_expires_at is None
        assert completed.status == "SUCCEEDED"

        scheduler = PartitionScheduler(db, cpu_capacity=1, memory_mb=1024, lease_seconds=60)
        reclaimed = scheduler.claim_next(aid, "annotate", "retry-worker")
        assert reclaimed is not None
        assert reclaimed.id == interrupted.id
        assert reclaimed.attempt == 2
        assert reclaimed.lease_owner == "retry-worker"
        scheduler.succeed(reclaimed.id, "retry-worker", reclaimed.lease_token, metadata={"resource_id": "resource-v1"})

        # A second scheduling pass sees no READY partition. The already-completed
        # batch is not reopened or leased a second time.
        assert scheduler.claim_next(aid, "annotate", "third-worker") is None
        db.refresh(completed)
        assert completed.status == "SUCCEEDED"
        assert completed.attempt == 1


def test_save_batch_checkpoint_can_stage_without_commit():
    """Result checkpoints can share the partition-fenced transaction."""
    from unittest.mock import Mock

    from backend.app.workflows.variant import _save_batch_checkpoint

    db = Mock()
    step = Mock()
    step.metadata_json = {}
    step.last_heartbeat = None
    step.updated_at = None

    _save_batch_checkpoint(
        db,
        step,
        0,
        10,
        status="SUCCEEDED",
        metadata={"provider": "GeneBe"},
        commit=False,
    )

    db.add.assert_called_once_with(step)
    db.commit.assert_not_called()
    assert step.metadata_json["batches"]["0:10"]["status"] == "SUCCEEDED"


def test_transient_workflow_error_supports_capacity_specific_retry_policy():
    from backend.app.workflows.variant import TransientWorkflowError

    error = TransientWorkflowError(
        "No resource capacity available for the next annotation partition",
        countdown=60,
        max_retries=20,
        error_code="ANNOTATION_CAPACITY_RETRY_EXHAUSTED",
    )

    assert error.countdown == 60
    assert error.max_retries == 20
    assert error.error_code == "ANNOTATION_CAPACITY_RETRY_EXHAUSTED"
