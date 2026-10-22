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


def test_normalization_artifact_replay_reuses_same_row_and_preserves_original_provenance(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'artifact-idempotency.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact_id = uuid5(analysis_id, "siraloom:normalization:normalized-vcf:v2")
    store = ArtifactStore(tmp_path / "artifacts")
    first_source = tmp_path / "normalized-first.vcf.gz"
    second_source = tmp_path / "normalized-replay.vcf.gz"
    first_source.write_bytes(b"stable normalized VCF bytes\n")
    second_source.write_bytes(first_source.read_bytes())
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name="Artifact Replay Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id, organization_id=organization_id,
                external_subject=str(user_id), email=f"{user_id}@test.local",
                display_name="Artifact Replay", role="ADMIN", status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id, organization_id=organization_id,
                case_identifier=f"ARTIFACT-REPLAY-{case_id}", status="OPEN",
                clinical_context={}, language="en", created_by=user_id,
            ))
            db.flush()
            db.add(Analysis(
                id=analysis_id, case_id=case_id, parent_analysis_id=None,
                assay_id=None, analysis_type="VARIANT_INTERPRETATION",
                workflow_id="variant-v1", workflow_version="test",
                status="RUNNING", queue_task_id="artifact-replay",
                reference_build="GRCh38", configuration={},
                started_at=datetime.now(UTC), completed_at=None,
                created_by=user_id, analysis_version=1,
            ))
            db.commit()

            first = _put_idempotent_stage_artifact(
                store, artifact_id=artifact_id, db=db,
                case_id=case_id, analysis_id=analysis_id,
                source_path=first_source, filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                genome_build="GRCh38",
                metadata={
                    "reference_package_checksum": "a" * 64,
                    "normalization_command": ["bcftools", "-o", "/tmp/worker-attempt-1.vcf.gz"],
                },
            )
            db.commit()
            second = _put_idempotent_stage_artifact(
                store, artifact_id=artifact_id, db=db,
                case_id=case_id, analysis_id=analysis_id,
                source_path=second_source, filename="normalized.vcf.gz",
                artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                genome_build="GRCh38",
                metadata={
                    "reference_package_checksum": "a" * 64,
                    "normalization_command": ["bcftools", "-o", "/tmp/worker-attempt-2.vcf.gz"],
                },
            )

            assert second.id == first.id == artifact_id
            assert second.metadata_json["normalization_command"][-1] == "/tmp/worker-attempt-1.vcf.gz"
            assert db.scalar(select(func.count(Artifact.id)).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )) == 1

            changed_source = tmp_path / "changed.vcf.gz"
            changed_source.write_bytes(b"different normalized bytes\n")
            with pytest.raises(RuntimeError, match="produced different bytes on replay"):
                _put_idempotent_stage_artifact(
                    store, artifact_id=artifact_id, db=db,
                    case_id=case_id, analysis_id=analysis_id,
                    source_path=changed_source, filename="normalized.vcf.gz",
                    artifact_type="NORMALIZED_VCF", media_type="application/gzip",
                    genome_build="GRCh38",
                    metadata={
                        "reference_package_checksum": "a" * 64,
                        "normalization_command": ["bcftools", "-o", "/tmp/worker-attempt-3.vcf.gz"],
                    },
                )
    finally:
        engine.dispose()


def test_normalization_artifact_replay_recovers_after_file_write_before_commit(
    monkeypatch, tmp_path
):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'artifact-worker-loss.db'}")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id, analysis_id = (uuid4() for _ in range(4))
    artifact_id = uuid5(analysis_id, "siraloom:normalization:normalized-vcf:v3")
    store = ArtifactStore(tmp_path / "artifacts")
    source = tmp_path / "normalized.vcf.gz"
    content = b"stable normalized VCF output from pinned execution\n"
    source.write_bytes(content)
    uri = store.uri_for_artifact(
        case_id=case_id, artifact_id=artifact_id, filename="normalized.vcf.gz"
    )

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name="Normalization Worker Loss Lab",
                external_identifier=str(organization_id),
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@test.local",
                display_name="Normalization Worker Loss",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.flush()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"NORM-WORKER-LOSS-{case_id}",
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
                queue_task_id="normalization-worker-loss",
                reference_build="GRCh38",
                configuration={},
                started_at=datetime.now(UTC),
                completed_at=None,
                created_by=user_id,
                analysis_version=1,
            ))
            db.commit()

            persist_file = store.put_file

            def lose_worker_after_file_and_row_flush(**kwargs):
                artifact = persist_file(**kwargs)
                raise SystemExit(f"simulated worker loss after flush: {artifact.id}")

            monkeypatch.setattr(store, "put_file", lose_worker_after_file_and_row_flush)
            with pytest.raises(SystemExit, match="simulated worker loss after flush"):
                _put_idempotent_stage_artifact(
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
                    metadata={"reference_package_checksum": "c" * 64},
                )

            # A dead worker's open transaction is rolled back by the DB driver;
            # the filesystem copy survives and must be safely overwritten on replay.
            db.rollback()
            assert db.get(Artifact, artifact_id) is None
            assert store.exists(uri)

            monkeypatch.setattr(store, "put_file", persist_file)
            recovered = _put_idempotent_stage_artifact(
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
                metadata={"reference_package_checksum": "c" * 64},
            )
            db.commit()

            assert recovered.id == artifact_id
            assert recovered.sha256 == hashlib.sha256(content).hexdigest()
            assert store.read_bytes(uri) == content
            assert db.scalar(select(func.count(Artifact.id)).where(
                Artifact.analysis_id == analysis_id,
                Artifact.artifact_type == "NORMALIZED_VCF",
            )) == 1
    finally:
        engine.dispose()
