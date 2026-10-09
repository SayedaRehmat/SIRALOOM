"""Test-only Celery app for exercising real worker-process loss in PostgreSQL CI.

Loaded by a separate prefork worker process. The first delivery commits an
in-progress workflow checkpoint and exits the child process abruptly; a broker
redelivery must invoke the production execution claim and recovery routines.
"""
import os
from uuid import UUID

from celery import Celery
from redis import Redis
from sqlalchemy import text

from backend.app.config import settings

celery_app = Celery(
    "siraloom_worker_loss_integration",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 30},
    result_backend_transport_options={"visibility_timeout": 30},
)

@celery_app.task(bind=True, name="siraloom.test_worker_loss_after_checkpoint", acks_late=True)
def worker_loss_after_checkpoint(self, analysis_id: str, marker_prefix: str):
    import importlib
    import time

    from backend.app.domain.enums import StepStatus
    from backend.app.infrastructure.db.models import Analysis, AnalysisPartition, WorkflowStep
    from backend.app.infrastructure.db.session import SessionLocal, engine
    from backend.app.workflows.variant import recover_interrupted_execution

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    analysis_uuid = UUID(analysis_id)
    delivery = self.request.delivery_info or {}
    redelivered = bool(delivery.get("redelivered"))
    marker_key = f"{marker_prefix}:attempts"
    attempt = redis.incr(marker_key)
    redis.expire(marker_key, 300)

    production_queue = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    lock_connection = engine.connect() if engine.dialect.name == "postgresql" else None
    claim_db = SessionLocal()
    try:
        claim_kwargs = {"lock_connection": lock_connection} if lock_connection else {}
        claimed = production_queue._claim_analysis_execution(
            claim_db,
            analysis_uuid,
            task_id=self.request.id,
            allow_running=redelivered,
            **claim_kwargs,
        )
        if not claimed:
            result = {
                "outcome": "claim_rejected",
                "redelivered": redelivered,
                "attempt": attempt,
            }
            redis.set(f"{marker_prefix}:result", __import__("json").dumps(result), ex=300)
            return result

        if not redelivered:
            # Persist a checkpoint exactly as a worker would before entering a
            # long-running annotation batch, then die without executing finally.
            with SessionLocal() as db:
                step = WorkflowStep(
                    id=__import__("uuid").uuid4(),
                    analysis_id=analysis_uuid,
                    step_id="annotate",
                    step_order=3,
                    status=StepStatus.RUNNING,
                    attempt=1,
                    input_artifacts=["normalized-vcf"],
                    output_artifacts=[],
                    metadata_json={"next_step": "annotate", "checkpoint": "batch-4"},
                )
                partition = AnalysisPartition(
                    id=__import__("uuid").uuid4(),
                    analysis_id=analysis_uuid,
                    step_id="annotate",
                    partition_key="batch-4",
                    ordinal=4,
                    record_start=400,
                    record_end=500,
                    variant_count=100,
                    status="RUNNING",
                    metadata_json={"variant_ids": ["unfinished-variant"]},
                    resource_class="STANDARD",
                    cpu_request=1.0,
                    memory_mb=1024,
                    attempt=1,
                    lease_owner="crashed-worker",
                    lease_expires_at=None,
                )
                db.add_all([step, partition])
                db.commit()
            redis.set(f"{marker_prefix}:checkpoint", "committed", ex=300)
            # No Python cleanup runs; the OS closes this process's PostgreSQL
            # connection, releasing the session-scoped execution advisory lock.
            os._exit(73)

        # Do not paper over missing broker metadata: this test specifically
        # validates that real redelivery is marked as such by the configured
        # Celery/Redis transport.
        if not redelivered:
            result = {"outcome": "redelivery_flag_missing", "attempt": attempt}
            redis.set(f"{marker_prefix}:result", __import__("json").dumps(result), ex=300)
            return result

        with SessionLocal() as recovery_db:
            recovered = recover_interrupted_execution(recovery_db, analysis_uuid)

        with SessionLocal() as verify_db:
            analysis = verify_db.get(Analysis, analysis_uuid)
            step = verify_db.query(WorkflowStep).filter(
                WorkflowStep.analysis_id == analysis_uuid,
                WorkflowStep.step_id == "annotate",
            ).one()
            partition = verify_db.query(AnalysisPartition).filter(
                AnalysisPartition.analysis_id == analysis_uuid,
                AnalysisPartition.partition_key == "batch-4",
            ).one()
            result = {
                "outcome": "recovered",
                "redelivered": redelivered,
                "attempt": attempt,
                "recovered": recovered,
                "analysis_status": str(analysis.status),
                "step_status": str(step.status),
                "step_error_code": step.error_code,
                "checkpoint": step.metadata_json.get("checkpoint"),
                "partition_status": partition.status,
                "partition_lease_owner": partition.lease_owner,
                "partition_error_code": partition.error_code,
            }
        redis.set(f"{marker_prefix}:result", __import__("json").dumps(result), ex=300)
        return result
    finally:
        claim_db.close()
        if lock_connection is not None:
            lock_key = lock_connection.info.pop(
                "siraloom_analysis_execution_lock_key", None
            )
            try:
                if lock_key is not None:
                    lock_connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": lock_key},
                    ).scalar_one()
                    lock_connection.commit()
            except Exception:
                lock_connection.invalidate()
            finally:
                lock_connection.close()
