from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from backend.app.infrastructure.db.models import Resource

REFERENCE_PACKAGE_SCHEMA_VERSION = "1.0"
REFERENCE_PACKAGE_RESOURCE_TYPE = "REFERENCE_PACKAGE"
REFERENCE_PACKAGE_STATUS = "ACTIVE"
CONTIG_POLICY_EXACT = "EXACT"


class ReferencePackageError(ValueError):
    """Stable, actionable failures for the authoritative reference package contract."""

    def __init__(self, message: str, *, code: str = "REFERENCE_PACKAGE_INVALID"):
        super().__init__(message)
        self.code = code


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contigs_from_fai(fai_path: str | Path) -> list[dict[str, int | str]]:
    entries: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for line_no, line in enumerate(Path(fai_path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) < 5:
            raise ReferencePackageError(
                f"Malformed FASTA index at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            )
        name = fields[0]
        if name in seen:
            raise ReferencePackageError(
                f"Duplicate contig {name!r} in FASTA index.",
                code="REFERENCE_FAI_INVALID",
            )
        try:
            length = int(fields[1])
            offset = int(fields[2])
            line_bases = int(fields[3])
            line_width = int(fields[4])
        except ValueError as exc:
            raise ReferencePackageError(
                f"Non-numeric FASTA index field at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            ) from exc
        if length <= 0 or offset < 0 or line_bases <= 0 or line_width < line_bases:
            raise ReferencePackageError(
                f"Invalid FASTA index geometry at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            )
        entries.append({"name": name, "length": length})
        seen.add(name)
    if not entries:
        raise ReferencePackageError(
            "Reference FASTA index contains no contigs.",
            code="REFERENCE_FAI_INVALID",
        )
    return entries


def contig_manifest_sha256(contigs: list[dict[str, int | str]]) -> str:
    payload = json.dumps(contigs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def package_checksum(
    *,
    genome_build: str,
    version: str,
    fasta_sha256: str,
    fai_sha256: str,
    contigs_sha256: str,
) -> str:
    manifest = {
        "schema_version": REFERENCE_PACKAGE_SCHEMA_VERSION,
        "genome_build": genome_build,
        "version": version,
        "fasta_sha256": fasta_sha256,
        "fai_sha256": fai_sha256,
        "contigs_sha256": contigs_sha256,
        "contig_policy": CONTIG_POLICY_EXACT,
    }
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_reference_package(
    resource: Resource,
    *,
    expected_genome_build: str,
) -> dict:
    if resource.resource_type != REFERENCE_PACKAGE_RESOURCE_TYPE:
        raise ReferencePackageError(
            f"Resource {resource.id} is not a reference package.",
            code="REFERENCE_PACKAGE_INVALID",
        )
    if resource.status != REFERENCE_PACKAGE_STATUS:
        raise ReferencePackageError(
            f"Reference package {resource.name!r} is not ACTIVE (status={resource.status!r}).",
            code="REFERENCE_PACKAGE_NOT_ACTIVE",
        )
    if resource.genome_build != expected_genome_build:
        raise ReferencePackageError(
            f"Reference package build mismatch: analysis requires {expected_genome_build}, "
            f"package declares {resource.genome_build}.",
            code="REFERENCE_BUILD_MISMATCH",
        )
    if not resource.version:
        raise ReferencePackageError(
            "Reference package version is missing.",
            code="REFERENCE_PACKAGE_INVALID",
        )
    metadata = dict(resource.metadata_json or {})
    if metadata.get("schema_version") != REFERENCE_PACKAGE_SCHEMA_VERSION:
        raise ReferencePackageError(
            f"Unsupported reference package schema: {metadata.get('schema_version')!r}.",
            code="REFERENCE_PACKAGE_INVALID",
        )
    if metadata.get("contig_policy") != CONTIG_POLICY_EXACT:
        raise ReferencePackageError(
            "Reference package must declare contig_policy=EXACT; implicit contig aliases are forbidden.",
            code="REFERENCE_CONTIG_POLICY_INVALID",
        )

    fasta_path = Path(str(metadata.get("fasta_path") or ""))
    fai_path = Path(str(metadata.get("fai_path") or ""))
    if not fasta_path.is_file():
        raise ReferencePackageError(
            f"Reference FASTA is missing: {fasta_path}",
            code="REFERENCE_PACKAGE_NOT_FOUND",
        )
    if not fai_path.is_file():
        raise ReferencePackageError(
            f"Reference FASTA index is missing: {fai_path}",
            code="REFERENCE_PACKAGE_NOT_FOUND",
        )

    actual_fasta_sha = sha256_file(fasta_path)
    actual_fai_sha = sha256_file(fai_path)
    expected_fasta_sha = str(metadata.get("fasta_sha256") or "")
    expected_fai_sha = str(metadata.get("fai_sha256") or "")
    if actual_fasta_sha != expected_fasta_sha:
        raise ReferencePackageError(
            f"Reference FASTA checksum mismatch: expected {expected_fasta_sha}, got {actual_fasta_sha}.",
            code="REFERENCE_CHECKSUM_MISMATCH",
        )
    if actual_fai_sha != expected_fai_sha:
        raise ReferencePackageError(
            f"Reference FAI checksum mismatch: expected {expected_fai_sha}, got {actual_fai_sha}.",
            code="REFERENCE_CHECKSUM_MISMATCH",
        )

    contigs = contigs_from_fai(fai_path)
    actual_contigs_sha = contig_manifest_sha256(contigs)
    expected_contigs_sha = str(metadata.get("contigs_sha256") or "")
    if actual_contigs_sha != expected_contigs_sha:
        raise ReferencePackageError(
            "Reference contig manifest checksum mismatch.",
            code="REFERENCE_CONTIG_MANIFEST_MISMATCH",
        )

    expected_package_checksum = package_checksum(
        genome_build=expected_genome_build,
        version=resource.version,
        fasta_sha256=actual_fasta_sha,
        fai_sha256=actual_fai_sha,
        contigs_sha256=actual_contigs_sha,
    )
    if not resource.checksum or resource.checksum != expected_package_checksum:
        raise ReferencePackageError(
            "Reference package identity checksum mismatch.",
            code="REFERENCE_PACKAGE_CHECKSUM_MISMATCH",
        )

    declared_contigs = metadata.get("contigs")
    if declared_contigs != contigs:
        raise ReferencePackageError(
            "Reference package contig manifest does not match the FASTA index.",
            code="REFERENCE_CONTIG_MANIFEST_MISMATCH",
        )

    return {
        "resource_id": str(resource.id),
        "name": resource.name,
        "provider": resource.provider,
        "version": resource.version,
        "genome_build": resource.genome_build,
        "fasta_path": str(fasta_path),
        "fai_path": str(fai_path),
        "fasta_sha256": actual_fasta_sha,
        "fai_sha256": actual_fai_sha,
        "contigs_sha256": actual_contigs_sha,
        "package_checksum": expected_package_checksum,
        "contig_policy": CONTIG_POLICY_EXACT,
        "contigs": contigs,
    }


def load_reference_package(
    db,
    *,
    resource_id: str | UUID | None,
    expected_genome_build: str,
) -> dict:
    if not resource_id:
        raise ReferencePackageError(
            "No authoritative reference package is selected for this analysis.",
            code="REFERENCE_PACKAGE_NOT_CONFIGURED",
        )
    try:
        resource_uuid = UUID(str(resource_id))
    except ValueError as exc:
        raise ReferencePackageError(
            f"Invalid reference package resource ID: {resource_id!r}.",
            code="REFERENCE_PACKAGE_INVALID",
        ) from exc
    resource = db.get(Resource, resource_uuid)
    if resource is None:
        raise ReferencePackageError(
            f"Reference package resource not found: {resource_id}.",
            code="REFERENCE_PACKAGE_NOT_FOUND",
        )
    return validate_reference_package(resource, expected_genome_build=expected_genome_build)
