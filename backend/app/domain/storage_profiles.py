from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.db.models import OrganizationStorageProfile


class StorageProfileError(ValueError):
    pass


SUPPORTED_BACKENDS = {"LOCAL_FILESYSTEM", "FIREBASE_GCS"}
SUPPORTED_STORAGE_KEYS = {"PRIMARY_ARTIFACTS", "PRIMARY_FIREBASE"}


def _validate_target(backend_type: str, storage_key: str) -> None:
    backend = backend_type.strip().upper()
    key = storage_key.strip().upper()
    if backend not in SUPPORTED_BACKENDS:
        raise StorageProfileError(f"Unsupported storage backend: {backend}")
    if key not in SUPPORTED_STORAGE_KEYS:
        raise StorageProfileError(f"Unsupported deployment storage key: {key}")
    if backend == "LOCAL_FILESYSTEM" and key != "PRIMARY_ARTIFACTS":
        raise StorageProfileError("LOCAL_FILESYSTEM must use PRIMARY_ARTIFACTS")
    if backend == "FIREBASE_GCS" and key != "PRIMARY_FIREBASE":
        raise StorageProfileError("FIREBASE_GCS must use PRIMARY_FIREBASE")
    if backend == "LOCAL_FILESYSTEM":
        root = str(settings.artifact_root or "").strip()
        if not root:
            raise StorageProfileError("ARTIFACT_ROOT is not configured")
    if backend == "FIREBASE_GCS":
        if not settings.firebase_storage_enabled:
            raise StorageProfileError("FIREBASE_STORAGE_ENABLED is false")
        if not settings.firebase_storage_bucket:
            raise StorageProfileError("FIREBASE_STORAGE_BUCKET is not configured")


def get_active_storage_profile(
    db: Session,
    *,
    organization_id: UUID,
) -> OrganizationStorageProfile | None:
    return db.scalar(
        select(OrganizationStorageProfile)
        .where(
            OrganizationStorageProfile.organization_id == organization_id,
            OrganizationStorageProfile.status == "ACTIVE",
        )
        .order_by(OrganizationStorageProfile.version.desc())
        .limit(1)
    )


def resolve_storage_profile(
    db: Session,
    *,
    organization_id: UUID,
) -> OrganizationStorageProfile | None:
    profile = get_active_storage_profile(db, organization_id=organization_id)
    if profile is not None:
        _validate_target(profile.backend_type, profile.storage_key)
        return profile

    if settings.organization_require_storage_profile:
        raise StorageProfileError(
            "Organization has no ACTIVE storage profile. "
            "Register and activate the laboratory artifact storage target before use."
        )

    return None


def register_storage_profile(
    db: Session,
    *,
    organization_id: UUID,
    name: str,
    backend_type: str,
    storage_key: str,
    configuration: dict | None,
    created_by: UUID | None,
) -> OrganizationStorageProfile:
    clean_name = name.strip()
    if not clean_name:
        raise StorageProfileError("Storage profile name is required")
    _validate_target(backend_type, storage_key)

    latest = db.scalar(
        select(OrganizationStorageProfile)
        .where(
            OrganizationStorageProfile.organization_id == organization_id,
            OrganizationStorageProfile.name == clean_name,
        )
        .order_by(OrganizationStorageProfile.version.desc())
        .limit(1)
    )
    version = (latest.version + 1) if latest else 1

    profile = OrganizationStorageProfile(
        id=uuid4(),
        organization_id=organization_id,
        name=clean_name,
        version=version,
        backend_type=backend_type.strip().upper(),
        storage_key=storage_key.strip().upper(),
        configuration_json=dict(configuration or {}),
        status="DRAFT",
        created_by=created_by,
    )
    db.add(profile)
    db.flush()
    return profile


def activate_storage_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
) -> OrganizationStorageProfile:
    profile = db.scalar(
        select(OrganizationStorageProfile)
        .where(
            OrganizationStorageProfile.id == profile_id,
            OrganizationStorageProfile.organization_id == organization_id,
        )
        .with_for_update()
    )
    if profile is None:
        raise StorageProfileError("Storage profile not found")

    _validate_target(profile.backend_type, profile.storage_key)

    current = list(
        db.scalars(
            select(OrganizationStorageProfile)
            .where(
                OrganizationStorageProfile.organization_id == organization_id,
                OrganizationStorageProfile.status == "ACTIVE",
                OrganizationStorageProfile.id != profile.id,
            )
            .with_for_update()
        )
    )
    for row in current:
        row.status = "RETIRED"

    profile.status = "ACTIVE"
    db.add(profile)
    db.flush()
    return profile
