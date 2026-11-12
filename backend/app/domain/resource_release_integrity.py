"""Verification of immutable, checksum-pinned scientific source releases."""
from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.artifact_integrity import verify_artifact_file
from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.storage_profiles import artifact_store_for_uri
from backend.app.infrastructure.db.models import (
    Annotation, Evidence, PopulationObservation, Resource, ResourceReleaseArtifact, ResourceStaging,
)


def verify_resource_release_artifact(
    db: Session, artifact: ResourceReleaseArtifact,
) -> str:
    """Verify release identity and bytes immediately before scientific evidence use."""
    staging = db.get(ResourceStaging, artifact.resource_staging_id)
    if (
        staging is None or staging.status != "STAGED"
        or staging.resource_id != artifact.resource_id
        or staging.resource_version != artifact.resource_version
        or staging.destination_uri != artifact.storage_uri
        or staging.observed_sha256 != artifact.sha256
        or staging.observed_size_bytes != artifact.size_bytes
    ):
        raise ValueError("Source-release staging identity no longer matches its immutable snapshot.")
    path = local_path_from_uri(artifact.storage_uri)
    if path is not None:
        verify_artifact_file(path, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
    else:
        store = artifact_store_for_uri(
            db, organization_id=artifact.organization_id,
            storage_uri=artifact.storage_uri,
        )
        if not callable(getattr(store, "download_to_file", None)):
            raise ValueError("Source-release storage backend cannot independently verify bytes.")
        with tempfile.NamedTemporaryFile(prefix="siraloom-release-verify-", delete=False) as handle:
            staged = Path(handle.name)
        try:
            store.download_to_file(
                artifact.storage_uri, staged,
                expected_sha256=artifact.sha256,
                expected_size_bytes=artifact.size_bytes,
            )
            verify_artifact_file(staged, sha256=artifact.sha256, size_bytes=artifact.size_bytes)
        finally:
            staged.unlink(missing_ok=True)
    return (
        "VERIFIED"
        if artifact.integrity_status == "PUBLISHER_CHECKSUM_VERIFIED"
        else "CAPTURED"
    )


def find_verified_resource_release(
    db: Session, *, resource_id: UUID, resource_version: str,
) -> tuple[ResourceReleaseArtifact | None, str]:
    artifact = db.scalar(
        select(ResourceReleaseArtifact)
        .where(
            ResourceReleaseArtifact.resource_id == resource_id,
            ResourceReleaseArtifact.resource_version == resource_version,
        )
        .order_by(ResourceReleaseArtifact.verified_at.desc(), ResourceReleaseArtifact.id.desc())
        .limit(1)
    )
    if artifact is None:
        return None, "NOT_AVAILABLE"
    status = verify_resource_release_artifact(db, artifact)
    return artifact, status



def _verify_release_reference(
    db: Session, *, resource_id: UUID | None, artifact_id: UUID | None,
    digest: str | None, size_bytes: int | None, status: str,
) -> bool:
    resource = db.get(Resource, resource_id) if resource_id else None
    normalized = str(status or "NOT_AVAILABLE").upper()
    if normalized == "NOT_AVAILABLE":
        if (
            resource is not None
            and str(resource.access_method or "").upper() in {"LOCAL", "FILE", "LOCAL_ONLY"}
        ):
            raise ValueError("Local scientific evidence is missing its immutable source-release artifact.")
        if artifact_id is not None or digest is not None or size_bytes is not None:
            raise ValueError("Unverified source-release reference contains artifact identity or digest.")
        return False
    if normalized not in {"VERIFIED", "CAPTURED"}:
        raise ValueError(f"Unsupported source-release status: {normalized}.")
    if artifact_id is None or resource is None or not digest or size_bytes is None:
        raise ValueError("Source-release reference is incomplete.")
    artifact = db.get(ResourceReleaseArtifact, artifact_id)
    if (
        artifact is None or artifact.resource_id != resource.id
        or artifact.resource_version != resource.version
        or artifact.sha256 != digest or artifact.size_bytes != size_bytes
    ):
        raise ValueError("Source-release artifact identity, release, digest, or size was substituted.")
    actual_status = verify_resource_release_artifact(db, artifact)
    if actual_status != normalized:
        raise ValueError("Source-release verification status does not match its immutable artifact.")
    return True


def verify_annotation_source_release_reference(db: Session, annotation: Annotation) -> bool:
    return _verify_release_reference(
        db, resource_id=annotation.resource_id,
        artifact_id=annotation.source_release_artifact_id,
        digest=annotation.source_release_sha256,
        size_bytes=annotation.source_release_size_bytes,
        status=annotation.source_release_status,
    )


def verify_evidence_source_release_reference(db: Session, evidence: Evidence) -> bool:
    return _verify_release_reference(
        db, resource_id=evidence.resource_id,
        artifact_id=evidence.source_release_artifact_id,
        digest=evidence.source_release_sha256,
        size_bytes=evidence.source_release_size_bytes,
        status=evidence.source_release_status,
    )


def verify_population_source_release_reference(
    db: Session, observation: PopulationObservation,
) -> bool:
    return _verify_release_reference(
        db, resource_id=observation.resource_id,
        artifact_id=observation.source_release_artifact_id,
        digest=observation.source_release_sha256,
        size_bytes=observation.source_release_size_bytes,
        status=observation.source_release_status,
    )
