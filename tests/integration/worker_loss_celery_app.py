"""Test-only Celery app for crashing the real SIRALOOM analysis task mid-stage.

The outer task runs in a real prefork worker. It calls the production
run_analysis_task with broker delivery metadata preserved. The workflow
function is replaced only inside this worker process so the first invocation
commits an interrupted-stage checkpoint and exits abruptly.
"""
import json
import os
from uuid import UUID

from celery import Celery
from redis import Redis

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


@celery_app.task(
    bind=True,
    name="siraloom.test_worker_loss_after_checkpoint",
    acks_late=True,
    reject_on_worker_lost=True,
)
def worker_loss_after_checkpoint(self, analysis_id: str, marker_prefix: str):
    import importlib

    from backend.app.domain.enums import StepStatus
    from backend.app.infrastructure.db.models import AnalysisPartition, WorkflowStep
    from backend.app.infrastructure.db.session import SessionLocal

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    analysis_uuid = UUID(analysis_id)
    marker = lambda suffix: f"{marker_prefix}:{suffix}"
    production_queue = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    workflow_module = importlib.import_module("backend.app.workflows.variant")
    original_workflow = workflow_module.run_variant_analysis

    def crashable_workflow(workflow_analysis_id):
        assert UUID(str(workflow_analysis_id)) == analysis_uuid
        if redis.get(marker("checkpoint")) is None:
            # The production task has already claimed the analysis and committed
            # RUNNING. Commit a real stage/partition checkpoint, then kill this
            # prefork child without running either task's Python finalizers.
            with SessionLocal() as db:
                db.add_all([
                    WorkflowStep(
                        id=__import__("uuid").uuid4(),
                        analysis_id=analysis_uuid,
                        step_id="annotate",
                        step_order=3,
                        status=StepStatus.RUNNING,
                        attempt=1,
                        input_artifacts=["normalized-vcf"],
                        output_artifacts=[],
                        metadata_json={
                            "next_step": "annotate",
                            "checkpoint": "batch-4",
                        },
                    ),
                    AnalysisPartition(
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
                    ),
                ])
                db.commit()
            redis.set(marker("checkpoint"), "committed", ex=300)
            os._exit(73)

        # This executes only if the actual production task sees redelivery,
        # reacquires the execution fence, and recovers interrupted state before
        # calling run_variant_analysis again.
        with SessionLocal() as db:
            step = db.query(WorkflowStep).filter(
                WorkflowStep.analysis_id == analysis_uuid,
                WorkflowStep.step_id == "annotate",
            ).one()
            partition = db.query(AnalysisPartition).filter(
                AnalysisPartition.analysis_id == analysis_uuid,
                AnalysisPartition.partition_key == "batch-4",
            ).one()
            workflow_result = {
                "step_status": str(step.status),
                "step_error_code": step.error_code,
                "checkpoint": step.metadata_json.get("checkpoint"),
                "partition_status": partition.status,
                "partition_lease_owner": partition.lease_owner,
                "partition_error_code": partition.error_code,
            }
        redis.set(marker("workflow"), json.dumps(workflow_result), ex=300)
        return original_workflow(workflow_analysis_id)

    workflow_module.run_variant_analysis = crashable_workflow
    production_task = production_queue.run_analysis_task
    delivery = dict(self.request.delivery_info or {})
    production_task.push_request(
        id=self.request.id,
        retries=0,
        delivery_info=delivery,
    )
    try:
        production_result = production_task.run(analysis_id)
        workflow_payload = redis.get(marker("workflow"))
        result = {
            "production_result": production_result,
            "delivery_redelivered": bool(delivery.get("redelivered")),
            "workflow_result": json.loads(workflow_payload) if workflow_payload else None,
        }
        redis.set(marker("result"), json.dumps(result), ex=300)
        return result
    finally:
        production_task.pop_request()
        workflow_module.run_variant_analysis = original_workflow
