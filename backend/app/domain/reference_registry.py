"""GRCh38 reference-package registration and qualification lifecycle.

This module deliberately builds on the existing Resource registry and
ResourceQualification persistence model. It does not create a second registry.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.domain.reference_package import (
    REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION,
    REFERENCE_PACKAGE_RESOURCE_TYPE,
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    SUPPORTED_REFERENCE_PACKAGE_SCHEMA_VERSIONS,
    package_checksum as calculate_package_checksum,
)
from backend.app.domain.resource_qualification import QualificationResult, qualify_resource
from backend.app.domain.resources import (
    ResourceRegistryError,
    activate_resource_version,
    qualify_resource_version,
    register_resource_version,
)
from backend.app.infrastructure.db.models import Resource, ResourceStaging

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_MANIFEST_FIELDS = (
    "assembly_name",
    "assembly_accession",
    "reference_source",
    "sequence_scope",
    "fasta_path",
    "fai_path",
    "fasta_sha256",
    "fai_sha256",
    "contigs_sha256",
    "contigs",
)


class ReferenceRegistryError(ValueError):
    """Stable registration and lifecycle errors for reference packages."""

    def __init__(self, message: str, *, code: str = "REFERENCE_REGISTRY_INVALID"):
        super().__init__(message)
        self.code = code


def validate_reference_registration(
    manifest: dict[str, Any],
    *,
    genome_build: str,
    package_version: str,
    package_checksum: str,
) -> dict[str, Any]:
    """Validate the immutable package identity before it enters the registry.

    This is registration-time structural validation. File bytes are not trusted
    until qualify_reference_package_resource executes the full package validator.
    """
    if not isinstance(manifest, dict):
        raise ReferenceRegistryError("reference package manifest must be an object")
    schema = str(manifest.get("schema_version") or "")
    if schema not in SUPPORTED_REFERENCE_PACKAGE_SCHEMA_VERSIONS:
        raise ReferenceRegistryError(
            f"unsupported reference package schema {schema!r}",
            code="REFERENCE_PACKAGE_SCHEMA_UNSUPPORTED",
        )
    missing = [field for field in _REQUIRED_MANIFEST_FIELDS if manifest.get(field) in (None, "", [])]
    if missing:
        raise ReferenceRegistryError(
            "reference package manifest is missing: " + ", ".join(missing),
            code="REFERENCE_PACKAGE_MANIFEST_INCOMPLETE",
        )
    if str(manifest.get("contig_policy") or "") != "EXACT":
        raise ReferenceRegistryError(
            "reference packages must use exact contig identifiers; aliases are not implicit",
            code="REFERENCE_CONTIG_POLICY_INVALID",
        )
    if not genome_build.strip() or str(manifest.get("assembly_name")) != genome_build:
        raise ReferenceRegistryError(
            "assembly_name must exactly match the registered genome_build",
            code="REFERENCE_BUILD_IDENTITY_MISMATCH",
        )
    for field in ("fasta_sha256", "fai_sha256", "contigs_sha256"):
        if not _SHA256.fullmatch(str(manifest.get(field) or "").lower()):
            raise ReferenceRegistryError(
                f"{field} must be a 64-character SHA-256 digest",
                code="REFERENCE_MANIFEST_DIGEST_INVALID",
            )
    if not _SHA256.fullmatch(str(package_checksum or "").lower()):
        raise ReferenceRegistryError(
            "package_checksum must be a 64-character SHA-256 digest",
            code="REFERENCE_PACKAGE_CHECKSUM_INVALID",
        )
    if not package_version.strip():
        raise ReferenceRegistryError(
            "package_version is required",
            code="REFERENCE_PACKAGE_VERSION_REQUIRED",
        )
    expected_package_checksum = calculate_package_checksum(
        genome_build=genome_build,
        version=package_version,
        fasta_sha256=str(manifest["fasta_sha256"]),
        fai_sha256=str(manifest["fai_sha256"]),
        contigs_sha256=str(manifest["contigs_sha256"]),
        assembly_name=str(manifest["assembly_name"]),
        assembly_accession=str(manifest["assembly_accession"]),
        reference_source=str(manifest["reference_source"]),
        sequence_scope=str(manifest["sequence_scope"]),
        schema_version=schema,
        gzi_sha256=str(manifest.get("gzi_sha256") or "") or None,
    )
    if expected_package_checksum != package_checksum.lower():
        raise ReferenceRegistryError(
            "package checksum does not bind the supplied manifest and version",
            code="REFERENCE_PACKAGE_CHECKSUM_MISMATCH",
        )
    contigs = manifest.get("contigs")
    if not isinstance(contigs, list) or not contigs:
        raise ReferenceRegistryError(
            "reference package must declare a non-empty ordered contig manifest",
            code="REFERENCE_CONTIG_MANIFEST_INVALID",
        )
    seen: set[str] = set()
    for index, contig in enumerate(contigs):
        if not isinstance(contig, dict):
            raise ReferenceRegistryError(
                f"contig manifest entry {index} must be an object",
                code="REFERENCE_CONTIG_MANIFEST_INVALID",
            )
        name = str(contig.get("name") or "")
        length = contig.get("length")
        if not name or name in seen or not isinstance(length, int) or length <= 0:
            raise ReferenceRegistryError(
                f"contig manifest entry {index} has an invalid identifier or length",
                code="REFERENCE_CONTIG_MANIFEST_INVALID",
            )
        seen.add(name)
    if schema == REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION:
        if not manifest.get("gzi_path") or not _SHA256.fullmatch(str(manifest.get("gzi_sha256") or "").lower()):
            raise ReferenceRegistryError(
                "BGZF reference packages require a GZI path and SHA-256 digest",
                code="REFERENCE_GZI_REQUIRED",
            )
    if schema == REFERENCE_PACKAGE_SCHEMA_VERSION and (manifest.get("gzi_path") or manifest.get("gzi_sha256")):
        raise ReferenceRegistryError(
            "plain FASTA package schema 1.0 must not declare BGZF GZI assets",
            code="REFERENCE_PACKAGE_SCHEMA_INVALID",
        )
    return dict(manifest)


def register_reference_package(
    db: Session,
    *,
    name: str,
    provider: str,
    version: str,
    genome_build: str,
    manifest: dict[str, Any],
    package_checksum: str,
    source_contract: dict[str, Any],
    execution_contract: dict[str, Any],
    organization_id: UUID | None = None,
) -> tuple[Resource, bool]:
    """Register a reference release as CANDIDATE; never activate on registration."""
    identity = validate_reference_registration(
        manifest,
        genome_build=genome_build,
        package_version=version,
        package_checksum=package_checksum,
    )
    if not isinstance(source_contract, dict) or not isinstance(execution_contract, dict):
        raise ReferenceRegistryError(
            "source_contract and execution_contract must be objects",
            code="REFERENCE_PROVENANCE_REQUIRED",
        )
    metadata = {
        **identity,
        "source_contract": dict(source_contract),
        "execution": dict(execution_contract),
        "registry_contract": "siraloom.reference-registry.v1",
    }
    return register_resource_version(
        db,
        name=name,
        provider=provider,
        resource_type=REFERENCE_PACKAGE_RESOURCE_TYPE,
        version=version,
        genome_build=genome_build,
        access_method="LOCAL",
        license_text=None,
        checksum=package_checksum,
        location=str(identity["fasta_path"]),
        population_definition=None,
        metadata_json=metadata,
        organization_id=organization_id,
        initial_status="CANDIDATE",
    )


def qualify_reference_package_resource(
    db: Session,
    *,
    resource_id: UUID,
    staging: ResourceStaging,
    qualification_version: str,
    qualified_by: UUID | None = None,
) -> tuple[QualificationResult, Any]:
    """Execute byte-level qualification and persist the resulting evidence."""
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ReferenceRegistryError(
            f"reference package {resource_id} was not found",
            code="REFERENCE_PACKAGE_NOT_FOUND",
        )
    if resource.resource_type != REFERENCE_PACKAGE_RESOURCE_TYPE:
        raise ReferenceRegistryError(
            "resource is not a REFERENCE_PACKAGE",
            code="REFERENCE_RESOURCE_TYPE_INVALID",
        )
    if resource.status not in {"CANDIDATE", "QUALIFIED"}:
        raise ReferenceRegistryError(
            f"reference package cannot be qualified from status {resource.status!r}",
            code="REFERENCE_PACKAGE_STATE_INVALID",
        )
    result = qualify_resource(
        resource,
        staging=staging,
        qualification_version=qualification_version,
    )
    persisted = qualify_resource_version(
        db,
        resource_id=resource_id,
        qualification_version=qualification_version,
        checks=result.checks,
        qualified_by=qualified_by,
    )
    return result, persisted


def activate_reference_package_resource(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str,
) -> Resource:
    """Activate only the exact release with a persisted successful qualification."""
    resource = db.get(Resource, resource_id)
    if resource is None or resource.resource_type != REFERENCE_PACKAGE_RESOURCE_TYPE:
        raise ReferenceRegistryError(
            "reference package was not found",
            code="REFERENCE_PACKAGE_NOT_FOUND",
        )
    return activate_resource_version(
        db,
        resource_id=resource_id,
        qualification_version=qualification_version,
    )
