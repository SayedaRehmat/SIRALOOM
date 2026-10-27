from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.db.models import OrganizationStorageProfile


class StorageProfileError(ValueError):
    pass


SUPPORTED_BACKENDS = {"LOCAL_FILESYSTEM", "FIREBASE_GCS"}
SUPPORTED_STORAGE_KEYS = {"PRIMARY_ARTIFACTS", "PRIMARY_FIREBASE"}
_TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


def _configured_targets() -> dict[str, dict[str, str]]:
    try:
        raw = json.loads(settings.artifact_storage_targets_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise StorageProfileError("ARTIFACT_STORAGE_TARGETS_JSON is invalid JSON") from exc
    if not isinstance(raw, dict):
        raise StorageProfileError("Artifact storage target configuration must be an object")

    targets: dict[str, dict[str, str]] = {}
    for target_id, value in raw.items():
        if not isinstance(target_id, str) or not _TARGET_ID.fullmatch(target_id):
            raise StorageProfileError("Artifact storage target ID is invalid")
        if not isinstance(value, dict) or set(value) - {
            "backend_type",
            "root",
            "bucket",
            "organization_id",
            "credentials_path",
            "project_id",
        }:
            raise StorageProfileError(f"Artifact storage target {target_id} has invalid fields")
        try:
            owner_id = str(UUID(str(value.get("organization_id"))))
        except (ValueError, TypeError, AttributeError) as exc:
            raise StorageProfileError(
                f"Artifact storage target {target_id} needs an organization_id"
            ) from exc
        backend = str(value.get("backend_type") or "").strip().upper()
        if backend == "LOCAL_FILESYSTEM":
            root_value = value.get("root")
            root = root_value.strip() if isinstance(root_value, str) else ""
            resolved_root = Path(root).expanduser().resolve() if root else None
            if (
                resolved_root is None
                or not resolved_root.is_absolute()
                or resolved_root == Path(resolved_root.anchor)
                or any(key in value for key in ("bucket", "credentials_path", "project_id"))
            ):
                raise StorageProfileError(
                    f"Local storage target {target_id} needs a dedicated absolute root"
                )
            targets[target_id] = {
                "backend_type": backend,
                "root": str(resolved_root),
                "organization_id": owner_id,
            }
        elif backend == "FIREBASE_GCS":
            bucket_value = value.get("bucket")
            bucket = bucket_value.strip() if isinstance(bucket_value, str) else ""
            if (
                not bucket
                or "/" in bucket
                or any(char.isspace() for char in bucket)
                or "root" in value
            ):
                raise StorageProfileError(f"Cloud storage target {target_id} needs a bucket name")
            credentials_value = value.get("credentials_path")
            if credentials_value is not None and not isinstance(credentials_value, str):
                raise StorageProfileError(
                    f"Cloud storage target {target_id} credential path must be a string"
                )
            credentials_path = credentials_value.strip() if credentials_value else ""
            if credentials_path and not Path(credentials_path).expanduser().is_absolute():
                raise StorageProfileError(
                    f"Cloud storage target {target_id} credential path must be absolute"
                )
            project_value = value.get("project_id")
            if project_value is not None and not isinstance(project_value, str):
                raise StorageProfileError(
                    f"Cloud storage target {target_id} project_id must be a string"
                )
            project_id = project_value.strip() if project_value else ""
            targets[target_id] = {
                "backend_type": backend,
                "bucket": bucket,
                "organization_id": owner_id,
                **(
                    {"credentials_path": str(Path(credentials_path).expanduser().resolve())}
                    if credentials_path
                    else {}
                ),
                **({"project_id": project_id} if project_id else {}),
            }
        else:
            raise StorageProfileError(
                f"Artifact storage target {target_id} has an unsupported backend"
            )
    seen_cloud_buckets: dict[str, str] = {}
    seen_local_roots: dict[str, str] = {}
    for target_id, target in targets.items():
        if target["backend_type"] == "FIREBASE_GCS":
            key = target["bucket"].casefold()
            previous = seen_cloud_buckets.setdefault(key, target["organization_id"])
            if previous != target["organization_id"]:
                raise StorageProfileError(
                    "A cloud bucket cannot be assigned to multiple organizations"
                )
        else:
            root = Path(target["root"])
            key = str(root)
            for other_key, other_owner in seen_local_roots.items():
                other_root = Path(other_key)
                if other_owner != target["organization_id"] and (
                    root == other_root or root in other_root.parents or other_root in root.parents
                ):
                    raise StorageProfileError(
                        "Local storage roots cannot overlap across organizations"
                    )
            seen_local_roots[key] = target["organization_id"]
    return targets


def list_deployment_storage_targets(*, organization_id: UUID) -> list[dict[str, str]]:
    """Expose only target identifiers and backend types assigned to one organization."""
    owner_id = str(organization_id)
    return [
        {"target_id": target_id, "backend_type": target["backend_type"]}
        for target_id, target in sorted(_configured_targets().items())
        if target["organization_id"] == owner_id
    ]


def configured_local_storage_targets() -> list[tuple[str, str]]:
    """Return configured local target IDs and roots for internal health checks."""
    return [
        (target_id, target["root"])
        for target_id, target in sorted(_configured_targets().items())
        if target["backend_type"] == "LOCAL_FILESYSTEM"
    ]


def configured_firebase_storage_target_ids() -> list[str]:
    """Return configured cloud target IDs without exposing bucket credentials."""
    return [
        target_id
        for target_id, target in sorted(_configured_targets().items())
        if target["backend_type"] == "FIREBASE_GCS"
    ]


def probe_configured_firebase_storage_target(target_id: str) -> None:
    """Exercise write/read/delete against one deployment-approved bucket."""
    targets = _configured_targets()
    target = targets.get(target_id)
    if target is None or target["backend_type"] != "FIREBASE_GCS":
        raise StorageProfileError("Configured Firebase storage target is unavailable")
    if not settings.firebase_storage_enabled:
        raise StorageProfileError("FIREBASE_STORAGE_ENABLED is false")
    store = _store("FIREBASE_GCS", target["bucket"], target_id=target_id)
    store.probe()


def _target_for_profile(profile: OrganizationStorageProfile) -> tuple[str, str]:
    configuration = profile.configuration_json or {}
    if not isinstance(configuration, dict) or set(configuration) - {"target_id"}:
        raise StorageProfileError("Storage profile configuration may contain only target_id")

    targets = _configured_targets()
    target_id = configuration.get("target_id")
    if targets:
        if target_id is None and profile.status == "RETIRED":
            # Keep pre-allowlist artifacts readable after the organization has
            # rotated to an explicitly assigned deployment target.
            if profile.backend_type == "LOCAL_FILESYSTEM" and settings.artifact_root:
                return "__legacy_local__", str(Path(settings.artifact_root).expanduser().resolve())
            if (
                profile.backend_type == "FIREBASE_GCS"
                and settings.firebase_storage_enabled
                and settings.firebase_storage_bucket
            ):
                return "__legacy_firebase__", settings.firebase_storage_bucket
        if not isinstance(target_id, str) or target_id not in targets:
            raise StorageProfileError(
                "Storage profile must reference a configured deployment target"
            )
        target = targets[target_id]
        if target["organization_id"] != str(profile.organization_id):
            raise StorageProfileError(
                "Deployment storage target is assigned to another organization"
            )
        if target["backend_type"] != profile.backend_type:
            raise StorageProfileError(
                "Storage profile backend does not match its deployment target"
            )
        if profile.backend_type == "FIREBASE_GCS" and not settings.firebase_storage_enabled:
            raise StorageProfileError("FIREBASE_STORAGE_ENABLED is false")
        return target_id, target["root"] if profile.backend_type == "LOCAL_FILESYSTEM" else target[
            "bucket"
        ]

    # Backward-compatible single-target mode for existing deployments. It is
    # deliberately unavailable once an explicit target allowlist is configured.
    if target_id is not None:
        raise StorageProfileError("No deployment storage targets are configured")
    if profile.backend_type == "LOCAL_FILESYSTEM":
        root = str(settings.artifact_root or "").strip()
        if not root:
            raise StorageProfileError("ARTIFACT_ROOT is not configured")
        return "__legacy_local__", str(Path(root).expanduser().resolve())
    if profile.backend_type == "FIREBASE_GCS":
        if not settings.firebase_storage_enabled or not settings.firebase_storage_bucket:
            raise StorageProfileError("Firebase Storage is not configured")
        return "__legacy_firebase__", settings.firebase_storage_bucket
    raise StorageProfileError(f"Unsupported storage backend: {profile.backend_type}")


def artifact_storage_target_for_organization(
    db: Session, *, organization_id: UUID
) -> tuple[str, str, str]:
    """Resolve the configured artifact backend and location for one organization."""
    profile = resolve_storage_profile(db, organization_id=organization_id)
    if profile is None:
        if _configured_targets():
            raise StorageProfileError(
                "Organization has no ACTIVE storage profile for the configured deployment targets"
            )
        if settings.firebase_storage_enabled:
            return "FIREBASE_GCS", "__legacy_firebase__", settings.firebase_storage_bucket or ""
        root = str(settings.artifact_root or "").strip()
        if not root:
            raise StorageProfileError("ARTIFACT_ROOT is not configured")
        return "LOCAL_FILESYSTEM", "__legacy_local__", str(Path(root).expanduser().resolve())

    target_id, target = _target_for_profile(profile)
    return profile.backend_type, target_id, target


def _validate_target(
    backend_type: str,
    storage_key: str,
    configuration: dict | None = None,
    organization_id: UUID | None = None,
    status: str = "DRAFT",
) -> None:
    if configuration is not None and not isinstance(configuration, dict):
        raise StorageProfileError("Storage profile configuration must be an object")
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
    candidate = OrganizationStorageProfile(
        backend_type=backend,
        storage_key=key,
        configuration_json=dict(configuration or {}),
        organization_id=organization_id,
        status=status,
    )
    _target_for_profile(candidate)


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
        _validate_target(
            profile.backend_type,
            profile.storage_key,
            profile.configuration_json,
            organization_id,
            profile.status,
        )
        return profile
    if settings.organization_require_storage_profile:
        raise StorageProfileError(
            "Organization has no ACTIVE storage profile. Register and activate the laboratory artifact storage target before use."
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
    _validate_target(backend_type, storage_key, configuration, organization_id)
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
    _validate_target(
        profile.backend_type,
        profile.storage_key,
        profile.configuration_json,
        organization_id,
        profile.status,
    )
    _target_for_profile(profile)
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


def _store(backend_type: str, target: str, *, target_id: str | None = None):
    from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
    from backend.app.infrastructure.artifacts.store import ArtifactStore

    if backend_type == "FIREBASE_GCS":
        configured_targets = _configured_targets()
        target_config = configured_targets.get(target_id or "", {})
        app_name = None
        if target_id and target_id in configured_targets:
            project_id = target_config.get("project_id") or settings.firebase_project_id or ""
            stable_name = f"{target_id}\0{target}\0{project_id}\0{target_config.get('credentials_path', '')}"
            app_name = "siraloom-storage-" + hashlib.sha256(stable_name.encode()).hexdigest()[:20]
        return FirebaseArtifactStore(
            target,
            credentials_path=target_config.get("credentials_path"),
            project_id=target_config.get("project_id"),
            app_name=app_name,
            inherit_global_credentials=not bool(app_name),
        )
    if target_id and target_id != "__legacy_local__":
        root = Path(target).expanduser().resolve()
        if not root.is_dir():
            raise StorageProfileError(
                "Configured organization artifact target is missing or not a directory"
            )
        if not os.access(root, os.W_OK | os.X_OK):
            raise StorageProfileError(
                "Configured organization artifact target is not writable by the service"
            )
    return ArtifactStore(target)


def artifact_store_for_organization(db: Session, *, organization_id: UUID):
    backend, target_id, target = artifact_storage_target_for_organization(
        db, organization_id=organization_id
    )
    return _store(backend, target, target_id=target_id)


def artifact_store_for_uri(db: Session, *, organization_id: UUID, storage_uri: str):
    """Resolve a historical artifact only through a target assigned to its organization."""
    from backend.app.domain.local_uri import local_path_from_uri

    if not storage_uri.startswith(("file:", "gs://")):
        raise StorageProfileError("Artifact storage URI uses an unsupported backend")
    if (
        storage_uri.startswith("gs://")
        and (not settings.firebase_storage_enabled or not settings.firebase_storage_bucket)
        and not _configured_targets()
    ):
        raise StorageProfileError("Firebase Storage is not configured to read this artifact")
    profiles = list(
        db.scalars(
            select(OrganizationStorageProfile)
            .where(
                OrganizationStorageProfile.organization_id == organization_id,
                OrganizationStorageProfile.status.in_(("ACTIVE", "RETIRED")),
            )
            .order_by(OrganizationStorageProfile.version.desc())
        )
    )
    if not profiles:
        if _configured_targets():
            raise StorageProfileError(
                "Organization has no storage profile assigned to the configured deployment targets"
            )
        if settings.organization_require_storage_profile:
            raise StorageProfileError("Organization has no ACTIVE storage profile")
        # Legacy organizations have no profile and can only access the global store.
        if (
            storage_uri.startswith("gs://")
            and settings.firebase_storage_enabled
            and settings.firebase_storage_bucket
        ):
            bucket = settings.firebase_storage_bucket
            if urlsplit(storage_uri).netloc == bucket:
                return _store("FIREBASE_GCS", bucket)
        if storage_uri.startswith("file:") and settings.artifact_root:
            path = local_path_from_uri(storage_uri)
            root = Path(settings.artifact_root).expanduser().resolve()
            if path is not None and (path == root or root in path.parents):
                return _store("LOCAL_FILESYSTEM", str(root))
        raise StorageProfileError("Artifact URI is not assigned to this organization")

    targets = _configured_targets()
    matches = []
    retired_target_errors = []
    if not targets and all(
        not (profile.configuration_json or {}).get("target_id") for profile in profiles
    ):
        # Legacy single-target deployments may have historical files on either
        # globally configured adapter after changing the active profile.
        if (
            storage_uri.startswith("gs://")
            and settings.firebase_storage_enabled
            and settings.firebase_storage_bucket
        ):
            if urlsplit(storage_uri).netloc == settings.firebase_storage_bucket:
                return _store("FIREBASE_GCS", settings.firebase_storage_bucket)
        if storage_uri.startswith("file:") and settings.artifact_root:
            path = local_path_from_uri(storage_uri)
            root = Path(settings.artifact_root).expanduser().resolve()
            if path is not None and (path == root or root in path.parents):
                return _store("LOCAL_FILESYSTEM", str(root))
    if not storage_uri.startswith(("file:", "gs://")):
        raise StorageProfileError("Artifact storage URI uses an unsupported backend")
    for profile in profiles:
        try:
            _validate_target(
                profile.backend_type,
                profile.storage_key,
                profile.configuration_json,
                organization_id,
                profile.status,
            )
            target_id, target = _target_for_profile(profile)
        except StorageProfileError as exc:
            if profile.status == "ACTIVE":
                raise
            retired_target_errors.append(exc)
            continue
        if profile.backend_type == "FIREBASE_GCS":
            if storage_uri.startswith("gs://") and urlsplit(storage_uri).netloc == target:
                matches.append((profile.backend_type, target, target_id))
        else:
            path = local_path_from_uri(storage_uri) if storage_uri.startswith("file:") else None
            root = Path(target).expanduser().resolve()
            if path is not None and (path == root or root in path.parents):
                matches.append((profile.backend_type, target, target_id))
    if not matches:
        if retired_target_errors:
            raise StorageProfileError(
                "Historical artifact storage target is unavailable or no longer approved"
            ) from retired_target_errors[0]
        raise StorageProfileError("Artifact URI is not assigned to this organization")
    unique = set(matches)
    if len(unique) != 1:
        raise StorageProfileError("Artifact URI matches multiple organization storage targets")
    backend, target, target_id = unique.pop()
    return _store(backend, target, target_id=target_id)
