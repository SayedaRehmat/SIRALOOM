"""Test-only Celery app for crashing the real SIRALOOM analysis task mid-stage.

The outer task runs in a real prefork worker. It calls the production
run_analysis_task with broker delivery metadata preserved. The workflow
function is replaced only inside this worker process so the first invocation
commits an interrupted-stage checkpoint and exits abruptly.
"""
import json
import os
from uuid import UUID, uuid4

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
                        id=uuid4(),
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
        # The test replaces the scientific stage body after verifying that the
        # production wrapper recovered its checkpoint. Do not run external
        # annotation providers in this worker-process fault-injection test.
        return None

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



@celery_app.task(
    bind=True,
    name="siraloom.test_vcf_normalization_worker_loss",
    acks_late=True,
    reject_on_worker_lost=True,
)
def vcf_normalization_worker_loss(
    self,
    analysis_id: str,
    marker_prefix: str,
    source_vcf: str,
    reference_fasta: str,
    first_output: str,
    replay_output: str,
    artifact_root: str,
    bcftools_executable: str,
):
    """Run real BCFtools normalization, kill its prefork child, then replay.

    The production analysis-task wrapper owns dispatch fencing, PostgreSQL
    execution locking, Celery redelivery recovery, and the workflow invocation.
    Only the normalization-stage body is instrumented so the test can stop at
    the durable artifact/checkpoint boundary without invoking downstream
    annotation providers.
    """
    import gzip
    import hashlib
    import importlib
    import subprocess
    from datetime import datetime, timezone
    from pathlib import Path
    from uuid import UUID, uuid4, uuid5

    from redis import Redis
    from sqlalchemy import func, select

    from backend.app.domain.enums import StepStatus
    from backend.app.infrastructure.artifacts.store import ArtifactStore
    from backend.app.infrastructure.db.models import (
        Analysis,
        Artifact,
        Case,
        WorkflowStep,
    )
    from backend.app.infrastructure.db.session import SessionLocal
    from backend.app.workflows.variant import _put_idempotent_stage_artifact

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    analysis_uuid = UUID(analysis_id)
    marker = lambda suffix: f"{marker_prefix}:{suffix}"
    artifact_id = uuid5(
        analysis_uuid, "siraloom:normalization:normalized-vcf:v6"
    )
    store = ArtifactStore(artifact_root)
    production_queue = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    workflow_module = importlib.import_module("backend.app.workflows.variant")
    original_workflow = workflow_module.run_variant_analysis

    version_result = subprocess.run(
        [bcftools_executable, "--version"],
        check=True,
        capture_output=True,
        text=True,
    )
    tool_version = version_result.stdout.splitlines()[0]
    if tool_version != "bcftools 1.24":
        raise RuntimeError(f"Unexpected BCFtools version: {tool_version}")

    def normalize_to(output_path: str) -> list[str]:
        command = [
            bcftools_executable,
            "norm",
            "--no-version",
            "-f",
            reference_fasta,
            "-Oz",
            "-o",
            output_path,
            source_vcf,
        ]
        subprocess.run(command, check=True, capture_output=True, text=True)
        return command

    def crashable_workflow(workflow_analysis_id):
        assert UUID(str(workflow_analysis_id)) == analysis_uuid
        if redis.get(marker("checkpoint")) is None:
            command = normalize_to(first_output)
            with SessionLocal() as db:
                analysis = db.get(Analysis, analysis_uuid)
                if analysis is None:
                    raise RuntimeError("Normalization analysis disappeared.")
                case = db.get(Case, analysis.case_id)
                if case is None:
                    raise RuntimeError("Normalization case disappeared.")
                metadata = {
                    "reference_package_checksum": "a" * 64,
                    "normalization_tool_version": tool_version,
                    "normalization_command": command,
                    "normalization_version": "6.0",
                }
                artifact = _put_idempotent_stage_artifact(
                    store,
                    artifact_id=artifact_id,
                    db=db,
                    case_id=analysis.case_id,
                    analysis_id=analysis_uuid,
                    source_path=Path(first_output),
                    filename="normalized.vcf.gz",
                    artifact_type="NORMALIZED_VCF",
                    media_type="application/gzip",
                    genome_build=analysis.reference_build,
                    metadata=metadata,
                )
                now = datetime.now(timezone.utc)
                db.add(
                    WorkflowStep(
                        id=__import__("uuid").uuid4(),
                        analysis_id=analysis_uuid,
                        step_id="normalize",
                        step_order=2,
                        status=StepStatus.RUNNING,
                        attempt=1,
                        started_at=now,
                        last_heartbeat=now,
                        input_artifacts=["source-vcf"],
                        output_artifacts=[str(artifact.id)],
                        metadata_json={
                            "next_step": "normalize",
                            "checkpoint": "normalized-artifact-committed",
                            "normalized_artifact_id": str(artifact.id),
                        },
                    )
                )
                db.commit()
                durable_sha256 = artifact.sha256

            # The artifact bytes, artifact row, and RUNNING normalization
            # checkpoint are committed before the prefork child is terminated.
            redis.set(
                marker("checkpoint"),
                json.dumps({"artifact_id": str(artifact_id), "sha256": durable_sha256}),
                ex=300,
            )
            os._exit(73)

        # This path is reached only when the broker redelivers the task to a
        # replacement prefork child. The production wrapper has already run
        # recover_interrupted_execution() before invoking this workflow body.
        replay_command = normalize_to(replay_output)
        with SessionLocal() as db:
            step = db.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_uuid,
                    WorkflowStep.step_id == "normalize",
                )
            )
            if step is None or step.status != StepStatus.RETRYING:
                raise AssertionError("Normalization checkpoint was not recovered.")
            metadata = {
                "reference_package_checksum": "a" * 64,
                "normalization_tool_version": tool_version,
                "normalization_command": replay_command,
                "normalization_version": "6.0",
            }
            replay_artifact = _put_idempotent_stage_artifact(
                store,
                artifact_id=artifact_id,
                db=db,
                case_id=db.get(Analysis, analysis_uuid).case_id,
                analysis_id=analysis_uuid,
                source_path=Path(replay_output),
                filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF",
                media_type="application/gzip",
                genome_build="GRCh38",
                metadata=metadata,
            )
            persisted_bytes = store.read_bytes(replay_artifact.storage_uri)
            replay_bytes = Path(replay_output).read_bytes()
            if persisted_bytes != replay_bytes:
                raise AssertionError("Replayed normalized bytes differ from durable artifact.")
            if hashlib.sha256(persisted_bytes).hexdigest() != replay_artifact.sha256:
                raise AssertionError("Durable normalized artifact checksum mismatch.")

            normalized_records = [
                line.split("\t")
                for line in gzip.decompress(replay_bytes).decode("utf-8").splitlines()
                if line and not line.startswith("#")
            ]
            if len(normalized_records) != 1 or normalized_records[0][1] != "1":
                raise AssertionError(
                    f"Expected one left-normalized indel at position 1; got {normalized_records!r}"
                )

            artifact_count = db.scalar(
                select(func.count(Artifact.id)).where(
                    Artifact.analysis_id == analysis_uuid,
                    Artifact.artifact_type == "NORMALIZED_VCF",
                )
            )
            if artifact_count != 1:
                raise AssertionError(f"Expected one normalized artifact, found {artifact_count}.")

            step.status = StepStatus.SUCCEEDED
            step.error_code = None
            step.error_message = None
            step.output_artifacts = [str(replay_artifact.id)]
            step.metadata_json = {
                **dict(step.metadata_json or {}),
                "replay_verified": True,
                "normalized_artifact_sha256": replay_artifact.sha256,
            }
            db.add(step)
            db.commit()

            workflow_result = {
                "step_status": str(step.status),
                "step_error_code": step.error_code,
                "recovery": step.metadata_json.get("recovery"),
                "checkpoint": step.metadata_json.get("checkpoint"),
                "artifact_id": str(replay_artifact.id),
                "artifact_sha256": replay_artifact.sha256,
                "artifact_count": artifact_count,
                "replayed_bytes_match": persisted_bytes == replay_bytes,
                "normalized_record": normalized_records[0],
                "normalization_tool_version": tool_version,
            }

        redis.set(marker("workflow"), json.dumps(workflow_result), ex=300)
        return None

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
