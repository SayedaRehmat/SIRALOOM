from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

from backend.app.domain.reference import ReferenceError, validate_bgzf_gzi_index
from backend.app.infrastructure.db.models import Resource

REFERENCE_PACKAGE_SCHEMA_VERSION = "1.0"
REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION = "1.1"
SUPPORTED_REFERENCE_PACKAGE_SCHEMA_VERSIONS = {
    REFERENCE_PACKAGE_SCHEMA_VERSION,
    REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION,
}
REFERENCE_PACKAGE_RESOURCE_TYPE = "REFERENCE_PACKAGE"
REFERENCE_PACKAGE_STATUS = "ACTIVE"
CONTIG_POLICY_EXACT = "EXACT"
REFERENCE_ASSEMBLY_METADATA_FIELDS = ("assembly_name", "assembly_accession", "reference_source", "sequence_scope")
_FASTA_BASES = b"ACGTRYSWKMBDHVNacgtryswkmbdhvn"
_FASTA_TRANSLATION = bytes.maketrans(b"", b"")


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


def validate_fasta_index_consistency(
    fasta_path: str | Path,
    fai_path: str | Path,
) -> list[dict[str, int | str]]:
    """Verify every FAI offset/line geometry against the actual FASTA byte stream.

    gzip.open transparently reads BGZF's concatenated gzip members, so the same
    uncompressed FASTA geometry check applies to plain and BGZF-compressed FASTA.
    """
    import gzip

    fasta = Path(fasta_path)
    fai = Path(fai_path)
    expected: dict[str, tuple[int, int, int, int]] = {}
    order: list[str] = []
    for line_no, line in enumerate(fai.read_text(encoding="utf-8").splitlines(), 1):
        fields = line.split("\t")
        if len(fields) < 5:
            raise ReferencePackageError(
                f"Malformed FASTA index at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            )
        try:
            name = fields[0]
            length, offset, line_bases, line_width = map(int, fields[1:5])
        except ValueError as exc:
            raise ReferencePackageError(
                f"Non-numeric FASTA index field at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            ) from exc
        if name in expected or not name or length <= 0 or offset < 0 or line_bases <= 0 or line_width < line_bases:
            raise ReferencePackageError(
                f"Invalid or duplicate FASTA index entry at line {line_no}.",
                code="REFERENCE_FAI_INVALID",
            )
        expected[name] = (length, offset, line_bases, line_width)
        order.append(name)

    observed: list[dict[str, int | str]] = []
    try:
        with fasta.open("rb") as probe:
            is_gzip = probe.read(2) == b"\x1f\x8b"
        opener = gzip.open if is_gzip else open
        with opener(fasta, "rb") as handle:
            current_name: str | None = None
            sequence_length = 0
            sequence_offset = 0
            first_line_bases = 0
            first_line_width = 0
            previous_line_bases: int | None = None
            previous_line_width: int | None = None
            for raw_line in handle:
                if raw_line.startswith(b">"):
                    if current_name is not None:
                        if sequence_length <= 0:
                            raise ReferencePackageError(
                                f"Reference contig {current_name!r} has no sequence.",
                                code="REFERENCE_FASTA_INVALID",
                            )
                        observed.append({
                            "name": current_name,
                            "length": sequence_length,
                            "offset": sequence_offset,
                            "line_bases": first_line_bases,
                            "line_width": first_line_width,
                        })
                    header = raw_line[1:].strip().split()
                    if not header:
                        raise ReferencePackageError(
                            "Reference FASTA contains an empty sequence identifier.",
                            code="REFERENCE_FASTA_INVALID",
                        )
                    current_name = header[0].decode("utf-8")
                    sequence_length = 0
                    sequence_offset = handle.tell()
                    first_line_bases = 0
                    first_line_width = 0
                    previous_line_bases = None
                    continue
                if current_name is None:
                    raise ReferencePackageError(
                        "Reference FASTA sequence appears before the first header.",
                        code="REFERENCE_FASTA_INVALID",
                    )
                sequence = raw_line.rstrip(b"\r\n")
                # Keep per-base validation in bytes.translate's C loop. Iterating
                # over every nucleotide in Python made validation of human-sized
                # references impractically slow.
                invalid_bases = sequence.translate(_FASTA_TRANSLATION, _FASTA_BASES)
                if not sequence or invalid_bases:
                    raise ReferencePackageError(
                        f"Invalid sequence line in reference contig {current_name!r}.",
                        code="REFERENCE_FASTA_INVALID",
                    )
                line_bases = len(sequence)
                line_width = len(raw_line)
                if first_line_bases == 0:
                    first_line_bases = line_bases
                    first_line_width = line_width
                elif (
                    previous_line_bases != first_line_bases
                    or previous_line_width != first_line_width
                    or line_bases > first_line_bases
                ):
                    raise ReferencePackageError(
                        f"Inconsistent FASTA line wrapping in contig {current_name!r}.",
                        code="REFERENCE_FASTA_INVALID",
                    )
                previous_line_bases = line_bases
                previous_line_width = line_width
                sequence_length += line_bases
            if current_name is not None:
                if sequence_length <= 0:
                    raise ReferencePackageError(
                        f"Reference contig {current_name!r} has no sequence.",
                        code="REFERENCE_FASTA_INVALID",
                    )
                observed.append({
                    "name": current_name,
                    "length": sequence_length,
                    "offset": sequence_offset,
                    "line_bases": first_line_bases,
                    "line_width": first_line_width,
                })
    except (OSError, EOFError) as exc:
        raise ReferencePackageError(
            f"Unable to read reference FASTA or BGZF stream: {exc}",
            code="REFERENCE_FASTA_INVALID",
        ) from exc

    if [entry["name"] for entry in observed] != order:
        raise ReferencePackageError(
            "FASTA sequence identifiers/order do not match the FAI index.",
            code="REFERENCE_FAI_MISMATCH",
        )
    for entry in observed:
        indexed = expected[str(entry["name"])]
        actual = (
            int(entry["length"]),
            int(entry["offset"]),
            int(entry["line_bases"]),
            int(entry["line_width"]),
        )
        if actual != indexed:
            raise ReferencePackageError(
                f"FASTA index geometry does not match sequence {entry['name']!r}.",
                code="REFERENCE_FAI_MISMATCH",
            )
    return [{"name": str(entry["name"]), "length": int(entry["length"])} for entry in observed]


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
    assembly_name: str,
    assembly_accession: str,
    reference_source: str,
    sequence_scope: str,
    schema_version: str = REFERENCE_PACKAGE_SCHEMA_VERSION,
    gzi_sha256: str | None = None,
) -> str:
    manifest = {
        "schema_version": schema_version,
        "genome_build": genome_build,
        "version": version,
        "fasta_sha256": fasta_sha256,
        "fai_sha256": fai_sha256,
        "contigs_sha256": contigs_sha256,
        "contig_policy": CONTIG_POLICY_EXACT,
        "assembly_name": assembly_name,
        "assembly_accession": assembly_accession,
        "reference_source": reference_source,
        "sequence_scope": sequence_scope,
    }
    if schema_version == REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION:
        manifest["gzi_sha256"] = gzi_sha256
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_reference_package(
    resource: Resource,
    *,
    expected_genome_build: str,
    allow_approved_qualified: bool = False,
    allow_candidate_for_qualification: bool = False,
) -> dict:
    if resource.resource_type != REFERENCE_PACKAGE_RESOURCE_TYPE:
        raise ReferencePackageError(
            f"Resource {resource.id} is not a reference package.",
            code="REFERENCE_PACKAGE_INVALID",
        )
    allowed_statuses = {"ACTIVE", "SUPERSEDED"}
    if allow_approved_qualified:
        allowed_statuses.add("QUALIFIED")
    if allow_candidate_for_qualification:
        allowed_statuses.add("CANDIDATE")
    if resource.status not in allowed_statuses:
        raise ReferencePackageError(
            f"Reference package {resource.name!r} is not consumable (status={resource.status!r}).",
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
    schema_version = metadata.get("schema_version")
    if schema_version not in SUPPORTED_REFERENCE_PACKAGE_SCHEMA_VERSIONS:
        raise ReferencePackageError(
            f"Unsupported reference package schema: {schema_version!r}.",
            code="REFERENCE_PACKAGE_INVALID",
        )
    missing_identity = [field for field in REFERENCE_ASSEMBLY_METADATA_FIELDS if not metadata.get(field)]
    if missing_identity:
        raise ReferencePackageError(
            "Reference package is missing assembly identity metadata: " + ", ".join(missing_identity),
            code="REFERENCE_ASSEMBLY_IDENTITY_MISSING",
        )

    if metadata.get("contig_policy") != CONTIG_POLICY_EXACT:
        raise ReferencePackageError(
            "Reference package must declare contig_policy=EXACT; implicit contig aliases are forbidden.",
            code="REFERENCE_CONTIG_POLICY_INVALID",
        )

    fasta_path = Path(str(metadata.get("fasta_path") or ""))
    fai_path = Path(str(metadata.get("fai_path") or ""))
    try:
        with fasta_path.open("rb") as probe:
            compressed = probe.read(2) == b"\x1f\x8b"
    except OSError:
        compressed = fasta_path.name.lower().endswith((".gz", ".bgz"))
    if compressed and schema_version != REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION:
        raise ReferencePackageError(
            "BGZF reference packages require schema 1.1 with a checksummed GZI index.",
            code="REFERENCE_GZI_REQUIRED",
        )
    if schema_version == REFERENCE_PACKAGE_BGZF_SCHEMA_VERSION and not compressed:
        raise ReferencePackageError(
            "Reference package schema 1.1 is reserved for BGZF FASTA packages.",
            code="REFERENCE_PACKAGE_SCHEMA_INVALID",
        )
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

    gzi_path: Path | None = None
    actual_gzi_sha: str | None = None
    if compressed:
        gzi_path = Path(str(metadata.get("gzi_path") or ""))
        if not gzi_path.is_file():
            raise ReferencePackageError(
                "BGZF reference package is missing its GZI index.",
                code="REFERENCE_GZI_MISSING",
            )
        actual_gzi_sha = sha256_file(gzi_path)
        if actual_gzi_sha != str(metadata.get("gzi_sha256") or ""):
            raise ReferencePackageError(
                "Reference GZI checksum mismatch.",
                code="REFERENCE_CHECKSUM_MISMATCH",
            )
        try:
            validate_bgzf_gzi_index(fasta_path, gzi_path)
        except ReferenceError as exc:
            raise ReferencePackageError(str(exc), code=exc.code) from exc

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

    contigs = validate_fasta_index_consistency(fasta_path, fai_path)
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
        assembly_name=str(metadata["assembly_name"]),
        assembly_accession=str(metadata["assembly_accession"]),
        reference_source=str(metadata["reference_source"]),
        sequence_scope=str(metadata["sequence_scope"]),
        schema_version=str(schema_version),
        gzi_sha256=actual_gzi_sha,
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
        "assembly_name": metadata["assembly_name"],
        "assembly_accession": metadata["assembly_accession"],
        "reference_source": metadata["reference_source"],
        "sequence_scope": metadata["sequence_scope"],
        "fasta_path": str(fasta_path),
        "fai_path": str(fai_path),
        "fasta_sha256": actual_fasta_sha,
        "fai_sha256": actual_fai_sha,
        "gzi_path": str(gzi_path) if gzi_path is not None else None,
        "gzi_sha256": actual_gzi_sha,
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
    allow_approved_qualified: bool = False,
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
    return validate_reference_package(
        resource,
        expected_genome_build=expected_genome_build,
        allow_approved_qualified=allow_approved_qualified,
    )
