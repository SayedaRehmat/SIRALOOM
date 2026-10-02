"""Governed scientific-resource staging and integrity lifecycle.

Discovery never activates a resource. Durable staging state records storage
preflight, acquisition attempts, integrity verification, and failures before
the existing qualification/approval gates can activate execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from datetime import datetime, timezone
import os
import shutil
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Resource, ResourceStaging


class ResourceStagingError(RuntimeError):
    """A governed staging failure with an explicit recovery classification."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "STAGING_FAILED",
        outcome: str = "RESOURCE_INVALID",
        retryable: bool = False,
    ):
        super().__init__(message)
        self.code = code
        self.outcome = outcome
        self.retryable = retryable


def staging_recovery_decision(
    row: ResourceStaging,
    *,
    fallback_available: bool = False,
    lab_action_required: bool = False,
):
    """Return the existing workflow decision contract for a staging failure.

    Staging is resource lifecycle infrastructure rather than an analysis step, so
    this helper does not persist a workflow decision or perform fallback itself.
    It gives the owning orchestrator one explicit, governed next action.
    """
    from backend.app.domain.workflow_decision import (
        OutcomeKind,
        decide_workflow_outcome,
    )

    outcome = OutcomeKind(str(row.metadata_json.get("recovery_outcome", "RESOURCE_INVALID")).upper())
    return decide_workflow_outcome(
        outcome,
        code=row.error_code or "STAGING_FAILED",
        message=row.error_message or "Resource staging failed.",
        retryable=bool(row.metadata_json.get("retryable", False)),
        fallback_available=fallback_available,
        lab_action_required=lab_action_required,
    )


@dataclass(frozen=True)
class StagedResource:
    source: str
    local_path: str
    sha256: str
    size_bytes: int
    metadata: dict[str, object]


class ResourceStager(Protocol):
    def stage(self, descriptor: dict[str, object], destination: Path) -> StagedResource:
        ...


@dataclass(frozen=True)
class StoragePreflight:
    destination: Path
    parent_exists: bool
    parent_writable: bool
    available_bytes: int
    required_bytes: int | None

    @property
    def passed(self) -> bool:
        return (
            self.parent_exists
            and self.parent_writable
            and (
                self.required_bytes is None
                or self.available_bytes >= self.required_bytes
            )
        )


_ALLOWED_TRANSITIONS = {
    "DISCOVERED": {"READY_TO_STAGE", "PREFLIGHT_FAILED", "INVALID"},
    "READY_TO_STAGE": {"STAGING", "PREFLIGHT_FAILED", "INVALID"},
    "STAGING": {"STAGED", "INTEGRITY_FAILED", "INVALID"},
    "STAGED": {"INTEGRITY_FAILED", "REMOVED"},
    "PREFLIGHT_FAILED": {"READY_TO_STAGE", "REMOVED"},
    "INTEGRITY_FAILED": {"READY_TO_STAGE", "REMOVED"},
    "INVALID": {"REMOVED"},
    "REMOVED": set(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_staged_resource(path: Path, expected_sha256: str) -> StagedResource:
    if not path.is_file():
        raise ResourceStagingError("staged resource file does not exist")
    actual = _sha256(path)
    if actual != expected_sha256.lower():
        raise ResourceStagingError(
            f"staged resource checksum mismatch: expected {expected_sha256}, got {actual}"
        )
    return StagedResource(
        source="verified-local-staging",
        local_path=str(path),
        sha256=actual,
        size_bytes=path.stat().st_size,
        metadata={"integrity": "SHA-256"},
    )


def stage_and_verify(
    stager: ResourceStager,
    descriptor: dict[str, object],
    destination: Path,
    expected_sha256: str,
) -> StagedResource:
    staged = stager.stage(descriptor, destination)
    verified = verify_staged_resource(Path(staged.local_path), expected_sha256)
    return StagedResource(
        source=staged.source,
        local_path=verified.local_path,
        sha256=verified.sha256,
        size_bytes=verified.size_bytes,
        metadata={**staged.metadata, **verified.metadata},
    )


def storage_preflight(
    destination: str | Path,
    *,
    required_bytes: int | None = None,
) -> StoragePreflight:
    path = Path(destination)
    parent = path.parent
    exists = parent.is_dir()
    writable = exists and os.access(parent, os.W_OK)
    available = shutil.disk_usage(parent).free if exists else 0
    return StoragePreflight(path, exists, writable, available, required_bytes)


def create_staging_candidate(
    db: Session,
    *,
    resource: Resource,
    source_uri: str,
    destination_uri: str,
    storage_backend: str = "LOCAL_FILESYSTEM",
    expected_sha256: str | None = None,
    expected_size_bytes: int | None = None,
    staging_key: str | None = None,
    metadata: dict | None = None,
) -> ResourceStaging:
    if not source_uri.strip() or not destination_uri.strip():
        raise ValueError("source_uri and destination_uri are required")
    if resource.organization_id is not None and not storage_backend.startswith("ORGANIZATION_"):
        raise ResourceStagingError(
            "organization-managed resources require organization-managed staging storage"
        )
    if resource.location and str(resource.location) != destination_uri:
        raise ResourceStagingError(
            "staging destination does not match the resource execution location"
        )
    if resource.access_method.upper() in {"LOCAL", "FILE", "LOCAL_ONLY"} and not resource.location:
        resource.location = destination_uri
        db.add(resource)
        db.flush()
    key = staging_key or f"{resource.provider}:{resource.version}:{destination_uri}"
    existing = db.scalar(
        select(ResourceStaging).where(
            ResourceStaging.resource_id == resource.id,
            ResourceStaging.resource_version == resource.version,
            ResourceStaging.staging_key == key,
        )
    )
    if existing is not None:
        return existing
    row = ResourceStaging(
        id=uuid4(),
        resource_id=resource.id,
        resource_version=resource.version,
        staging_key=key,
        source_uri=source_uri,
        destination_uri=destination_uri,
        storage_backend=storage_backend,
        status="DISCOVERED",
        expected_sha256=expected_sha256.lower() if expected_sha256 else None,
        expected_size_bytes=expected_size_bytes,
        metadata_json=metadata or {},
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


def transition_staging(
    db: Session,
    row: ResourceStaging,
    status: str,
    *,
    error_code: str | None = None,
    error_message: str | None = None,
) -> ResourceStaging:
    status = status.upper()
    if status not in _ALLOWED_TRANSITIONS:
        raise ValueError(f"unsupported staging status {status!r}")
    if status != row.status and status not in _ALLOWED_TRANSITIONS[row.status]:
        raise ResourceStagingError(f"invalid staging transition {row.status} -> {status}")
    row.status = status
    row.error_code = error_code
    row.error_message = error_message
    row.updated_at = _now()
    if status == "STAGING":
        row.started_at = row.started_at or _now()
        row.attempt += 1
    if status in {"STAGED", "INTEGRITY_FAILED", "INVALID", "REMOVED", "PREFLIGHT_FAILED"}:
        row.completed_at = _now()
    db.add(row)
    db.flush()
    return row


def prepare_staging(db: Session, row: ResourceStaging) -> ResourceStaging:
    preflight = storage_preflight(
        row.destination_uri,
        required_bytes=row.expected_size_bytes,
    )
    row.metadata_json = {
        **dict(row.metadata_json or {}),
        "storage_preflight": {
            "parent_exists": preflight.parent_exists,
            "parent_writable": preflight.parent_writable,
            "available_bytes": preflight.available_bytes,
            "required_bytes": preflight.required_bytes,
            "passed": preflight.passed,
        },
    }
    if not preflight.passed:
        return transition_staging(
            db,
            row,
            "PREFLIGHT_FAILED",
            error_code="STORAGE_PREFLIGHT_FAILED",
            error_message="staging destination is missing, unwritable, or lacks required free space",
        )
    return transition_staging(db, row, "READY_TO_STAGE")


def stage_local_artifact(
    db: Session,
    row: ResourceStaging,
    *,
    source_path: str | Path,
) -> ResourceStaging:
    """Atomically stage an explicit local artifact and verify its declared integrity.

    Arbitrary URL fetching is intentionally excluded from this primitive. Remote
    acquisition requires a dedicated adapter with network, credentials, and
    publisher allow-list controls.
    """
    source = Path(source_path)
    destination = Path(row.destination_uri)
    if not source.is_file():
        return transition_staging(
            db,
            row,
            "INVALID",
            error_code="SOURCE_ARTIFACT_MISSING",
            error_message=f"source artifact does not exist: {source}",
        )
    if row.status == "DISCOVERED":
        prepare_staging(db, row)
    if row.status != "READY_TO_STAGE":
        raise ResourceStagingError(f"resource staging is not ready: {row.status}")
    if source.resolve() == destination.resolve():
        raise ResourceStagingError("source and destination must differ")

    transition_staging(db, row, "STAGING")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.staging-{row.id}")
    try:
        shutil.copyfile(source, temporary)
        observed_size = temporary.stat().st_size
        observed_sha256 = _sha256(temporary)
        row.observed_size_bytes = observed_size
        row.observed_sha256 = observed_sha256

        if row.expected_size_bytes is not None and observed_size != row.expected_size_bytes:
            temporary.unlink(missing_ok=True)
            return transition_staging(
                db, row, "INTEGRITY_FAILED",
                error_code="SIZE_MISMATCH",
                error_message=f"expected {row.expected_size_bytes} bytes, observed {observed_size}",
            )
        if row.expected_sha256 is not None and observed_sha256 != row.expected_sha256:
            temporary.unlink(missing_ok=True)
            return transition_staging(
                db, row, "INTEGRITY_FAILED",
                error_code="CHECKSUM_MISMATCH",
                error_message="staged SHA-256 does not match the declared release checksum",
            )

        os.replace(temporary, destination)
        row.metadata_json = {
            **dict(row.metadata_json or {}),
            "integrity": "SHA256_VERIFIED" if row.expected_sha256 else "SHA256_COMPUTED",
        }
        return transition_staging(db, row, "STAGED")
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        transition_staging(
            db,
            row,
            "INTEGRITY_FAILED",
            error_code="STAGING_FAILED",
            error_message=str(exc),
        )
        raise


def stage_resource_release(
    db: Session,
    row: ResourceStaging,
    *,
    local_source_path: str | Path | None = None,
    max_remote_bytes: int = 5 * 1024 * 1024 * 1024,
    timeout_seconds: float = 30.0,
) -> ResourceStaging:
    """Execute the governed staging path selected by the registered resource.

    Remote acquisition is permitted only for a validated PUBLIC source contract
    with an HTTPS artifact and a published SHA-256. Authenticated, licensed, or
    local-only resources require their provider-specific execution path.
    """
    resource = db.get(Resource, row.resource_id)
    if resource is None:
        raise ResourceStagingError("staging resource does not exist")
    if row.resource_version != resource.version:
        raise ResourceStagingError("staging resource version does not match registered resource")

    access_method = str(resource.access_method or "").strip().upper()
    if local_source_path is not None:
        if access_method not in {"LOCAL", "FILE", "LOCAL_ONLY"}:
            raise ResourceStagingError(
                f"local source staging is not permitted for access_method {access_method!r}"
            )
        return stage_local_artifact(db, row, source_path=local_source_path)

    if access_method != "HTTPS":
        raise ResourceStagingError(
            f"generic remote staging supports HTTPS resources only; got {access_method!r}"
        )

    contract = dict((resource.metadata_json or {}).get("source_contract") or {})
    if str(contract.get("access_mode") or "").upper() != "PUBLIC":
        raise ResourceStagingError(
            "generic remote staging requires a PUBLIC source contract; "
            "authenticated or license-controlled resources require a provider-specific adapter"
        )
    artifact_url = str(contract.get("artifact_url") or "").strip()
    if artifact_url != row.source_uri:
        raise ResourceStagingError(
            "staging source does not match the registered source contract artifact"
        )
    if str(contract.get("checksum_status") or "").upper() != "PUBLISHED_AND_VERIFIED":
        raise ResourceStagingError(
            "generic remote staging requires a published and verified source checksum"
        )
    if not row.expected_sha256:
        raise ResourceStagingError(
            "generic remote staging requires the concrete release SHA-256"
        )

    from backend.app.domain.resource_remote_staging import stage_remote_artifact

    from urllib.parse import urlparse
    parsed = urlparse(artifact_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ResourceStagingError("source contract artifact must be an absolute HTTPS URL")
    allowed_hosts = {parsed.hostname.lower().rstrip(".")}
    return stage_remote_artifact(
        db,
        row,
        allowed_hosts=allowed_hosts,
        max_bytes=max_remote_bytes,
        timeout_seconds=timeout_seconds,
    )
