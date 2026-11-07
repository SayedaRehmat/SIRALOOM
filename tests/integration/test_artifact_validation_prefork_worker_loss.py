from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.domain.enums import ArtifactType
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.models import (
    Artifact,
    ArtifactValidationDispatch,
    AuditEvent,
    Case,
    Organization,
    User,
)


@pytest.mark.integration
@pytest.mark.parametrize("crash_boundary", ["after_tool", "after_commit"])
def test_real_prefork_artifact_validation_worker_loss_redelivers_and_commits_once(
    tmp_path: Path,
    crash_boundary: str,
):
    database_url = os.environ.get("DATABASE_URL", "")
    redis_url = os.environ.get("REDIS_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("Artifact validation worker-loss test requires PostgreSQL")
    if not redis_url:
        pytest.skip("Artifact validation worker-loss test requires Redis")

    bcftools = shutil.which("bcftools")
    if bcftools is None:
        pytest.skip("Pinned BCFtools is required for artifact validation")
    version = subprocess.run(
        [bcftools, "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert version[0] == f"bcftools {settings.bcftools_version}"
    assert version[1] == f"Using htslib {settings.htslib_version}"

    from sqlalchemy import create_engine

    integration_dir = str(Path(__file__).resolve().parent)
    if integration_dir not in sys.path:
        sys.path.insert(0, integration_dir)
    celery_app = __import__(
        "worker_loss_celery_app", fromlist=["celery_app"]
    ).celery_app

    engine = create_engine(database_url, pool_pre_ping=True)
    redis = Redis.from_url(redis_url, decode_responses=True)
    organization_id, user_id, case_id = (uuid4() for _ in range(3))
    artifact_id, dispatch_id = uuid4(), uuid4()
    marker_prefix = f"siraloom:artifact-validation-worker-loss:{uuid4()}"
    marker_keys = [
        f"{marker_prefix}:first-attempt",
        f"{marker_prefix}:result",
    ]
    queue_name = f"artifact-validation-loss-{uuid4().hex[:12]}"
    worker_name = f"artifact-validation-loss-{uuid4().hex[:12]}"
    artifact_root = tmp_path / "artifact-store"
    scratch_root = tmp_path / "worker-scratch"
    source = tmp_path / "site-only.vcf"
    source.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tG\t50\tPASS\t.\n",
        encoding="utf-8",
        newline="\n",
    )
    worker_log = tmp_path / "artifact-validation-worker.log"
    worker_log_handle = None
    worker_process = None

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"Artifact Validation Worker Loss {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
        with Session(engine) as db:
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@artifact-worker-loss.integration.test",
                display_name="Artifact Validation Worker Loss",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.commit()
        with Session(engine) as db:
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"ARTIFACT-WORKER-LOSS-{dispatch_id}",
                status="VALIDATING",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()

        store = ArtifactStore(artifact_root)
        with Session(engine) as db:
            artifact = store.put_file(
                db=db,
                case_id=case_id,
                analysis_id=None,
                source_path=source,
                filename=source.name,
                artifact_type=ArtifactType.VCF,
                media_type="text/vcf",
                genome_build="GRCh38",
                metadata={"ingestion": {"file_kind": "VCF"}},
                validation_status="PENDING",
            )
            assert artifact.id is not None
            artifact_id = artifact.id
            db.commit()

        with Session(engine) as db:
            db.add(ArtifactValidationDispatch(
                id=dispatch_id,
                artifact_id=artifact_id,
                organization_id=organization_id,
                case_id=case_id,
                status="PUBLISHED",
                task_id=str(dispatch_id),
                attempts=1,
                toolchain_profile_id=settings.bcftools_profile_id,
                toolchain_bcftools_version=settings.bcftools_version,
                toolchain_htslib_version=settings.htslib_version,
                toolchain_queue=queue_name,
                toolchain_snapshot={
                    "profile_id": settings.bcftools_profile_id,
                    "bcftools_version": settings.bcftools_version,
                    "htslib_version": settings.htslib_version,
                    "worker_queue": queue_name,
                },
                published_at=datetime.now(timezone.utc),
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

        inspector = celery_app.control.inspect(timeout=1)
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
                f"Celery worker did not become ready: {worker_log.read_text(encoding='utf-8')}"
            )

        redis.delete(*marker_keys)
        celery_app.send_task(
            "siraloom.test_artifact_validation_worker_loss",
            args=[
                str(artifact_id),
                marker_prefix,
                str(artifact_root),
                str(scratch_root),
                crash_boundary,
            ],
            task_id=str(dispatch_id),
            queue=queue_name,
        )

        result_key = f"{marker_prefix}:result"
        result_payload = None
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
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
                f"Timed out waiting for artifact validation replay: {worker_log.read_text(encoding='utf-8')}"
            )

        result = json.loads(result_payload)
        assert result["delivery_redelivered"] is True
        assert result["result"]["status"] == "VALID_SITE_ONLY"
        assert redis.get(f"{marker_prefix}:first-attempt") == crash_boundary
        assert result["crash_boundary"] == crash_boundary

        with Session(engine) as db:
            artifact = db.get(Artifact, artifact_id)
            dispatch = db.get(ArtifactValidationDispatch, dispatch_id)
            events = db.scalars(
                select(AuditEvent).where(
                    AuditEvent.case_id == case_id,
                    AuditEvent.event_type == "ARTIFACT_VALIDATION_COMPLETED",
                )
            ).all()
            assert artifact is not None
            assert artifact.validation_status == "VALID_SITE_ONLY"
            assert artifact.metadata_json["workflow_eligibility"] == "SITE_LEVEL_ONLY"
            assert dispatch is not None
            assert dispatch.status == "COMPLETED"
            assert dispatch.task_id == str(dispatch_id)
            assert dispatch.attempts == 3
            assert len(events) == 1
            assert events[0].subject_id == str(artifact_id)

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
            db.query(AuditEvent).filter(AuditEvent.case_id == case_id).delete(
                synchronize_session=False
            )
            db.query(ArtifactValidationDispatch).filter(
                ArtifactValidationDispatch.id == dispatch_id
            ).delete(synchronize_session=False)
            db.query(Artifact).filter(Artifact.id == artifact_id).delete(
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
        shutil.rmtree(artifact_root, ignore_errors=True)
        shutil.rmtree(scratch_root, ignore_errors=True)
        engine.dispose()
