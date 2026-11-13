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
    """Crash after committing production-normalizer VCF+CSI artifacts, then replay.

    The real production normalization wrapper validates the pinned BCFtools
    toolchain, reference identity, source-to-child mapping, BGZF output and CSI
    index. The test-only workflow hook stops only after both artifacts and the
    RUNNING checkpoint are durably committed.
    """
    import gzip
    import hashlib
    import importlib
    from datetime import datetime, timezone
    from pathlib import Path
    from uuid import UUID, uuid4, uuid5

    from redis import Redis
    from sqlalchemy import func, select

    from backend.app.domain.enums import StepStatus
    from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools
    from backend.app.infrastructure.artifacts.store import ArtifactStore
    from backend.app.infrastructure.db.models import (
        Analysis,
        Artifact,
        WorkflowStep,
    )
    from backend.app.infrastructure.db.session import SessionLocal
    from backend.app.workflows.variant import _put_idempotent_stage_artifact

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    analysis_uuid = UUID(analysis_id)
    marker = lambda suffix: f"{marker_prefix}:{suffix}"
    normalized_artifact_id = uuid5(
        analysis_uuid, "siraloom:normalization:normalized-vcf:v6"
    )
    index_artifact_id = uuid5(
        analysis_uuid, "siraloom:normalization:normalized-vcf-index:v6"
    )
    store = ArtifactStore(artifact_root)
    production_queue = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    workflow_module = importlib.import_module("backend.app.workflows.variant")
    original_workflow = workflow_module.run_variant_analysis

    def normalize_to(output_path: str) -> dict:
        return normalize_vcf_with_bcftools(
            Path(source_vcf),
            Path(output_path),
            reference_fasta=Path(reference_fasta),
            expected_bcftools_version=settings.bcftools_version,
            source_only_format_fields=[],
            bcftools_executable=bcftools_executable,
        )

    def artifact_metadata(stats: dict, output_path: str) -> dict:
        reference_artifacts = stats["reference_identity"]["artifacts"]
        stable_command = stats["command"].replace(output_path, "<NORMALIZED_VCF>")
        return {
            "normalization_version": "6.0",
            "source_record_mapping_tag": stats["source_record_mapping_tag"],
            "source_record_mapping_policy": stats["source_record_mapping_policy"],
            "multiallelic_overlap_policy": stats["multiallelic_overlap_policy"],
            "source_genotype_provenance_contract": "SIRALOOM_SOURCE_GT_AND_SOURCE_ALT_COUNT_V1",
            "source_record_count": stats["source_child_reconciliation"]["source_records"],
            "record_count": stats["source_child_reconciliation"]["source_records"],
            "reference_source": "TEST_FIXTURE_FASTA_AND_FAI",
            "reference_fasta_sha256": reference_artifacts["fasta"]["sha256"],
            "reference_fai_sha256": reference_artifacts["fai"]["sha256"],
            "normalization_tool": stats["tool"],
            "normalization_tool_version": stats["tool_version"],
            "normalization_expected_tool_version": stats["expected_tool_version"],
            "normalization_command": stable_command,
            "source_only_format_fields": stats["source_only_format_fields"],
            "source_only_format_fields_policy": stats["source_only_format_fields_policy"],
            "compression": stats["compression"],
            "index": stats["index"],
            "index_validation": stats["index_validation"],
            "source_child_reconciliation": stats["source_child_reconciliation"],
        }

    def persist_normalized_pair(db, analysis, stats: dict, output_path: str):
        normalized_path = Path(output_path)
        index_path = Path(stats["index_path"])
        metadata = artifact_metadata(stats, output_path)
        normalized_artifact = _put_idempotent_stage_artifact(
            store,
            artifact_id=normalized_artifact_id,
            db=db,
            case_id=analysis.case_id,
            analysis_id=analysis_uuid,
            source_path=normalized_path,
            filename="normalized.vcf.gz",
            artifact_type="NORMALIZED_VCF",
            media_type="application/gzip",
            genome_build=analysis.reference_build,
            metadata=metadata,
        )
        index_artifact = _put_idempotent_stage_artifact(
            store,
            artifact_id=index_artifact_id,
            db=db,
            case_id=analysis.case_id,
            analysis_id=analysis_uuid,
            source_path=index_path,
            filename="normalized.vcf.gz.csi",
            artifact_type="VCF_INDEX",
            media_type="application/octet-stream",
            genome_build=analysis.reference_build,
            paired_artifact_id=normalized_artifact.id,
            metadata={
                "index_type": stats["index"],
                "indexed_artifact_id": str(normalized_artifact.id),
                "normalization_tool": stats["tool"],
                "normalization_tool_version": stats["tool_version"],
                "normalization_version": "6.0",
                "reference_fasta_sha256": metadata["reference_fasta_sha256"],
                "reference_fai_sha256": metadata["reference_fai_sha256"],
                "index_validation": stats["index_validation"],
            },
        )
        normalized_artifact.paired_artifact_id = index_artifact.id
        db.add(normalized_artifact)
        db.add(index_artifact)
        return normalized_artifact, index_artifact

    def crashable_workflow(workflow_analysis_id):
        assert UUID(str(workflow_analysis_id)) == analysis_uuid
        if redis.get(marker("checkpoint")) is None:
            first_stats = normalize_to(first_output)
            with SessionLocal() as db:
                analysis = db.get(Analysis, analysis_uuid)
                if analysis is None:
                    raise RuntimeError("Normalization analysis disappeared.")
                normalized_artifact, index_artifact = persist_normalized_pair(
                    db, analysis, first_stats, first_output
                )
                now = datetime.now(timezone.utc)
                db.add(
                    WorkflowStep(
                        id=uuid4(),
                        analysis_id=analysis_uuid,
                        step_id="normalize",
                        step_order=2,
                        status=StepStatus.RUNNING,
                        attempt=1,
                        started_at=now,
                        last_heartbeat=now,
                        input_artifacts=["source-vcf"],
                        output_artifacts=[
                            str(normalized_artifact.id),
                            str(index_artifact.id),
                        ],
                        metadata_json={
                            "next_step": "normalize",
                            "checkpoint": "normalized-artifact-pair-committed",
                            "normalized_artifact_id": str(normalized_artifact.id),
                            "index_artifact_id": str(index_artifact.id),
                        },
                    )
                )
                db.commit()
                durable = {
                    "normalized_artifact_id": str(normalized_artifact.id),
                    "normalized_sha256": normalized_artifact.sha256,
                    "index_artifact_id": str(index_artifact.id),
                    "index_sha256": index_artifact.sha256,
                }

            # Both artifact rows/objects and the RUNNING checkpoint are durable
            # before this prefork child exits without task acknowledgment.
            redis.set(marker("checkpoint"), json.dumps(durable), ex=300)
            os._exit(73)

        # This path is reached only after Celery redelivery and production
        # recover_interrupted_execution() have reset the interrupted step.
        replay_stats = normalize_to(replay_output)
        with SessionLocal() as db:
            step = db.scalar(
                select(WorkflowStep).where(
                    WorkflowStep.analysis_id == analysis_uuid,
                    WorkflowStep.step_id == "normalize",
                )
            )
            if step is None or step.status != StepStatus.RETRYING:
                raise AssertionError("Normalization checkpoint was not recovered.")
            analysis = db.get(Analysis, analysis_uuid)
            if analysis is None:
                raise RuntimeError("Normalization analysis disappeared during replay.")
            normalized_artifact, index_artifact = persist_normalized_pair(
                db, analysis, replay_stats, replay_output
            )

            persisted_vcf = store.read_bytes(normalized_artifact.storage_uri)
            replay_vcf = Path(replay_output).read_bytes()
            persisted_index = store.read_bytes(index_artifact.storage_uri)
            replay_index = Path(replay_stats["index_path"]).read_bytes()
            if persisted_vcf != replay_vcf:
                raise AssertionError("Replayed normalized VCF bytes differ from durable artifact.")
            if persisted_index != replay_index:
                raise AssertionError("Replayed CSI bytes differ from durable index artifact.")
            if hashlib.sha256(persisted_vcf).hexdigest() != normalized_artifact.sha256:
                raise AssertionError("Durable normalized VCF checksum mismatch.")
            if hashlib.sha256(persisted_index).hexdigest() != index_artifact.sha256:
                raise AssertionError("Durable CSI checksum mismatch.")

            source_child = replay_stats["source_child_reconciliation"]
            index_validation = replay_stats["index_validation"]
            if source_child.get("status") != "VALIDATED" or source_child.get("balanced") is not True:
                raise AssertionError("Normalized records do not reconcile to immutable source ALTs.")
            if (
                index_validation.get("indexed_query_records_verified") != index_validation.get("records")
                or index_validation.get("indexed_query_contigs_verified") != index_validation.get("contigs")
                or source_child.get("normalized_child_records") != index_validation.get("records")
            ):
                raise AssertionError("CSI indexed-query results do not reconcile with normalized source-child records.")

            normalized_records = [
                line.split("\t")
                for line in gzip.decompress(replay_vcf).decode("utf-8").splitlines()
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
            index_artifact_count = db.scalar(
                select(func.count(Artifact.id)).where(
                    Artifact.analysis_id == analysis_uuid,
                    Artifact.artifact_type == "VCF_INDEX",
                )
            )
            if artifact_count != 1 or index_artifact_count != 1:
                raise AssertionError(
                    f"Expected one normalized VCF and one CSI artifact; found {artifact_count} and {index_artifact_count}."
                )
            if normalized_artifact.paired_artifact_id != index_artifact.id:
                raise AssertionError("Normalized VCF does not point to its paired CSI artifact.")
            if index_artifact.paired_artifact_id != normalized_artifact.id:
                raise AssertionError("CSI artifact does not point to its paired normalized VCF.")

            step.status = StepStatus.SUCCEEDED
            step.error_code = None
            step.error_message = None
            step.output_artifacts = [
                str(normalized_artifact.id),
                str(index_artifact.id),
            ]
            step.metadata_json = {
                **dict(step.metadata_json or {}),
                "replay_verified": True,
                "normalized_artifact_sha256": normalized_artifact.sha256,
                "index_artifact_sha256": index_artifact.sha256,
                "source_child_reconciliation": source_child,
                "index_validation": index_validation,
            }
            db.add(step)
            db.commit()

            workflow_result = {
                "step_status": str(step.status),
                "step_error_code": step.error_code,
                "recovery": step.metadata_json.get("recovery"),
                "checkpoint": step.metadata_json.get("checkpoint"),
                "artifact_id": str(normalized_artifact.id),
                "artifact_sha256": normalized_artifact.sha256,
                "artifact_count": artifact_count,
                "index_artifact_id": str(index_artifact.id),
                "index_artifact_sha256": index_artifact.sha256,
                "index_artifact_count": index_artifact_count,
                "paired_index_id": str(normalized_artifact.paired_artifact_id),
                "paired_vcf_id": str(index_artifact.paired_artifact_id),
                "replayed_bytes_match": persisted_vcf == replay_vcf,
                "replayed_index_bytes_match": persisted_index == replay_index,
                "normalized_record": normalized_records[0],
                "normalization_tool_version": replay_stats["tool_version"],
                "source_child_reconciliation": source_child,
                "index_validation": index_validation,
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


@celery_app.task(
    bind=True,
    name="siraloom.test_artifact_validation_worker_loss",
    acks_late=True,
    reject_on_worker_lost=True,
)
def artifact_validation_worker_loss(
    self,
    artifact_id: str,
    marker_prefix: str,
    artifact_root: str,
    scratch_root: str,
    crash_boundary: str,
):
    """Kill a real prefork child at a validation publication boundary.

    Supported boundaries:
    - after_tool: after real VCF/BCFtools validation returns, before DB commit;
    - after_commit: after artifact status/audit commit, before dispatch completion.
    """
    import importlib
    import json
    import os
    from pathlib import Path

    from backend.app.infrastructure.artifacts.store import ArtifactStore

    if crash_boundary not in {"after_tool", "after_commit"}:
        raise ValueError(f"Unsupported crash boundary: {crash_boundary}")

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    marker = lambda suffix: f"{marker_prefix}:{suffix}"
    validation_module = importlib.import_module(
        "backend.app.domain.artifact_validation"
    )
    original_validate = validation_module.validate_persisted_artifact
    original_validate_vcf = validation_module.validate_vcf
    original_store_resolver = validation_module.artifact_store_for_uri
    original_scratch_root = settings.worker_scratch_root

    validation_module.artifact_store_for_uri = (
        lambda *args, **kwargs: ArtifactStore(Path(artifact_root))
    )
    settings.worker_scratch_root = scratch_root

    def terminate_after_tool(path, **kwargs):
        result = original_validate_vcf(path, **kwargs)
        if redis.set(marker("first-attempt"), "after_tool", nx=True, ex=600):
            os._exit(73)
        return result

    def terminate_after_commit(artifact_uuid):
        result = original_validate(artifact_uuid)
        if redis.set(marker("first-attempt"), "after_commit", nx=True, ex=600):
            os._exit(73)
        return result

    if crash_boundary == "after_tool":
        validation_module.validate_vcf = terminate_after_tool
    else:
        validation_module.validate_persisted_artifact = terminate_after_commit

    production_queue = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )
    production_task = production_queue.run_artifact_validation_task
    delivery = dict(self.request.delivery_info or {})
    production_task.push_request(
        id=self.request.id,
        retries=self.request.retries,
        delivery_info=delivery,
    )
    try:
        result = production_task.run(artifact_id)
        payload = {
            "result": result,
            "delivery_redelivered": bool(delivery.get("redelivered")),
            "crash_boundary": crash_boundary,
        }
        redis.set(marker("result"), json.dumps(payload), ex=600)
        return payload
    finally:
        production_task.pop_request()
        validation_module.validate_persisted_artifact = original_validate
        validation_module.validate_vcf = original_validate_vcf
        validation_module.artifact_store_for_uri = original_store_resolver
        settings.worker_scratch_root = original_scratch_root
