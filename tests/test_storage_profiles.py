from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.storage_profiles import (
    activate_storage_profile,
    artifact_store_for_uri,
    get_active_storage_profile,
    register_storage_profile,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, OrganizationStorageProfile, User


def _engine():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            OrganizationStorageProfile.__table__,
        ],
    )
    return engine


def test_storage_profile_activation_is_organization_scoped_and_versioned():
    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        db.add(org)
        db.flush()

        first = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"purpose": "clinical-artifacts"},
            created_by=None,
        )
        db.commit()

        active = activate_storage_profile(
            db,
            organization_id=org.id,
            profile_id=first.id,
        )
        db.commit()

        assert active.status == "ACTIVE"
        assert get_active_storage_profile(db, organization_id=org.id).id == first.id

        second = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"purpose": "clinical-artifacts-v2"},
            created_by=None,
        )
        assert second.version == 2

        db.commit()
        activate_storage_profile(
            db,
            organization_id=org.id,
            profile_id=second.id,
        )
        db.commit()

        db.refresh(first)
        assert first.status == "RETIRED"
        assert get_active_storage_profile(db, organization_id=org.id).id == second.id


def test_storage_profile_has_no_cross_organization_visibility():
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        db.add_all([org_a, org_b])
        db.flush()

        profile = register_storage_profile(
            db,
            organization_id=org_a.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={},
            created_by=None,
        )
        db.commit()

        assert get_active_storage_profile(db, organization_id=org_b.id) is None
        assert profile.organization_id == org_a.id


def test_storage_profile_api_payload_never_exposes_configuration():
    from datetime import datetime, timezone

    from backend.app.api.v1.storage import _payload

    secret = "do-not-return-this-service-account-key"
    now = datetime.now(timezone.utc)
    profile = OrganizationStorageProfile(
        id=uuid4(),
        organization_id=uuid4(),
        name="primary",
        version=1,
        backend_type="FIREBASE_GCS",
        storage_key="PRIMARY_FIREBASE",
        configuration_json={"service_account_key": secret, "purpose": "clinical"},
        status="DRAFT",
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    payload = _payload(profile)

    assert "configuration" not in payload
    assert secret not in repr(payload)


def test_historical_artifact_backend_is_selected_from_uri_after_profile_change(monkeypatch, tmp_path):
    from backend.app.config import settings
    from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
    from backend.app.infrastructure.artifacts.store import ArtifactStore

    engine = _engine()
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "firebase_storage_enabled", True)
    monkeypatch.setattr(settings, "firebase_storage_bucket", "lab-current-bucket")
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        db.add(org)
        db.flush()
        cloud_profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="FIREBASE_GCS",
            storage_key="PRIMARY_FIREBASE",
            configuration={},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=cloud_profile.id)
        db.commit()

        historical_local = artifact_store_for_uri(
            db,
            organization_id=org.id,
            storage_uri="file:///old-profile/cases/case/artifacts/artifact/file.vcf",
        )
        assert isinstance(historical_local, ArtifactStore)

        historical_cloud = artifact_store_for_uri(
            db,
            organization_id=org.id,
            storage_uri="gs://lab-current-bucket/cases/case/artifacts/artifact/file.vcf",
        )
        assert isinstance(historical_cloud, FirebaseArtifactStore)
        assert historical_cloud.bucket_name == "lab-current-bucket"

        # A broken current cloud configuration must not prevent reads from an
        # independently available historical local artifact.
        monkeypatch.setattr(settings, "firebase_storage_enabled", False)
        still_available_local = artifact_store_for_uri(
            db,
            organization_id=org.id,
            storage_uri="file:///old-profile/cases/case/artifacts/artifact/file.vcf",
        )
        assert isinstance(still_available_local, ArtifactStore)


def test_artifact_store_for_uri_rejects_unknown_or_unconfigured_backends(monkeypatch):
    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import StorageProfileError

    engine = _engine()
    monkeypatch.setattr(settings, "firebase_storage_enabled", False)
    monkeypatch.setattr(settings, "firebase_storage_bucket", "lab-current-bucket")
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        db.add(org)
        db.commit()
        with pytest.raises(StorageProfileError, match="unsupported backend"):
            artifact_store_for_uri(db, organization_id=org.id, storage_uri="https://example.invalid/file")
        with pytest.raises(StorageProfileError, match="Firebase Storage is not configured"):
            artifact_store_for_uri(db, organization_id=org.id, storage_uri="gs://lab-current-bucket/file")
