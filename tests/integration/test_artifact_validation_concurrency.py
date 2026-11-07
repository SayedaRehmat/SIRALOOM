from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.domain.enums import ArtifactType
from backend.app.domain.ingestion import ValidationResult
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.db.models import (
    Artifact,
    AuditEvent,
    Case,
    Organization,
    Specimen,
    User,
)


@pytest.mark.integration
def test_concurrent_vcf_validation_serializes_case_intake_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two VCF workers must not overwrite aggregate case readiness from stale snapshots."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("Concurrent artifact validation test requires PostgreSQL")

    from backend.app.config import settings
    from backend.app.domain import artifact_validation

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    organization_id, user_id, case_id, specimen_id = (uuid4() for _ in range(4))
    artifact_ids: list = []
    artifact_root = tmp_path / "artifact-store"
    scratch_root = tmp_path / "worker-scratch"
    store = ArtifactStore(artifact_root)
    source_paths = []
    for name in ("valid.vcf", "invalid.vcf"):
        source = tmp_path / name
        source.write_text(
            "##fileformat=VCFv4.2\n"
            "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
            "1\t10\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n",
            encoding="utf-8",
            newline="\n",
        )
        source_paths.append(source)

    barrier = Barrier(2)

    def controlled_validate(path: str | Path) -> ValidationResult:
        barrier.wait(timeout=20)
        if Path(path).name == "valid.vcf":
            return ValidationResult(
                "VALID", "VCF", 1, ["SAMPLE1"], "GRCh38", [], [],
                "VCFv4.2", {}, None,
            )
        return ValidationResult(
            "INVALID", "VCF", 0, ["SAMPLE1"], "GRCh38",
            ["synthetic validation failure"], [], "VCFv4.2", {},
            "VCF_INVALID",
        )

    monkeypatch.setattr(artifact_validation, "SessionLocal", SessionFactory)
    monkeypatch.setattr(
        artifact_validation,
        "artifact_store_for_uri",
        lambda _db, **_kwargs: store,
    )
    monkeypatch.setattr(artifact_validation, "validate_vcf", controlled_validate)
    monkeypatch.setattr(settings, "worker_scratch_root", str(scratch_root))

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"Concurrent Artifact Validation {organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()
            db.add(User(
                id=user_id,
                organization_id=organization_id,
                external_subject=str(user_id),
                email=f"{user_id}@artifact-concurrency.integration.test",
                display_name="Concurrent Artifact Validation",
                role="ADMIN",
                status="ACTIVE",
            ))
            db.commit()
            db.add(Case(
                id=case_id,
                organization_id=organization_id,
                case_identifier=f"ARTIFACT-CONCURRENCY-{case_id}",
                status="VALIDATING",
                clinical_context={},
                language="en",
                created_by=user_id,
            ))
            db.commit()
            db.add(Specimen(
                id=specimen_id,
                case_id=case_id,
                specimen_identifier=f"SPECIMEN-{specimen_id}",
                specimen_type="BLOOD",
                metadata_json={"vcf_sample_name": "SAMPLE1"},
            ))
            db.commit()

        with Session(engine) as db:
            for source in source_paths:
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
                artifact.specimen_id = specimen_id
                artifact_ids.append(artifact.id)
            db.commit()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                artifact_validation.validate_persisted_artifact,
                artifact_ids,
            ))

        assert {result["status"] for result in results} == {"VALID", "INVALID"}
        with Session(engine) as db:
            case = db.get(Case, case_id)
            artifacts = [db.get(Artifact, artifact_id) for artifact_id in artifact_ids]
            assert case is not None
            assert case.status == "READY_FOR_ANALYSIS"
            assert sorted(item.validation_status for item in artifacts if item) == [
                "INVALID", "VALID"
            ]
    finally:
        with Session(engine) as db:
            db.query(AuditEvent).filter(AuditEvent.case_id == case_id).delete(
                synchronize_session=False
            )
            db.query(Artifact).filter(Artifact.case_id == case_id).delete(
                synchronize_session=False
            )
            db.query(Specimen).filter(Specimen.id == specimen_id).delete(
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
