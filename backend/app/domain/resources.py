from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Resource, ResourceQualification

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_TYPES = frozenset({
    "REFERENCE", "REFERENCE_PACKAGE", "POPULATION", "ANNOTATION",
    "EVIDENCE", "ACMG_RULE",
})
RESOURCE_STATUSES = frozenset({
    "CANDIDATE", "QUALIFIED", "ACTIVE", "SUPERSEDED", "REJECTED", "QUARANTINED",
})


class ResourceRegistryError(ValueError):
    pass


def _normalize_checksum(checksum: str | None) -> str | None:
    if checksum is None or not checksum.strip():
        return None
    value = checksum.strip().lower()
    if not _SHA256_RE.fullmatch(value):
        raise ResourceRegistryError("checksum must be a 64-character SHA-256 hex digest")
    return value


def _validate_status(status: str) -> str:
    value = status.strip().upper()
    if value not in RESOURCE_STATUSES:
        raise ResourceRegistryError(
            f"unsupported resource status '{status}'; expected one of {sorted(RESOURCE_STATUSES)}"
        )
    return value


def register_resource_version(
    db: Session,
    *,
    name: str,
    provider: str,
    resource_type: str,
    version: str,
    genome_build: str | None,
    access_method: str,
    license_text: str | None,
    checksum: str | None,
    location: str | None,
    population_definition: dict | None,
    metadata_json: dict | None = None,
    organization_id: UUID | None = None,
    initial_status: str = "ACTIVE",
) -> tuple[Resource, bool]:
    """Register an immutable resource version.

    Existing callers may continue registering trusted resources as ACTIVE.
    Automated discovery should use CANDIDATE; candidates can only become
    production resources after an explicit qualification and activation step.
    """
    normalized_type = resource_type.strip().upper()
    if normalized_type not in _ALLOWED_TYPES:
        raise ResourceRegistryError(
            f"unsupported resource_type '{resource_type}'; expected one of {sorted(_ALLOWED_TYPES)}"
        )
    status = _validate_status(initial_status)

    values = {
        "organization_id": organization_id,
        "name": name.strip(),
        "provider": provider.strip(),
        "resource_type": normalized_type,
        "version": version.strip(),
        "genome_build": genome_build.strip() if genome_build else None,
        "access_method": access_method.strip(),
        "license_text": license_text,
        "checksum": _normalize_checksum(checksum),
        "location": location,
        "status": status,
        "population_definition": population_definition,
        "metadata_json": metadata_json or {},
    }
    for field in ("name", "provider", "version", "access_method"):
        if not values[field]:
            raise ResourceRegistryError(f"{field} is required")

    existing = db.scalar(
        select(Resource).where(
            Resource.organization_id == values["organization_id"],
            Resource.name == values["name"],
            Resource.provider == values["provider"],
            Resource.resource_type == values["resource_type"],
            Resource.version == values["version"],
            Resource.genome_build == values["genome_build"],
            Resource.checksum == values["checksum"],
        ).limit(1)
    )
    if existing:
        return existing, False

    if status == "ACTIVE":
        _supersede_active_identity(
            db,
            organization_id=values["organization_id"],
            name=values["name"],
            provider=values["provider"],
            resource_type=values["resource_type"],
            genome_build=values["genome_build"],
        )

    resource = Resource(
        id=uuid4(),
        **values,
    )
    db.add(resource)
    db.flush()
    return resource, True


def _supersede_active_identity(
    db: Session,
    *,
    organization_id: UUID | None,
    name: str,
    provider: str,
    resource_type: str,
    genome_build: str | None,
) -> None:
    active_rows = db.scalars(
        select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.name == name,
            Resource.provider == provider,
            Resource.resource_type == resource_type,
            Resource.genome_build == genome_build,
            Resource.status == "ACTIVE",
        )
    ).all()
    for row in active_rows:
        row.status = "SUPERSEDED"


def qualify_resource_version(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str,
    checks: dict,
    qualified_by: UUID | None,
) -> ResourceQualification:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if resource.status not in {"CANDIDATE", "QUALIFIED"}:
        raise ResourceRegistryError(
            f"resource status {resource.status!r} cannot be qualified"
        )
    if not qualification_version.strip():
        raise ResourceRegistryError("qualification_version is required")
    if not isinstance(checks, dict) or not checks.get("passed"):
        raise ResourceRegistryError(
            "qualification requires checks.passed=true"
        )

    qualification = db.scalar(
        select(ResourceQualification).where(
            ResourceQualification.resource_id == resource_id,
            ResourceQualification.qualification_version == qualification_version.strip(),
        )
    )
    if qualification is None:
        qualification = ResourceQualification(
            id=uuid4(),
            resource_id=resource_id,
            qualification_version=qualification_version.strip(),
            status="QUALIFIED",
            checks_json=checks,
            qualified_by=qualified_by,
            qualified_at=datetime.now(timezone.utc),
        )
        db.add(qualification)
    else:
        qualification.status = "QUALIFIED"
        qualification.checks_json = checks
        qualification.qualified_by = qualified_by
        qualification.qualified_at = datetime.now(timezone.utc)

    resource.status = "QUALIFIED"
    db.flush()
    return qualification


def activate_resource_version(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str,
) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if resource.status != "QUALIFIED":
        raise ResourceRegistryError(
            "only QUALIFIED resources can be activated"
        )

    qualification = db.scalar(
        select(ResourceQualification).where(
            ResourceQualification.resource_id == resource_id,
            ResourceQualification.qualification_version == qualification_version.strip(),
            ResourceQualification.status == "QUALIFIED",
        )
    )
    if qualification is None:
        raise ResourceRegistryError(
            "matching successful qualification is required before activation"
        )

    _supersede_active_identity(
        db,
        organization_id=resource.organization_id,
        name=resource.name,
        provider=resource.provider,
        resource_type=resource.resource_type,
        genome_build=resource.genome_build,
    )
    resource.status = "ACTIVE"
    db.flush()
    return resource
