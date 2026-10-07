"""Governed coordinator for the scientific-resource release lifecycle.

This module is the orchestration boundary between durable discovery, staging,
technical qualification, and later human/organization approval. It deliberately
stops at QUALIFIED; activation/adoption remains a separate governed decision.

The coordinator never replaces an active release when a new release fails.
Transient staging failures are returned as RETRY decisions, unavailable releases
remain explicit, and integrity/policy failures require governed action.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.resource_qualification import (
    QualificationResult,
    qualify_resource,
)
from backend.app.domain.resource_staging import (
    ResourceStagingError,
    prepare_staging,
    stage_resource_release,
    staging_recovery_decision,
)
from backend.app.domain.resources import qualify_resource_version
from backend.app.infrastructure.db.models import Resource, ResourceQualification, ResourceStaging


@dataclass(frozen=True)
class ResourceLifecycleResult:
    resource: Resource
    staging: ResourceStaging | None
    qualification: ResourceQualification | None
    qualification_result: QualificationResult | None
    decision: Any | None
    stage: str


def _latest_staging(db: Session, resource: Resource) -> ResourceStaging | None:
    return db.scalar(
        select(ResourceStaging)
        .where(
            ResourceStaging.resource_id == resource.id,
            ResourceStaging.resource_version == resource.version,
        )
        .order_by(ResourceStaging.created_at.desc())
    )


def _bind_verified_staging_location(
    db: Session,
    resource: Resource,
    staging: ResourceStaging,
) -> None:
    """Bind the verified local artifact as the execution location.

    The registered source contract remains authoritative for publisher identity
    and remote artifact provenance. Resource.location becomes the concrete local
    execution artifact only after STAGED integrity verification succeeds.
    """
    destination = str(Path(staging.destination_uri))
    if resource.location != destination:
        resource.location = destination
        db.add(resource)
        db.flush()


def _persist_qualification(
    db: Session,
    resource: Resource,
    result: QualificationResult,
    *,
    qualified_by: UUID | None,
) -> ResourceQualification:
    return qualify_resource_version(
        db,
        resource_id=resource.id,
        qualification_version=result.qualification_version,
        checks=result.checks,
        qualified_by=qualified_by,
    )


def run_resource_lifecycle(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str = "siraloom-resource-qualification-v1",
    qualified_by: UUID | None = None,
    local_source_path: str | Path | None = None,
    max_remote_bytes: int = 5 * 1024 * 1024 * 1024,
    timeout_seconds: float = 30.0,
) -> ResourceLifecycleResult:
    """Advance one discovered release through staging and qualification.

    The operation is intentionally resumable:
    - STAGED releases are not downloaded again.
    - an existing successful qualification is reused.
    - PREFLIGHT_FAILED and INTEGRITY_FAILED staging rows may be retried through
      the existing staging state machine.
    - failures are classified through the existing workflow decision contract.
    - no approval or activation occurs here.
    """
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ValueError("resource not found")

    staging = _latest_staging(db, resource)
    if staging is None:
        return ResourceLifecycleResult(
            resource=resource,
            staging=None,
            qualification=None,
            qualification_result=None,
            decision=None,
            stage="WAITING_FOR_STAGING_CONFIGURATION",
        )

    qualification = db.scalar(
        select(ResourceQualification).where(
            ResourceQualification.resource_id == resource.id,
            ResourceQualification.qualification_version == qualification_version.strip(),
        )
    )
    if qualification is not None and qualification.status == "QUALIFIED":
        return ResourceLifecycleResult(
            resource=resource,
            staging=staging,
            qualification=qualification,
            qualification_result=None,
            decision=None,
            stage="QUALIFIED",
        )

    if staging.status != "STAGED":
        if staging.status in {"PREFLIGHT_FAILED", "INTEGRITY_FAILED"}:
            prepare_staging(db, staging)
        if staging.status in {"DISCOVERED"}:
            prepare_staging(db, staging)

        if staging.status == "READY_TO_STAGE":
            try:
                staging = stage_resource_release(
                    db,
                    staging,
                    local_source_path=local_source_path,
                    max_remote_bytes=max_remote_bytes,
                    timeout_seconds=timeout_seconds,
                )
            except ResourceStagingError:
                decision = staging_recovery_decision(staging)
                return ResourceLifecycleResult(
                    resource=resource,
                    staging=staging,
                    qualification=qualification,
                    qualification_result=None,
                    decision=decision,
                    stage="STAGING_RECOVERY",
                )

        if staging.status != "STAGED":
            decision = staging_recovery_decision(staging)
            return ResourceLifecycleResult(
                resource=resource,
                staging=staging,
                qualification=qualification,
                qualification_result=None,
                decision=decision,
                stage="STAGING_RECOVERY",
            )

    _bind_verified_staging_location(db, resource, staging)

    result = qualify_resource(
        resource,
        staging=staging,
        qualification_version=qualification_version,
    )
    qualification = _persist_qualification(
        db,
        resource,
        result,
        qualified_by=qualified_by,
    )

    if result.passed:
        return ResourceLifecycleResult(
            resource=resource,
            staging=staging,
            qualification=qualification,
            qualification_result=result,
            decision=None,
            stage="QUALIFIED",
        )

    return ResourceLifecycleResult(
        resource=resource,
        staging=staging,
        qualification=qualification,
        qualification_result=result,
        decision=None,
        stage="QUALIFICATION_BLOCKED",
    )
