import hashlib
from datetime import UTC, datetime
from uuid import uuid4, uuid5

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Organization, User
from backend.app.workflows.variant import _put_idempotent_stage_artifact


def test_normalization_replay_after_durable_commit_before_worker_ack_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'post-commit-replay.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    artifact_id = uuid5(analysis_id, "siraloom:normalization:normalized-vcf:v6")
    store = ArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "normalized.vcf.gz"
    content = b"stable normalized VCF bytes after durable commit\n"
    source.write_bytes(content)

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Normalization Post-Commit Replay Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Normalization Post-Commit Replay",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"NORM-POST-COMMIT-{case_id}",
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
                workflow_version="test",
                status="RUNNING",
                queue_task_id="normalization-post-commit-replay",
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(UTC),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

        # The artifact row and bytes are durably committed. A worker can die
        # immediately after this point, before acknowledging its broker task.
        with pytest.raises(SystemExit, match="worker lost after durable commit"):
            with Session(engine) as db:
                first = _put_idempotent_stage_artifact(
                    store,
                    artifact_id=artifact_id,
                    db=db,
                    case_id=case_id,
                    analysis_id=analysis_id,
                    source_path=source,
                    filename="normalized.vcf.gz",
                    artifact_type="NORMALIZED_VCF",
                    media_type="application/gzip",
                    genome_build="GRCh38",
                    metadata={
                        "reference_package_checksum": "d" * 64,
                        "normalization_command": ["bcftools", "view", "--output", "attempt-1"],
                    },
                )
                db.commit()
                assert first.id == artifact_id
                raise SystemExit("worker lost after durable commit")

        # A new worker process/session replays the exact deterministic artifact
        # identity. It must reuse the committed row and must not duplicate it.
        with Session(engine) as db:
            replay = _put_idempotent_stage_artifact(
                store,
                artifact_id=artifact_id,
                db=db,
                case_id=case_id,
                analysis_id=analysis_id,
                source_path=source,
                filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF",
                media_type="application/gzip",
                genome_build="GRCh38",
                metadata={
                    "reference_package_checksum": "d" * 64,
                    "normalization_command": ["bcftools", "view", "--output", "attempt-2"],
                },
            )
            db.commit()

            assert replay.id == artifact_id
            assert replay.sha256 == hashlib.sha256(content).hexdigest()
            assert store.read_bytes(replay.storage_uri) == content
            assert replay.metadata_json["normalization_command"] == [
                "bcftools", "view", "--output", "attempt-1"
            ]
            assert db.scalar(select(func.count(Artifact.id)).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )) == 1
