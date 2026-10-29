"""PostgreSQL proof for the backup tool's artifact-target classification query."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Artifact,
    Case,
    Organization,
    OrganizationStorageProfile,
    User,
)
from scripts.laboratory_backup import ARTIFACT_STORAGE_PREFLIGHT_SQL


@pytest.mark.integration
def test_backup_storage_preflight_classifies_cloud_custom_and_legacy_targets():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    profile_id = uuid4()
    user_id = uuid4()
    case_id = uuid4()
    artifact_id = uuid4()
    try:
        with Session(engine) as db:
            db.add(
                Organization(
                    id=organization_id,
                    name=f"backup-preflight-{organization_id}",
                    external_identifier=str(organization_id),
                )
            )
            db.add(
                User(
                    id=user_id,
                    organization_id=organization_id,
                    display_name="Backup preflight test",
                    role="LAB_DIRECTOR",
                    status="ACTIVE",
                )
            )
            db.add(
                Case(
                    id=case_id,
                    organization_id=organization_id,
                    case_identifier=f"backup-preflight-{case_id}",
                    status="ACTIVE",
                    created_by=user_id,
                )
            )
            db.add(
                Artifact(
                    id=artifact_id,
                    case_id=case_id,
                    artifact_type="VCF",
                    filename="source.vcf",
                    size_bytes=1,
                    sha256="0" * 64,
                    storage_uri="file:///data/siraloom/artifacts/source.vcf",
                )
            )
            db.add(
                OrganizationStorageProfile(
                    id=profile_id,
                    organization_id=organization_id,
                    name="backup-test",
                    version=1,
                    backend_type="LOCAL_FILESYSTEM",
                    storage_key="PRIMARY_ARTIFACTS",
                    configuration_json={"target_id": "lab-artifact-root"},
                    status="RETIRED",
                )
            )
            db.commit()

            classify = lambda: db.execute(text(ARTIFACT_STORAGE_PREFLIGHT_SQL)).scalar_one()
            assert classify() == "CUSTOM_LOCAL_ARTIFACT_TARGETS_PRESENT"

            profile = db.get(OrganizationStorageProfile, profile_id)
            assert profile is not None
            profile.backend_type = "FIREBASE_GCS"
            db.commit()
            assert classify() == "CLOUD_ARTIFACTS_PRESENT"

            profile.backend_type = "LOCAL_FILESYSTEM"
            profile.configuration_json = {}
            db.commit()
            assert classify() == "LOCAL_ARTIFACTS_ONLY"

            db.delete(profile)
            artifact = db.get(Artifact, artifact_id)
            assert artifact is not None
            artifact.storage_uri = "file:///lab-a/artifacts/source.vcf"
            db.commit()
            assert classify() == "NON_LEGACY_ARTIFACTS_PRESENT"

            db.delete(artifact)
            db.flush()
            db.delete(db.get(Case, case_id))
            db.delete(db.get(User, user_id))
            db.delete(db.get(Organization, organization_id))
            db.commit()
    finally:
        engine.dispose()
