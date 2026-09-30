from __future__ import annotations

import hashlib
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Resource

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_TYPES = frozenset({"REFERENCE", "POPULATION", "ANNOTATION", "EVIDENCE", "ACMG_RULE"})


class ResourceRegistryError(ValueError):
    pass


def _normalize_checksum(checksum: str | None) -> str | None:
    if checksum is None or not checksum.strip():
        return None
    value = checksum.strip().lower()
    if not _SHA256_RE.fullmatch(value):
        raise ResourceRegistryError("checksum must be a 64-character SHA-256 hex digest")
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
) -> tuple[Resource, bool]:
    """Register an immutable scientific resource version.

    The registry is versioned: an existing resource row is never mutated to
    represent a new release. A new version/checksum becomes the sole ACTIVE
    version for the same resource identity. Re-registering the same identity
    is idempotent and returns the existing row.
    """
    normalized_type = resource_type.strip().upper()
    if normalized_type not in _ALLOWED_TYPES:
        raise ResourceRegistryError(
            f"unsupported resource_type '{resource_type}'; expected one of {sorted(_ALLOWED_TYPES)}"
        )

    values = {
        "name": name.strip(),
        "provider": provider.strip(),
        "resource_type": normalized_type,
        "version": version.strip(),
        "genome_build": genome_build.strip() if genome_build else None,
        "access_method": access_method.strip(),
        "license_text": license_text,
        "checksum": _normalize_checksum(checksum),
        "location": location,
        "population_definition": population_definition,
        "metadata_json": metadata_json or {},
    }
    for field in ("name", "provider", "version", "access_method"):
        if not values[field]:
            raise ResourceRegistryError(f"{field} is required")

    existing = db.scalar(
        select(Resource).where(
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

    active_rows = db.scalars(
        select(Resource).where(
            Resource.name == values["name"],
            Resource.provider == values["provider"],
            Resource.resource_type == values["resource_type"],
            Resource.genome_build == values["genome_build"],
            Resource.status == "ACTIVE",
        )
    ).all()
    for row in active_rows:
        row.status = "SUPERSEDED"

    resource = Resource(
        id=uuid4(),
        name=values["name"],
        provider=values["provider"],
        resource_type=values["resource_type"],
        version=values["version"],
        genome_build=values["genome_build"],
        access_method=values["access_method"],
        license_text=values["license_text"],
        checksum=values["checksum"],
        location=values["location"],
        status="ACTIVE",
        population_definition=values["population_definition"],
        metadata_json=values["metadata_json"],
    )
    db.add(resource)
    db.flush()
    return resource, True
