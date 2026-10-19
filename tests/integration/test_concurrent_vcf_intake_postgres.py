import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1.artifacts import _refresh_case_vcf_intake_status
from backend.app.domain.enums import ArtifactType, CaseStatus
from backend.app.infrastructure.db.models import Artifact, Case, Organization, User


@pytest.mark.integration
def test_postgres_concurrent_valid_and_invalid_vcf_uploads_preserve_ready_state():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    barrier = threading.Barrier(2)
    errors = []

    with Session(engine) as db:
        db.add(Organization(
            id=organization_id,
            name=f"vcf-race-{organization_id}",
            external_identifier=str(organization_id),
        ))
        db.commit()
        db.add(User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="VCF Intake Integration",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        db.commit()
        db.add(Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status=CaseStatus.DRAFT,
            clinical_context={},
            language="en",
            created_by=user_id,
        ))
        db.commit()

    def insert_vcf(validation_status: str):
        try:
            with Session(engine) as db:
                db.add(Artifact(
                    id=uuid4(),
                    analysis_id=None,
                    case_id=case_id,
                    artifact_type=ArtifactType.VCF,
                    filename=f"{validation_status.lower()}.vcf",
                    media_type="text/plain",
                    size_bytes=1,
                    sha256="0" * 64,
                    storage_uri=f"test://{uuid4()}",
                    genome_build="GRCh38",
                    specimen_id=None,
                    paired_artifact_id=None,
                    validation_status=validation_status,
                    metadata_json={},
                ))
                db.flush()
                # Both uploads have persisted their artifact row in an open
                # transaction before they race to recompute the case status.
                barrier.wait(timeout=10)
                _refresh_case_vcf_intake_status(db, case_id)
                db.commit()
        except Exception as exc:  # noqa: BLE001 - surface worker failures in the main test thread
            errors.append(exc)

    threads = [
        threading.Thread(target=insert_vcf, args=(status,))
        for status in ("VALID", "INVALID")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    try:
        assert all(not thread.is_alive() for thread in threads), "VCF intake transactions did not finish"
        assert not errors
        with Session(engine) as db:
            case = db.get(Case, case_id)
            statuses = db.scalars(
                select(Artifact.validation_status).where(
                    Artifact.case_id == case_id,
                    Artifact.artifact_type == ArtifactType.VCF,
                )
            ).all()
            assert sorted(statuses) == ["INVALID", "VALID"]
            assert case.status == CaseStatus.READY_FOR_ANALYSIS
    finally:
        with Session(engine) as db:
            db.query(Artifact).filter(Artifact.case_id == case_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
