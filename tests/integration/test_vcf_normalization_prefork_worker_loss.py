from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.domain.enums import AnalysisStatus, StepStatus
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    AuditEvent,
    Case,
    Organization,
    User,
    WorkflowStep,
)


@pytest.mark.integration
def test_real_prefork_worker_loss_during_vcf_normalization_redelivers_and_reuses_artifact(
    tmp_path: Path,
):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("Real prefork worker-loss test requires PostgreSQL")
    if not os.environ.get("REDIS_URL"):
        pytest.skip("Real prefork worker-loss test requires Redis")

    bcftools = shutil.which("bcftools")
    if bcftools is None:
        pytest.skip("Pinned BCFtools 1.24 is required for normalization worker-loss test")
    version = subprocess.run(
        [bcftools, "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert version[:2] == ["bcftools 1.24", "Using htslib 1.24"]

    from tests.integration.worker_loss_celery_app import celery_app

    engine = __import__("sqlalchemy").create_engine(database_url, pool_pre_ping=True)
    redis = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    dispatch_id = str(uuid4())
    marker_prefix = f"siraloom:vcf-normalization-worker-loss:{uuid4()}"
    marker_keys = [
        f"{marker_prefix}:checkpoint",
        f"{marker_prefix}:workflow",
        f"{marker_prefix}:result",
    ]
    queue_name = f"vcf-normalization-loss-{uuid4().hex[:12]}"
    worker_name = f"vcf-normalization-loss-{uuid4().hex[:12]}"
    worker_destination = f"{worker_name}@{socket.gethostname()}"

    reference = tmp_path / "reference.fa"
    reference.write_text(">1\nAAAAACCCCC\n", encoding="utf-8", newline="\n")
    (tmp_path / "reference.fa.fai").write_text(
        "1\t10\t3\t10\t11\n", encoding="utf-8"
    )
    source_vcf = tmp_path / "source.vcf"
    source_vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=10>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tPROBAND\n"
        "1\t3\t.\tA\tAA\t50\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
        newline="\n",
    )
    first_output = tmp_path / "normalized-attempt-1.vcf.gz"
    replay_output = tmp_path / "normalized-attempt-2.vcf.gz"
    artifact_root = tmp_path / "durable-artifacts"
    worker_log = tmp_path / "celery-worker.log"
    worker_log_handle = None
    worker_process = None

    try:
        # Persist the FK graph in dependency order. The task's durable dispatch
        # identity is the Celery task ID stored on the Analysis row.
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"VCF Worker Loss Lab {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@vcf-worker-loss.integration.test",
                display_name="VCF Normalization Worker Loss",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.commit()
        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"VCF-WORKER-LOSS-{analysis_id}",
                status="OPEN",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()
        with Session(engine) as db:
            db.add(Analysis(
                id=analysis_id,
                case_id=case_id,
                parent_analysis_id=None,
                assay_id=None,
                analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1",
                workflow_version="worker-loss-integration",
                status=AnalysisStatus.QUEUED,
                queue_task_id=dispatch_id,
                reference_build="GRCh38",
                configuration={},
                started_at=None,
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        worker_log_handle = worker_log.open("w", encoding="utf-8")
        worker_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "celery",
                "-A",
                "tests.integration.worker_loss_celery_app:celery_app",
                "worker",
                "--pool=prefork",
                "--concurrency=1",
                f"--queues={queue_name}",
                f"--hostname={worker_name}@%h",
                "--loglevel=INFO",
                "--without-gossip",
                "--without-mingle",
                "--without-heartbeat",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=os.environ.copy(),
            stdout=worker_log_handle,
            stderr=subprocess.STDOUT,
        )

        # Do not publish until the real worker has registered its remote-control
        # endpoint. This avoids mistaking startup latency for broker redelivery.
        inspector = celery_app.control.inspect(
            timeout=1, destination=[worker_destination]
        )
        ready_deadline = time.monotonic() + 45
        while time.monotonic() < ready_deadline:
            if worker_process.poll() is not None:
                raise AssertionError(
                    f"Celery worker exited during startup: {worker_log.read_text(encoding='utf-8')}"
                )
            if inspector.ping():
                break
            time.sleep(0.5)
        else:
            raise AssertionError(
                f"Celery prefork worker did not become ready: {worker_log.read_text(encoding='utf-8')}"
            )

        redis.delete(*marker_keys)
        celery_app.send_task(
            "siraloom.test_vcf_normalization_worker_loss",
            args=[
                str(analysis_id),
                marker_prefix,
                str(source_vcf),
                str(reference),
                str(first_output),
                str(replay_output),
                str(artifact_root),
                bcftools,
            ],
            task_id=dispatch_id,
            queue=queue_name,
        )

        result_key = f"{marker_prefix}:result"
        result_deadline = time.monotonic() + 120
        result_payload = None
        while time.monotonic() < result_deadline:
            result_payload = redis.get(result_key)
            if result_payload:
                break
            if worker_process.poll() is not None:
                raise AssertionError(
                    f"Celery worker exited before replay completed: {worker_log.read_text(encoding='utf-8')}"
                )
            time.sleep(0.5)
        if not result_payload:
            raise AssertionError(
                f"Timed out waiting for real worker-loss redelivery: {worker_log.read_text(encoding='utf-8')}"
            )

        result = json.loads(result_payload)
        workflow_result = result["workflow_result"]
        assert result["delivery_redelivered"] is True
        assert workflow_result["step_status"] == StepStatus.SUCCEEDED
        assert workflow_result["step_error_code"] is None
        assert workflow_result["recovery"] == "CELERY_REDELIVERY"
        assert workflow_result["checkpoint"] == "normalized-artifact-committed"
        assert workflow_result["artifact_count"] == 1
        assert workflow_result["replayed_bytes_match"] is True
        assert workflow_result["normalization_tool_version"] == "bcftools 1.24"
        assert workflow_result["normalized_record"][1] == "1"
        assert workflow_result["normalized_record"][3:5] == ["A", "AA"]

        with Session(engine) as db:
            analysis = db.get(Analysis, analysis_id)
            step = db.scalar(select(WorkflowStep).where(
                WorkflowStep.analysis_id == analysis_id,
                WorkflowStep.step_id == "normalize",
            ))
            artifact_rows = db.scalars(select(Artifact).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )).all()
            recovery_events = db.scalars(select(AuditEvent).where(
                AuditEvent.analysis_id == analysis_id,
                AuditEvent.event_type == "WORKFLOW_WORKER_RECOVERY",
            )).all()
            assert analysis.status == AnalysisStatus.RUNNING
            assert step is not None and step.status == StepStatus.SUCCEEDED
            assert len(artifact_rows) == 1
            assert artifact_rows[0].id == __import__("uuid").UUID(workflow_result["artifact_id"])
            assert artifact_rows[0].sha256 == workflow_result["artifact_sha256"]
            assert len(recovery_events) == 1
            assert recovery_events[0].payload["recovered_steps"] == ["normalize"]

    finally:
        if worker_process is not None and worker_process.poll() is None:
            worker_process.terminate()
            try:
                worker_process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker_process.kill()
                worker_process.wait(timeout=10)
        if worker_log_handle is not None:
            worker_log_handle.close()
        redis.delete(*marker_keys)
        with Session(engine) as db:
            db.query(AuditEvent).filter(
                AuditEvent.analysis_id == analysis_id
            ).delete(synchronize_session=False)
            db.query(WorkflowStep).filter(
                WorkflowStep.analysis_id == analysis_id
            ).delete(synchronize_session=False)
            db.query(Artifact).filter(
                Artifact.analysis_id == analysis_id
            ).delete(synchronize_session=False)
            db.query(Analysis).filter(Analysis.id == analysis_id).delete(
                synchronize_session=False
            )
            db.query(Case).filter(Case.id == case_id).delete(
                synchronize_session=False
            )
            db.query(User).filter(User.id == user_id).delete(
                synchronize_session=False
            )
            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete(synchronize_session=False)
            db.commit()
        engine.dispose()
