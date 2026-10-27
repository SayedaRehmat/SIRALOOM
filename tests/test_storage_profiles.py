from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.storage_profiles import (
    activate_storage_profile,
    artifact_store_for_uri,
    get_active_storage_profile,
    list_deployment_storage_targets,
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
            configuration={},
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
            configuration={},
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
        configuration_json={
            "target_id": "lab-a-primary",
            "credentials_path": "/run/secrets/firebase.json",
            "service_account_key": secret,
            "purpose": "clinical",
        },
        status="DRAFT",
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    payload = _payload(profile)

    assert "configuration" not in payload
    assert payload["deployment_target_id"] == "lab-a-primary"
    assert "/run/secrets/firebase.json" not in repr(payload)
    assert secret not in repr(payload)


def test_storage_profile_payload_hides_invalid_target_ids():
    from datetime import datetime, timezone

    from backend.app.api.v1.storage import _payload

    now = datetime.now(timezone.utc)
    profile = OrganizationStorageProfile(
        id=uuid4(),
        organization_id=uuid4(),
        name="primary",
        version=1,
        backend_type="LOCAL_FILESYSTEM",
        storage_key="PRIMARY_ARTIFACTS",
        configuration_json={"target_id": "../private"},
        status="DRAFT",
        created_by=None,
        created_at=now,
        updated_at=now,
    )

    assert _payload(profile)["deployment_target_id"] is None


def test_storage_target_list_exposes_only_targets_owned_by_organization(monkeypatch, tmp_path):
    import json

    from backend.app.config import settings

    organization_id = uuid4()
    other_organization_id = uuid4()
    secret_path = str(tmp_path / "private-service-account.json")
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps({
            "lab-local": {
                "backend_type": "LOCAL_FILESYSTEM",
                "root": str(tmp_path / "lab-local"),
                "organization_id": str(organization_id),
            },
            "lab-cloud": {
                "backend_type": "FIREBASE_GCS",
                "bucket": "private-bucket",
                "organization_id": str(organization_id),
                "project_id": "private-project",
                "credentials_path": secret_path,
            },
            "other-lab": {
                "backend_type": "LOCAL_FILESYSTEM",
                "root": str(tmp_path / "other-lab"),
                "organization_id": str(other_organization_id),
            },
        }),
    )

    targets = list_deployment_storage_targets(organization_id=organization_id)

    assert targets == [
        {"target_id": "lab-cloud", "backend_type": "FIREBASE_GCS"},
        {"target_id": "lab-local", "backend_type": "LOCAL_FILESYSTEM"},
    ]
    assert secret_path not in repr(targets)
    assert "private-bucket" not in repr(targets)
    assert "private-project" not in repr(targets)


def test_historical_artifact_backend_is_selected_from_uri_after_profile_change(
    monkeypatch, tmp_path
):
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
            storage_uri=(
                tmp_path / "artifacts" / "cases" / "case" / "artifacts" / "artifact" / "file.vcf"
            ).as_uri(),
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
            storage_uri=(
                tmp_path / "artifacts" / "cases" / "case" / "artifacts" / "artifact" / "file.vcf"
            ).as_uri(),
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
            artifact_store_for_uri(
                db, organization_id=org.id, storage_uri="https://example.invalid/file"
            )
        with pytest.raises(StorageProfileError, match="Firebase Storage is not configured"):
            artifact_store_for_uri(
                db, organization_id=org.id, storage_uri="gs://lab-current-bucket/file"
            )


def test_organizations_resolve_only_their_deployment_configured_storage_target(
    monkeypatch, tmp_path
):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import (
        StorageProfileError,
        artifact_storage_target_for_organization,
        artifact_store_for_organization,
    )

    root_a = tmp_path / "lab-a"
    root_b = tmp_path / "lab-b"
    root_a.mkdir()
    root_b.mkdir()
    org_a_id, org_b_id = uuid4(), uuid4()
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "lab-a": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(root_a),
                    "organization_id": str(org_a_id),
                },
                "lab-b": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(root_b),
                    "organization_id": str(org_b_id),
                },
            }
        ),
    )
    engine = _engine()
    with Session(engine) as db:
        organizations = [
            Organization(id=org_a_id, name="Lab A", external_identifier=None),
            Organization(id=org_b_id, name="Lab B", external_identifier=None),
        ]
        db.add_all(organizations)
        db.flush()
        profiles = []
        for org, target_id in zip(organizations, ("lab-a", "lab-b"), strict=True):
            profile = register_storage_profile(
                db,
                organization_id=org.id,
                name="primary",
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration={"target_id": target_id},
                created_by=None,
            )
            profiles.append(profile)
        db.commit()
        for org, profile in zip(organizations, profiles, strict=True):
            activate_storage_profile(db, organization_id=org.id, profile_id=profile.id)
        db.commit()

        assert artifact_storage_target_for_organization(
            db, organization_id=org_a_id
        ) == ("LOCAL_FILESYSTEM", "lab-a", str(root_a.resolve()))
        assert artifact_storage_target_for_organization(
            db, organization_id=org_b_id
        ) == ("LOCAL_FILESYSTEM", "lab-b", str(root_b.resolve()))

        stores = [
            artifact_store_for_organization(db, organization_id=org.id) for org in organizations
        ]
        assert stores[0].root == root_a.resolve()
        assert stores[1].root == root_b.resolve()
        assert stores[0].root != stores[1].root

        uri_a = (root_a / "case" / "artifact" / "input.vcf").resolve().as_uri()
        assert (
            artifact_store_for_uri(db, organization_id=organizations[0].id, storage_uri=uri_a).root
            == root_a.resolve()
        )
        with pytest.raises(StorageProfileError, match="not assigned"):
            artifact_store_for_uri(db, organization_id=organizations[1].id, storage_uri=uri_a)


def test_firebase_targets_bind_distinct_deployment_credentials(monkeypatch, tmp_path):
    import json

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import (
        activate_storage_profile,
        artifact_store_for_organization,
        register_storage_profile,
    )
    from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore

    org_a_id, org_b_id = uuid4(), uuid4()
    credential_a = tmp_path / "lab-a.json"
    credential_b = tmp_path / "lab-b.json"
    monkeypatch.setattr(settings, "firebase_storage_enabled", True)
    monkeypatch.setattr(settings, "firebase_credentials_path", None)
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "lab-a": {
                    "backend_type": "FIREBASE_GCS",
                    "bucket": "lab-a-bucket",
                    "organization_id": str(org_a_id),
                    "project_id": "project-a",
                    "credentials_path": str(credential_a),
                },
                "lab-b": {
                    "backend_type": "FIREBASE_GCS",
                    "bucket": "lab-b-bucket",
                    "organization_id": str(org_b_id),
                    "project_id": "project-b",
                    "credentials_path": str(credential_b),
                },
            }
        ),
    )
    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=org_a_id, name="Lab A", external_identifier=None)
        org_b = Organization(id=org_b_id, name="Lab B", external_identifier=None)
        db.add_all([org_a, org_b])
        db.flush()
        profiles = []
        for org, target_id in ((org_a, "lab-a"), (org_b, "lab-b")):
            profile = register_storage_profile(
                db,
                organization_id=org.id,
                name="primary",
                backend_type="FIREBASE_GCS",
                storage_key="PRIMARY_FIREBASE",
                configuration={"target_id": target_id},
                created_by=None,
            )
            profiles.append(profile)
        db.commit()
        for org, profile in ((org_a, profiles[0]), (org_b, profiles[1])):
            activate_storage_profile(db, organization_id=org.id, profile_id=profile.id)
        db.commit()

        store_a = artifact_store_for_organization(db, organization_id=org_a.id)
        store_b = artifact_store_for_organization(db, organization_id=org_b.id)
        assert isinstance(store_a, FirebaseArtifactStore)
        assert isinstance(store_b, FirebaseArtifactStore)
        assert store_a.bucket_name == "lab-a-bucket"
        assert store_a.credentials_path == str(credential_a)
        assert store_a.project_id == "project-a"
        assert store_a.app_name != store_b.app_name
        assert store_b.bucket_name == "lab-b-bucket"
        assert store_b.credentials_path == str(credential_b)
        assert store_b.project_id == "project-b"
        assert store_a.inherit_global_credentials is False


def test_storage_target_cannot_be_assigned_to_two_organizations(monkeypatch, tmp_path):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import StorageProfileError

    engine = _engine()
    with Session(engine) as db:
        org_a = Organization(id=uuid4(), name="Lab A", external_identifier=None)
        org_b = Organization(id=uuid4(), name="Lab B", external_identifier=None)
        db.add_all([org_a, org_b])
        db.flush()
        monkeypatch.setattr(
            settings,
            "artifact_storage_targets_json",
            json.dumps(
                {
                    "shared": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(tmp_path / "shared"),
                        "organization_id": str(org_a.id),
                    },
                }
            ),
        )
        profile_a = register_storage_profile(
            db,
            organization_id=org_a.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"target_id": "shared"},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org_a.id, profile_id=profile_a.id)
        db.commit()
        with pytest.raises(StorageProfileError, match="assigned to another organization"):
            register_storage_profile(
                db,
                organization_id=org_b.id,
                name="primary",
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration={"target_id": "shared"},
                created_by=None,
            )


def test_storage_profile_rejects_database_supplied_paths_and_unknown_target(monkeypatch, tmp_path):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import StorageProfileError

    engine = _engine()
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab", external_identifier=None)
        db.add(org)
        db.flush()
        monkeypatch.setattr(
            settings,
            "artifact_storage_targets_json",
            json.dumps(
                {
                    "approved": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(tmp_path / "approved"),
                        "organization_id": str(org.id),
                    },
                }
            ),
        )
        with pytest.raises(StorageProfileError, match="only target_id"):
            register_storage_profile(
                db,
                organization_id=org.id,
                name="bad",
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration={"root": str(tmp_path / "attacker")},
                created_by=None,
            )
        with pytest.raises(StorageProfileError, match="configuration must be an object"):
            register_storage_profile(
                db,
                organization_id=org.id,
                name="not-an-object",
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration=["target_id", "approved"],
                created_by=None,
            )
        with pytest.raises(StorageProfileError, match="configured deployment target"):
            register_storage_profile(
                db,
                organization_id=org.id,
                name="unknown",
                backend_type="LOCAL_FILESYSTEM",
                storage_key="PRIMARY_ARTIFACTS",
                configuration={"target_id": "attacker"},
                created_by=None,
            )


def test_target_registry_rejects_shared_or_overlapping_storage_across_labs(monkeypatch, tmp_path):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import StorageProfileError, _configured_targets

    org_a, org_b = str(uuid4()), str(uuid4())
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "lab-a": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(tmp_path / "labs"),
                    "organization_id": org_a,
                },
                "lab-b": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(tmp_path / "labs" / "lab-b"),
                    "organization_id": org_b,
                },
            }
        ),
    )
    with pytest.raises(StorageProfileError, match="cannot overlap"):
        _configured_targets()

    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "lab-a": {
                    "backend_type": "FIREBASE_GCS",
                    "bucket": "shared-bucket",
                    "organization_id": org_a,
                },
                "lab-b": {
                    "backend_type": "FIREBASE_GCS",
                    "bucket": "shared-bucket",
                    "organization_id": org_b,
                },
            }
        ),
    )
    with pytest.raises(StorageProfileError, match="cannot be assigned to multiple"):
        _configured_targets()

    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "root": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": "/",
                    "organization_id": org_a,
                }
            }
        ),
    )
    with pytest.raises(StorageProfileError, match="dedicated absolute root"):
        _configured_targets()


def test_retired_legacy_profile_keeps_historical_store_readable_after_target_migration(
    monkeypatch, tmp_path
):
    import json

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import artifact_store_for_uri
    from backend.app.infrastructure.artifacts.store import ArtifactStore

    old_root = tmp_path / "legacy"
    new_root = tmp_path / "assigned"
    org = Organization(id=uuid4(), name="Migrating Lab", external_identifier=None)
    engine = _engine()
    monkeypatch.setattr(settings, "artifact_root", str(old_root))
    monkeypatch.setattr(settings, "artifact_storage_targets_json", "{}")
    with Session(engine) as db:
        db.add(org)
        db.flush()
        old_profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=old_profile.id)
        db.commit()

        monkeypatch.setattr(
            settings,
            "artifact_storage_targets_json",
            json.dumps(
                {
                    "assigned": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(new_root),
                        "organization_id": str(org.id),
                    },
                }
            ),
        )
        new_profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"target_id": "assigned"},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=new_profile.id)
        db.commit()

        historical_uri = (old_root / "case" / "artifact" / "input.vcf").as_uri()
        store = artifact_store_for_uri(db, organization_id=org.id, storage_uri=historical_uri)
        assert isinstance(store, ArtifactStore)
        assert store.root == old_root.resolve()


def test_configured_target_mode_blocks_organizations_without_active_profiles(monkeypatch, tmp_path):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import (
        StorageProfileError,
        artifact_store_for_organization,
        artifact_store_for_uri,
    )

    org = Organization(id=uuid4(), name="Unassigned Lab", external_identifier=None)
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "assigned": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(tmp_path / "assigned"),
                    "organization_id": str(uuid4()),
                },
            }
        ),
    )
    engine = _engine()
    with Session(engine) as db:
        db.add(org)
        db.commit()
        with pytest.raises(StorageProfileError, match="no ACTIVE storage profile"):
            artifact_store_for_organization(db, organization_id=org.id)
        with pytest.raises(StorageProfileError, match="no storage profile assigned"):
            artifact_store_for_uri(
                db,
                organization_id=org.id,
                storage_uri=(tmp_path / "artifacts" / "case" / "file.vcf").as_uri(),
            )


def test_missing_configured_local_target_is_not_created_as_container_local_storage(
    monkeypatch, tmp_path
):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import (
        StorageProfileError,
        activate_storage_profile,
        artifact_store_for_organization,
    )

    org = Organization(id=uuid4(), name="Mounted Lab", external_identifier=None)
    root = tmp_path / "missing-target"
    monkeypatch.setattr(
        settings,
        "artifact_storage_targets_json",
        json.dumps({
            "lab-a": {
                "backend_type": "LOCAL_FILESYSTEM",
                "root": str(root),
                "organization_id": str(org.id),
            }
        }),
    )
    engine = _engine()
    with Session(engine) as db:
        db.add(org)
        db.flush()
        profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"target_id": "lab-a"},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=profile.id)
        db.commit()

        with pytest.raises(StorageProfileError, match="target is missing"):
            artifact_store_for_organization(db, organization_id=org.id)
    assert not root.exists()


def test_removed_retired_target_does_not_block_active_store_reads(monkeypatch, tmp_path):
    import json

    import pytest

    from backend.app.config import settings
    from backend.app.domain.storage_profiles import StorageProfileError, artifact_store_for_uri

    org = Organization(id=uuid4(), name="Migrating Lab", external_identifier=None)
    old_root, active_root = tmp_path / "old", tmp_path / "active"
    old_root.mkdir()
    active_root.mkdir()
    engine = _engine()
    with Session(engine) as db:
        db.add(org)
        db.flush()
        monkeypatch.setattr(
            settings,
            "artifact_storage_targets_json",
            json.dumps(
                {
                    "old": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(old_root),
                        "organization_id": str(org.id),
                    },
                    "active": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(active_root),
                        "organization_id": str(org.id),
                    },
                }
            ),
        )
        old_profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"target_id": "old"},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=old_profile.id)
        db.commit()
        active_profile = register_storage_profile(
            db,
            organization_id=org.id,
            name="primary",
            backend_type="LOCAL_FILESYSTEM",
            storage_key="PRIMARY_ARTIFACTS",
            configuration={"target_id": "active"},
            created_by=None,
        )
        activate_storage_profile(db, organization_id=org.id, profile_id=active_profile.id)
        db.commit()

        monkeypatch.setattr(
            settings,
            "artifact_storage_targets_json",
            json.dumps(
                {
                    "active": {
                        "backend_type": "LOCAL_FILESYSTEM",
                        "root": str(active_root),
                        "organization_id": str(org.id),
                    }
                }
            ),
        )
        current_uri = (active_root / "case" / "artifact" / "current.vcf").as_uri()
        assert (
            artifact_store_for_uri(db, organization_id=org.id, storage_uri=current_uri).root
            == active_root.resolve()
        )
        old_uri = (old_root / "case" / "artifact" / "old.vcf").as_uri()
        with pytest.raises(
            StorageProfileError, match="Historical artifact storage target is unavailable"
        ):
            artifact_store_for_uri(db, organization_id=org.id, storage_uri=old_uri)
