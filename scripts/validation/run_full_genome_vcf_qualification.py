#!/usr/bin/env python3
"""Full-genome qualification runner for real germline SNV/indel caller VCFs.

This is deliberately separate from run_real_caller_vcf_smoke.py. It never
constructs a chromosome projection or substitutes a reference. It requires an
already-built reference package plus a versioned GIAB truth VCF and confident
BED. A caller is qualified only when every required gate executes and passes.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.app.domain.caller_attestation import verify_signed_caller_manifest

from backend.app.domain.ebi_vcf_validator import (
    assess_ebi_vcf_compatibility,
    run_ebi_vcf_assembly_checker,
    run_ebi_vcf_validator,
)
from backend.app.domain.reference_identity import (
    inspect_fasta_sequence_identity,
    validate_sequence_dictionary,
)
from backend.app.domain.reference_package import (
    contig_manifest_sha256,
    sha256_file,
    validate_fasta_index_consistency,
)
from backend.app.domain.reference import validate_bgzf_gzi_index
from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance
from backend.app.domain.vcf_compatibility import create_dragen_v42_event_projection
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import validate_vcf_reference_alleles, validate_vcf_strict
from scripts.validation.run_real_caller_vcf_smoke import (
    download_callsets,
    EXPECTED_PROFILES,
    dragen_gp_attestation,
)
from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance

REQUIRED_CALLERS = {"GATK", "DEEPVARIANT", "DRAGEN"}


class QualificationBlocked(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], *, timeout: int, stdout_path: Path | None = None) -> dict[str, Any]:
    started = utc_now()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise QualificationBlocked(
            f"COMMAND_TIMEOUT after {timeout}s: {' '.join(command)}"
        ) from exc
    except OSError as exc:
        raise QualificationBlocked(
            f"COMMAND_EXECUTION_ERROR for {' '.join(command)}: {exc}"
        ) from exc
    evidence = {
        "command": command,
        "exit_code": completed.returncode,
        "started_at": started,
        "finished_at": utc_now(),
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-20000:],
        "stdout_truncated": len(completed.stdout) > 20000,
        "stderr_truncated": len(completed.stderr) > 20000,
    }
    if stdout_path is not None:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        evidence["stdout_artifact"] = str(stdout_path)
        evidence["stdout_sha256"] = sha256_file(stdout_path)
    if completed.returncode != 0:
        raise QualificationBlocked(
            f"COMMAND_FAILED ({completed.returncode}): {' '.join(command)}; "
            f"stderr={completed.stderr[-4000:]}"
        )
    return evidence


def _reference_package_checksum(manifest: dict[str, Any]) -> str:
    schema_version = str(manifest.get("schema_version") or "")
    package_payload = {
        "schema_version": schema_version,
        "genome_build": "GRCh38",
        "version": str(manifest.get("package_version") or ""),
        "fasta_sha256": str(manifest.get("fasta_sha256") or ""),
        "fai_sha256": str(manifest.get("fai_sha256") or ""),
        "contigs_sha256": str(manifest.get("contigs_sha256") or ""),
        "contig_policy": "EXACT",
        "assembly_name": str(manifest.get("assembly_name") or ""),
        "assembly_accession": str(manifest.get("assembly_accession") or ""),
        "reference_source": str(manifest.get("reference_source") or ""),
        "sequence_scope": str(manifest.get("sequence_scope") or ""),
    }
    if schema_version == "1.3":
        package_payload["gzi_sha256"] = str(manifest.get("gzi_sha256") or "")
    if schema_version in {"1.2", "1.3"}:
        package_payload["dictionary_sha256"] = str(manifest.get("dictionary_sha256") or "")
        package_payload["sequence_collection_digest"] = str(
            manifest.get("sequence_collection_digest") or ""
        )
    return hashlib.sha256(
        json.dumps(package_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_reference(
    manifest_path: Path,
    fasta_arg: Path,
    *,
    expected_package_checksum: str,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = str(manifest.get("schema_version") or "")
    if schema_version not in {"1.2", "1.3"}:
        raise QualificationBlocked(
            "REFERENCE_SEQUENCE_IDENTITY_SCHEMA_REQUIRED: full-genome qualification requires "
            "reference package schema 1.2 (plain FASTA) or 1.3 (BGZF FASTA) with Refget/Seqcol identity."
        )
    fasta = fasta_arg.resolve()
    fai = Path(str(fasta) + ".fai")
    if not fasta.is_file() or not fai.is_file():
        raise QualificationBlocked("REFERENCE_ASSET_MISSING: full FASTA and adjacent .fai are required")
    expected_fasta = str(manifest.get("fasta_sha256") or "")
    expected_fai = str(manifest.get("fai_sha256") or "")
    if not expected_fasta or sha256_file(fasta) != expected_fasta:
        raise QualificationBlocked("REFERENCE_FASTA_CHECKSUM_MISMATCH")
    if not expected_fai or sha256_file(fai) != expected_fai:
        raise QualificationBlocked("REFERENCE_FAI_CHECKSUM_MISMATCH")
    if manifest.get("fasta_size_bytes") is not None and fasta.stat().st_size != int(manifest["fasta_size_bytes"]):
        raise QualificationBlocked("REFERENCE_FASTA_SIZE_MISMATCH")

    with fasta.open("rb") as fasta_probe:
        compressed = fasta_probe.read(2) == bytes((31, 139))
    if (schema_version == "1.2" and compressed) or (schema_version == "1.3" and not compressed):
        raise QualificationBlocked("REFERENCE_FASTA_COMPRESSION_SCHEMA_MISMATCH")
    gzi_path = None
    gzi_sha = None
    if schema_version == "1.3":
        gzi_value = manifest.get("gzi_path")
        declared_gzi = Path(str(gzi_value)) if gzi_value else None
        adjacent_gzi = Path(str(fasta) + ".gzi")
        gzi_path = declared_gzi if declared_gzi and declared_gzi.is_file() else adjacent_gzi
        if not gzi_path.is_file():
            raise QualificationBlocked("REFERENCE_GZI_MISSING")
        gzi_sha = sha256_file(gzi_path)
        if gzi_sha != str(manifest.get("gzi_sha256") or ""):
            raise QualificationBlocked("REFERENCE_GZI_CHECKSUM_MISMATCH")
        try:
            validate_bgzf_gzi_index(fasta, gzi_path)
        except Exception as exc:
            raise QualificationBlocked(f"REFERENCE_GZI_INVALID: {exc}") from exc

    contigs = validate_fasta_index_consistency(fasta, fai)
    if contigs != manifest.get("contigs"):
        raise QualificationBlocked("REFERENCE_CONTIG_MANIFEST_MISMATCH")
    contigs_sha = contig_manifest_sha256(contigs)
    if contigs_sha != str(manifest.get("contigs_sha256") or ""):
        raise QualificationBlocked("REFERENCE_CONTIG_MANIFEST_CHECKSUM_MISMATCH")
    if manifest.get("contig_policy") != "EXACT":
        raise QualificationBlocked("REFERENCE_CONTIG_POLICY_MUST_BE_EXACT")
    for key in ("assembly_name", "assembly_accession", "reference_source", "sequence_scope", "package_version"):
        if not manifest.get(key):
            raise QualificationBlocked(f"REFERENCE_ASSEMBLY_IDENTITY_INCOMPLETE: {key}")

    dictionary_value = manifest.get("dictionary_path")
    declared_dictionary = Path(str(dictionary_value)) if dictionary_value else None
    adjacent_dictionary = fasta.with_suffix(".dict")
    dictionary = (
        declared_dictionary
        if declared_dictionary and declared_dictionary.is_file()
        else adjacent_dictionary
    )
    if not dictionary.is_file():
        raise QualificationBlocked("REFERENCE_DICTIONARY_MISSING")
    dictionary_sha = sha256_file(dictionary)
    if dictionary_sha != str(manifest.get("dictionary_sha256") or ""):
        raise QualificationBlocked("REFERENCE_DICTIONARY_CHECKSUM_MISMATCH")
    try:
        sequence_identity = inspect_fasta_sequence_identity(fasta)
        dictionary_identity = validate_sequence_dictionary(
            dictionary, sequence_identity["sequences"]
        )
    except Exception as exc:
        raise QualificationBlocked(f"REFERENCE_SEQUENCE_IDENTITY_INVALID: {exc}") from exc
    if sequence_identity["sequences"] != manifest.get("sequence_manifest"):
        raise QualificationBlocked("REFERENCE_SEQUENCE_MANIFEST_MISMATCH")
    if sequence_identity["sequence_collection_digest"] != manifest.get("sequence_collection_digest"):
        raise QualificationBlocked("REFERENCE_SEQUENCE_COLLECTION_DIGEST_MISMATCH")

    computed_package_checksum = _reference_package_checksum(manifest)
    if not expected_package_checksum or manifest.get("package_checksum") != expected_package_checksum:
        raise QualificationBlocked("REFERENCE_PACKAGE_APPROVAL_CHECKSUM_MISMATCH")
    if computed_package_checksum != expected_package_checksum:
        raise QualificationBlocked("REFERENCE_PACKAGE_CHECKSUM_MISMATCH")

    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "schema_version": schema_version,
        "fasta_path": str(fasta),
        "fasta_sha256": expected_fasta,
        "fai_path": str(fai),
        "fai_sha256": expected_fai,
        "dictionary_path": str(dictionary.resolve()),
        "dictionary_sha256": dictionary_sha,
        "dictionary_identity": dictionary_identity,
        "assembly_name": manifest["assembly_name"],
        "assembly_accession": manifest["assembly_accession"],
        "reference_source": manifest["reference_source"],
        "sequence_scope": manifest["sequence_scope"],
        "package_version": manifest["package_version"],
        "package_checksum": computed_package_checksum,
        "contigs_sha256": contigs_sha,
        "sequence_manifest": sequence_identity["sequences"],
        "sequence_collection_digest": sequence_identity["sequence_collection_digest"],
        "gzi_path": str(gzi_path.resolve()) if gzi_path else None,
        "gzi_sha256": gzi_sha,
        "contigs": contigs,
        "contig_count": len(contigs),
        "scope": "FULL_REFERENCE_PACKAGE",
        "identity_status": "FASTA_FAI_DICTIONARY_REFGET_SEQCOL_AND_PACKAGE_CHECKSUM_VERIFIED",
    }


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.name.lower().endswith((".gz", ".bgz")) else path.open("r", encoding="utf-8")


def validate_giab_manifest(
    manifest_path: Path,
    truth_vcf: Path,
    confident_bed: Path,
    reference: dict[str, Any],
    *,
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_manifest_sha256 = sha256_file(manifest_path)
    if not expected_manifest_sha256 or actual_manifest_sha256 != expected_manifest_sha256:
        raise QualificationBlocked("GIAB_MANIFEST_APPROVAL_CHECKSUM_MISMATCH")
    required = (
        "dataset_id", "dataset_version", "sample_id", "variant_scope",
        "assembly_accession", "reference_package_checksum", "reference_fasta_sha256",
        "sequence_collection_digest", "truth_vcf", "confident_bed",
    )
    missing = [key for key in required if not manifest.get(key)]
    if missing:
        raise QualificationBlocked("GIAB_MANIFEST_FIELDS_MISSING: " + ",".join(missing))
    if manifest.get("schema_version") != 1:
        raise QualificationBlocked("GIAB_MANIFEST_SCHEMA_UNSUPPORTED")
    if manifest["variant_scope"] != "GERMLINE_SNV_INDEL":
        raise QualificationBlocked("GIAB_VARIANT_SCOPE_MUST_BE_GERMLINE_SNV_INDEL")
    if manifest["assembly_accession"] != reference["assembly_accession"]:
        raise QualificationBlocked("GIAB_ASSEMBLY_ACCESSION_MISMATCH")
    if manifest["reference_package_checksum"] != reference["package_checksum"]:
        raise QualificationBlocked("GIAB_REFERENCE_PACKAGE_CHECKSUM_MISMATCH")
    if manifest["reference_fasta_sha256"] != reference["fasta_sha256"]:
        raise QualificationBlocked("GIAB_REFERENCE_FASTA_IDENTITY_MISMATCH")
    if manifest["sequence_collection_digest"] != reference["sequence_collection_digest"]:
        raise QualificationBlocked("GIAB_REFERENCE_SEQCOL_IDENTITY_MISMATCH")

    for key, artifact in (("truth_vcf", truth_vcf), ("confident_bed", confident_bed)):
        entry = manifest[key]
        if not isinstance(entry, dict):
            raise QualificationBlocked(f"GIAB_{key.upper()}_MANIFEST_INVALID")
        source_url = str(entry.get("source_url") or "")
        publisher_checksum_url = str(entry.get("publisher_checksum_source_url") or "")
        if not source_url.startswith("https://"):
            raise QualificationBlocked(f"GIAB_{key.upper()}_SOURCE_URL_REQUIRED")
        if not publisher_checksum_url.startswith("https://"):
            raise QualificationBlocked(f"GIAB_{key.upper()}_PUBLISHER_CHECKSUM_SOURCE_REQUIRED")
        if Path(str(entry.get("filename") or "")).name != artifact.name:
            raise QualificationBlocked(f"GIAB_{key.upper()}_FILENAME_MISMATCH")
        actual_sha = sha256_file(artifact)
        if actual_sha != str(entry.get("sha256") or ""):
            raise QualificationBlocked(f"GIAB_{key.upper()}_CHECKSUM_MISMATCH")
        checksum_algorithm = str(entry.get("publisher_checksum_algorithm") or "").upper()
        publisher_checksum = str(entry.get("publisher_checksum") or "").lower()
        if checksum_algorithm not in {"MD5", "SHA256"} or not publisher_checksum:
            raise QualificationBlocked(f"GIAB_{key.upper()}_PUBLISHER_CHECKSUM_MISSING")
        if checksum_algorithm == "SHA256":
            observed_publisher_checksum = actual_sha
        else:
            md5_digest = hashlib.md5(usedforsecurity=False)
            with artifact.open("rb") as checksum_handle:
                for chunk in iter(lambda: checksum_handle.read(1024 * 1024), b""):
                    md5_digest.update(chunk)
            observed_publisher_checksum = md5_digest.hexdigest()
        if observed_publisher_checksum != publisher_checksum:
            raise QualificationBlocked(f"GIAB_{key.upper()}_PUBLISHER_CHECKSUM_MISMATCH")

    reference_contigs = {str(item["name"]): int(item["length"]) for item in reference["contigs"]}
    sample_names: list[str] = []
    declared_contigs: dict[str, int] = {}
    with _open_text(truth_vcf) as handle:
        for line in handle:
            if line.startswith("##contig=<"):
                id_match = re.search(r"(?:^|,)ID=([^,>]+)", line.strip()[10:-1])
                length_match = re.search(r"(?:^|,)length=(\d+)", line.strip()[10:-1], flags=re.IGNORECASE)
                if not id_match or not length_match:
                    raise QualificationBlocked("GIAB_TRUTH_VCF_CONTIG_HEADER_INCOMPLETE")
                declared_contigs[id_match.group(1)] = int(length_match.group(1))
            elif line.startswith("#CHROM"):
                columns = line.rstrip("\r\n").split("\t")
                sample_names = columns[9:] if len(columns) > 9 else []
                break
            elif not line.startswith("#"):
                raise QualificationBlocked("GIAB_TRUTH_VCF_HEADER_TERMINATOR_MISSING")
    if not declared_contigs:
        raise QualificationBlocked("GIAB_TRUTH_VCF_CONTIG_DICTIONARY_MISSING")
    for contig, length in declared_contigs.items():
        if reference_contigs.get(contig) != length:
            raise QualificationBlocked(
                f"GIAB_TRUTH_VCF_CONTIG_REFERENCE_MISMATCH: {contig}:{length}"
            )
    if sample_names != [str(manifest["sample_id"])]:
        raise QualificationBlocked(
            f"GIAB_TRUTH_SAMPLE_MISMATCH: expected exactly {[manifest['sample_id']]!r}, observed {sample_names}"
        )

    reference_order = {name: index for index, name in enumerate(reference_contigs)}
    previous_key = (-1, -1)
    previous_end: dict[str, int] = {}
    bed_intervals = 0
    with _open_text(confident_bed) as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip() or line.startswith(("#", "track", "browser")):
                continue
            fields = line.rstrip("\r\n").split("\t")
            if len(fields) < 3:
                raise QualificationBlocked(f"GIAB_CONFIDENT_BED_INVALID_LINE:{line_number}")
            contig = fields[0]
            if contig not in reference_contigs:
                raise QualificationBlocked(f"GIAB_CONFIDENT_BED_UNKNOWN_CONTIG:{contig}")
            try:
                start, end = int(fields[1]), int(fields[2])
            except ValueError as exc:
                raise QualificationBlocked(f"GIAB_CONFIDENT_BED_INVALID_COORDINATE:{line_number}") from exc
            if start < 0 or end <= start or end > reference_contigs[contig]:
                raise QualificationBlocked(f"GIAB_CONFIDENT_BED_INTERVAL_OUT_OF_BOUNDS:{line_number}")
            order_key = (reference_order[contig], start)
            if order_key < previous_key or start < previous_end.get(contig, 0):
                raise QualificationBlocked(f"GIAB_CONFIDENT_BED_NOT_SORTED_OR_OVERLAPPING:{line_number}")
            previous_key = order_key
            previous_end[contig] = end
            bed_intervals += 1
    if bed_intervals == 0:
        raise QualificationBlocked("GIAB_CONFIDENT_BED_EMPTY")

    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": actual_manifest_sha256,
        "schema_version": 1,
        "dataset_id": manifest["dataset_id"],
        "dataset_version": manifest["dataset_version"],
        "sample_id": manifest["sample_id"],
        "variant_scope": manifest["variant_scope"],
        "assembly_accession": manifest["assembly_accession"],
        "reference_package_checksum": manifest["reference_package_checksum"],
        "reference_fasta_sha256": manifest["reference_fasta_sha256"],
        "sequence_collection_digest": manifest["sequence_collection_digest"],
        "truth_vcf": {
            "path": str(truth_vcf.resolve()),
            "sha256": sha256_file(truth_vcf),
            "source_url": manifest["truth_vcf"]["source_url"],
            "publisher_checksum_algorithm": manifest["truth_vcf"]["publisher_checksum_algorithm"],
            "publisher_checksum": manifest["truth_vcf"]["publisher_checksum"],
            "publisher_checksum_source_url": manifest["truth_vcf"]["publisher_checksum_source_url"],
            "sample_names": sample_names,
            "declared_contig_count": len(declared_contigs),
        },
        "confident_bed": {
            "path": str(confident_bed.resolve()),
            "sha256": sha256_file(confident_bed),
            "source_url": manifest["confident_bed"]["source_url"],
            "publisher_checksum_algorithm": manifest["confident_bed"]["publisher_checksum_algorithm"],
            "publisher_checksum": manifest["confident_bed"]["publisher_checksum"],
            "publisher_checksum_source_url": manifest["confident_bed"]["publisher_checksum_source_url"],
            "interval_count": bed_intervals,
        },
        "technical_compatibility_status": "VERIFIED_AGAINST_EXACT_REFERENCE_PACKAGE",
        "clinical_approval_status": manifest.get("clinical_approval_status", "NOT_ESTABLISHED"),
    }

def build_local_callsets(
    gatk_vcf: Path,
    deepvariant_vcf: Path,
    dragen_vcf: Path,
) -> list[dict[str, Any]]:
    supplied = (
        ("GATK_HAPLOTYPECALLER", gatk_vcf),
        ("DEEPVARIANT", deepvariant_vcf),
        ("DRAGEN", dragen_vcf),
    )
    callsets: list[dict[str, Any]] = []
    for caller, source_path in supplied:
        source = source_path.resolve()
        if not source.is_file():
            raise QualificationBlocked(f"LOCAL_CALLSET_MISSING: {caller}: {source}")
        provenance = inspect_caller_provenance(source)
        expected_profile = EXPECTED_PROFILES[caller]
        if provenance.get("caller_profile_id") != expected_profile:
            raise QualificationBlocked(
                f"LOCAL_CALLER_IDENTITY_MISMATCH: {caller}: expected profile "
                f"{expected_profile!r}, observed {provenance.get('caller_profile_id')!r}"
            )
        callsets.append({
            "caller": caller,
            "filename": source.name,
            "local_path": str(source),
            "sha256": sha256_file(source),
            "bytes": source.stat().st_size,
            "source_kind": "LAB_SUPPLIED_CALLSET",
            "caller_profile_id": expected_profile,
            "caller_provenance": provenance,
        })
    return callsets


def load_caller_reference_attestation(
    attestation_dir: Path | None,
    callset: dict[str, Any],
    source: Path,
    reference: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    if attestation_dir is None:
        return None, {
            "status": "BUILD_ONLY_UNVERIFIED",
            "reason_code": "SIGNED_CALLER_REFERENCE_MANIFEST_NOT_SUPPLIED",
            "reference_build": "GRCh38",
            "exact_reference_identity_verified": False,
        }
    caller = str(callset["caller"]).lower()
    manifest_path = attestation_dir / f"{caller}.json"
    if not manifest_path.is_file():
        raise QualificationBlocked(f"CALLER_SIGNED_MANIFEST_MISSING: {manifest_path}")
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = envelope.get("manifest") if isinstance(envelope, dict) else None
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 3:
        raise QualificationBlocked(
            f"{callset['caller']}: signed caller manifest schema v3 with exact reference identity is required"
        )
    try:
        organization_id = UUID(str(manifest["organization_id"]))
        verified = verify_signed_caller_manifest(
            source,
            envelope,
            organization_id=organization_id,
            expected_artifact_sha256=sha256_file(source),
        )
    except Exception as exc:
        raise QualificationBlocked(
            f"{callset['caller']}: signed caller reference manifest verification failed: {exc}"
        ) from exc
    expected = {
        "caller_profile_id": EXPECTED_PROFILES[callset["caller"]],
        "reference_build": "GRCh38",
        "reference_assembly_accession": reference["assembly_accession"],
        "reference_fasta_sha256": reference["fasta_sha256"],
        "reference_package_checksum": reference["package_checksum"],
        "reference_sequence_collection_digest": reference["sequence_collection_digest"],
    }
    for field, value in expected.items():
        if verified.get(field) != value:
            raise QualificationBlocked(
                f"{callset['caller']}: signed caller manifest {field} does not match selected run/reference"
            )
    return envelope, {
        "status": "EXACT_REFERENCE_IDENTITY_VERIFIED",
        "reason_code": None,
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_id": verified["manifest_id"],
        "caller_profile_id": verified["caller_profile_id"],
        "caller_release": verified["caller_release"],
        "reference_build": verified["reference_build"],
        "reference_assembly_accession": verified["reference_assembly_accession"],
        "reference_fasta_sha256": verified["reference_fasta_sha256"],
        "reference_package_checksum": verified["reference_package_checksum"],
        "reference_sequence_collection_digest": verified["reference_sequence_collection_digest"],
        "signature_sha256": verified["signature_sha256"],
        "exact_reference_identity_verified": True,
    }


def require_gatk(expected_version: str) -> dict[str, Any]:
    executable = shutil.which("gatk")
    if not executable:
        raise QualificationBlocked("GATK_VALIDATEVARIANTS_UNAVAILABLE")
    if not expected_version or not expected_version.strip():
        raise QualificationBlocked("GATK_EXPECTED_VERSION_REQUIRED")
    version_evidence = run_command([executable, "--version"], timeout=60)
    version_output = "\n".join(
        part for part in (version_evidence.get("stdout"), version_evidence.get("stderr")) if part
    )
    import re
    match = re.search(r"v?(\d+\.\d+\.\d+\.\d+)", version_output)
    if not match:
        raise QualificationBlocked(
            f"GATK_VERSION_UNRESOLVED: version command output was {version_output!r}"
        )
    observed_version = match.group(1)
    if observed_version != expected_version:
        raise QualificationBlocked(
            f"GATK_VERSION_MISMATCH: expected {expected_version}, observed {observed_version}"
        )
    executable_path = Path(executable).resolve()
    lock_value = os.environ.get("SIRALOOM_GATK_EXPLICIT_LOCK")
    if not lock_value:
        raise QualificationBlocked("GATK_EXPLICIT_LOCK_REQUIRED")
    lock_path = Path(lock_value).resolve()
    if not lock_path.is_file():
        raise QualificationBlocked(f"GATK_EXPLICIT_LOCK_MISSING: {lock_path}")
    return {
        "executable": str(executable_path),
        "executable_sha256": sha256_file(executable_path),
        "explicit_environment_lock": str(lock_path),
        "explicit_environment_lock_sha256": sha256_file(lock_path),
        "expected_version": expected_version,
        "observed_version": observed_version,
        "version_evidence": version_evidence,
    }


def run_happy(truth: Path, query: Path, confident_bed: Path, reference: Path, prefix: Path) -> dict:
    executable = shutil.which("hap.py")
    if not executable:
        raise QualificationBlocked("HAP_PY_UNAVAILABLE")
    if not truth.is_file() or not confident_bed.is_file():
        raise QualificationBlocked("GIAB_TRUTH_OR_CONFIDENT_BED_MISSING")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    command = [
        executable, str(truth), str(query),
        "-f", str(confident_bed),
        "-r", str(reference),
        "-o", str(prefix),
    ]
    evidence = run_command(command, timeout=24 * 60 * 60)
    generated = sorted(prefix.parent.glob(prefix.name + "*"))
    if not generated:
        raise QualificationBlocked("HAP_PY_COMPLETED_WITHOUT_OUTPUT_ARTIFACTS")
    evidence["outputs"] = [
        {"path": str(p), "bytes": p.stat().st_size, "sha256": sha256_file(p)}
        for p in generated if p.is_file()
    ]
    return evidence


def qualify_one(
    callset: dict[str, Any], *, reference: dict[str, Any], truth: Path,
    confident_bed: Path, giab: dict[str, Any], output: Path, gatk: dict[str, Any],
    caller_attestation_dir: Path | None = None,
) -> dict[str, Any]:
    caller = callset["caller"]
    source = Path(callset["local_path"]).resolve()
    result: dict[str, Any] = {
        "caller": caller,
        "source_filename": callset["filename"],
        "source_kind": callset.get("source_kind", "UNSPECIFIED"),
        "source_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "source_publisher_checksum": callset.get("zenodo_checksum"),
        "source_checksum_verified": callset.get("verified_source_checksum", False),
        "scope": "FULL_SOURCE_VCF",
        "started_at": utc_now(),
        "gates": {},
        "giab_reference_compatibility": giab,
    }
    if not result["source_checksum_verified"]:
        raise QualificationBlocked(f"{caller}: publisher checksum was not verified")
    provenance = inspect_caller_provenance(source)
    result["caller_provenance"] = provenance
    if provenance.get("caller_profile_id") != EXPECTED_PROFILES[caller]:
        raise QualificationBlocked(f"{caller}: caller profile identity does not match expected profile")

    caller_attestation, caller_reference_identity = load_caller_reference_attestation(
        caller_attestation_dir, callset, source, reference
    )
    result["caller_reference_identity"] = caller_reference_identity
    if caller_attestation is None:
        caller_attestation = dragen_gp_attestation(callset, source)
    signed_manifest = caller_attestation.get("manifest") if isinstance(caller_attestation, dict) else None
    strict = validate_vcf_strict(
        source,
        caller_attestation=caller_attestation,
        organization_id=UUID(signed_manifest["organization_id"]) if signed_manifest else None,
        artifact_sha256=result["source_sha256"],
        expected_reference_build="GRCh38",
        expected_reference_assembly_accession=reference["assembly_accession"] if signed_manifest else None,
        expected_reference_fasta_sha256=reference["fasta_sha256"] if signed_manifest else None,
        expected_reference_package_checksum=reference["package_checksum"] if signed_manifest else None,
        expected_reference_sequence_collection_digest=reference["sequence_collection_digest"] if signed_manifest else None,
    )
    result["caller_semantic_attestation"] = strict.get("caller_semantic_attestation")
    result["gates"]["siraloom_strict"] = {
        "status": (
            "PASS_WITH_REVIEW_REQUIRED"
            if strict.get("caller_semantic_compatibility_review_required")
            else "PASS"
        ),
        "records": strict.get("records"),
        "sample_count": strict.get("sample_count"),
        "vcf_version": strict.get("fileformat"),
        "metrics": strict,
    }

    ebi = run_ebi_vcf_validator(source, caller_provenance=provenance, timeout_seconds=6 * 60 * 60)
    ebi_compatibility = assess_ebi_vcf_compatibility(
        ebi,
        caller_semantic_attestation=strict.get("caller_semantic_attestation"),
    )
    ebi["compatibility_assessment"] = ebi_compatibility
    result["gates"]["ebi_vcf_validator"] = ebi
    ebi_effective_status = ebi_compatibility.get("effective_status", ebi.get("status"))
    if strict.get("caller_semantic_compatibility_review_required"):
        projection_path = output / caller.lower() / "compatibility" / "source.event-projected.vcf"
        projection = create_dragen_v42_event_projection(
            source,
            projection_path,
            caller_semantic_attestation=strict.get("caller_semantic_attestation"),
        )
        projection_ebi = run_ebi_vcf_validator(
            projection_path,
            caller_provenance=provenance,
            timeout_seconds=6 * 60 * 60,
        )
        projection_ebi_compatibility = assess_ebi_vcf_compatibility(
            projection_ebi,
            caller_semantic_attestation=strict.get("caller_semantic_attestation"),
        )
        projection_ebi["compatibility_assessment"] = projection_ebi_compatibility
        projection_ebi_effective = projection_ebi_compatibility.get(
            "effective_status", projection_ebi.get("status")
        )
        result["gates"]["dragen_event_compatibility_projection"] = {
            **projection,
            "raw_source_ebi_status": ebi.get("status"),
            "projection_ebi_validation": projection_ebi,
            "projection_ebi_effective_status": projection_ebi_effective,
        }
        if projection_ebi_effective not in {
            "PASS", "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS"
        }:
            raise QualificationBlocked(
                f"{caller}: EBI validation failed on the lossless DRAGEN compatibility projection"
            )
    if ebi_effective_status not in {"PASS", "PASS_WITH_DOCUMENTED_COMPATIBILITY_EXCEPTIONS"}:
        blocking = ebi_compatibility.get("blocking_diagnostics") or ebi.get("diagnostics") or []
        raise QualificationBlocked(
            f"{caller}: EBI validation has unresolved diagnostics; "
            f"raw_status={ebi.get('status')}, effective_status={ebi_effective_status}, "
            f"blocking_diagnostic_count={len(blocking)}"
        )

    # Route against the exact selected reference contig set before REF checking.
    # Out-of-package contigs are preserved unchanged in a dedicated artifact and
    # explicitly excluded from this reference's normalization/benchmark stream.
    reference_contig_lengths = {
        str(item["name"]): int(item["length"]) for item in reference["contigs"]
    }
    routed_dir = output / caller.lower() / "routing"
    routed = route_vcf_records(
        source,
        routed_dir,
        reference_contig_lengths=reference_contig_lengths,
    )
    result["gates"]["routing"] = routed
    if not routed.get("record_reconciliation", {}).get("balanced"):
        raise QualificationBlocked(f"{caller}: source-to-routing record reconciliation failed")
    if int(routed.get("source_record_count", -1)) != int(strict.get("records", -2)):
        raise QualificationBlocked(
            f"{caller}: strict-validator and router record counts disagree "
            f"({strict.get('records')} != {routed.get('source_record_count')})"
        )
    external_path_text = routed.get("external_reference_contigs_path")
    external_path = Path(external_path_text) if external_path_text else None
    external_count = int(routed.get("external_reference_contig_records", 0))
    if external_count and (external_path is None or not external_path.is_file()):
        raise QualificationBlocked(f"{caller}: external-contig records were counted but not preserved")
    result["gates"]["external_contig_disposition"] = {
        "status": "PRESERVED" if external_count else "NONE_PRESENT",
        "record_count": external_count,
        "artifact": (
            {
                "path": str(external_path),
                "bytes": external_path.stat().st_size,
                "sha256": sha256_file(external_path),
            }
            if external_path is not None and external_path.is_file() else None
        ),
        "policy": routed.get("external_contig_policy"),
        "reference_package_checksum": reference["package_checksum"],
    }
    if not routed.get("sequence_path") or int(routed.get("sequence_records", 0)) <= 0:
        raise QualificationBlocked(f"{caller}: no eligible sequence-resolved SNV/indel records in the selected reference")
    sequence_vcf = Path(routed["sequence_path"])

    gatk_dir = output / caller.lower() / "gatk"
    gatk_dir.mkdir(parents=True, exist_ok=True)
    gatk_input_vcf = sequence_vcf
    gatk_projection_evidence = None
    source_semantic_attestation = strict.get("caller_semantic_attestation")
    dragen_event_projection_required = bool(
        caller == "DRAGEN"
        and isinstance(source_semantic_attestation, dict)
        and source_semantic_attestation.get("caller_extension_detected") is True
        and source_semantic_attestation.get("targeted_records_verified") is True
    )
    if dragen_event_projection_required:
        gatk_projection_path = gatk_dir / "sequence.event-projected.vcf"
        gatk_projection_evidence = create_dragen_v42_event_projection(
            sequence_vcf,
            gatk_projection_path,
            caller_semantic_attestation=source_semantic_attestation,
        )
        gatk_input_vcf = gatk_projection_path
    gatk_log = gatk_dir / "validatevariants.stdout.log"
    # Exclude only GATK's extra-strict ALLELES genotype-observation test.
    # A VCF may list an ALT allele that is not selected in this sample's GT;
    # keep reference concordance and chromosome-count strict checks enabled.
    gatk_validation_command = [
        gatk["executable"], "ValidateVariants",
        "-R", reference["fasta_path"],
        "-V", str(gatk_input_vcf),
        "--validation-type-to-exclude", "ALLELES",
    ]
    gatk_evidence = run_command(
        gatk_validation_command,
        timeout=6 * 60 * 60,
        stdout_path=gatk_log,
    )
    result["gates"]["gatk_validate_variants"] = {
        **gatk_evidence,
        "validation_profile": "GATK_VALIDATEVARIANTS_STRICT_EXCEPT_UNOBSERVED_ALT_ALLELES",
        "validation_types_excluded": ["ALLELES"],
        "validation_policy_reason": (
            "GATK ALLELES is an extra-strict genotype-observation check; "
            "REF and CHR_COUNTS strict checks remain enabled."
        ),
        "input_path": str(gatk_input_vcf),
        "input_sha256": sha256_file(gatk_input_vcf),
        "input_scope": "REFERENCE_RESOLVED_SEQUENCE_RECORDS",
        "source_vcf_sha256": result["source_sha256"],
        "gatk_runtime": gatk,
        "compatibility_projection": gatk_projection_evidence,
    }

    ref_check = validate_vcf_reference_alleles(sequence_vcf, reference["fasta_path"])
    result["gates"]["siraloom_reference_check"] = {
        "status": "PASS",
        "scope": "REFERENCE_RESOLVED_SEQUENCE_RECORDS",
        "source_vcf_sha256": result["source_sha256"],
        "reference_package_checksum": reference["package_checksum"],
        "evidence": ref_check,
    }
    ebi_assembly = run_ebi_vcf_assembly_checker(
        sequence_vcf,
        reference["fasta_path"],
        source_artifact_sha256=result["source_sha256"],
        reference_build="GRCh38",
        caller_provenance=provenance,
        validation_input_scope="REFERENCE_RESOLVED_SEQUENCE_RECORDS",
        timeout_seconds=6 * 60 * 60,
    )
    result["gates"]["ebi_reference_resolved_assembly_checker"] = ebi_assembly
    if ebi_assembly.get("status") != "PASS":
        raise QualificationBlocked(f"{caller}: EBI assembly checker failed on reference-resolved sequence records")

    normalized = output / caller.lower() / f"{caller.lower()}.normalized.vcf.gz"
    normalization = normalize_vcf_with_bcftools(
        sequence_vcf,
        normalized,
        reference_fasta=reference["fasta_path"],
        expected_bcftools_version="1.25",
        timeout_seconds=6 * 60 * 60,
    )
    normalized_validation_input = normalized
    normalized_projection_evidence = None
    if dragen_event_projection_required:
        normalized_projection_path = output / caller.lower() / "normalized.event-projected.vcf"
        normalized_projection_evidence = create_dragen_v42_event_projection(
            normalized,
            normalized_projection_path,
            caller_semantic_attestation=source_semantic_attestation,
        )
        normalized_validation_input = normalized_projection_path
    normalized_strict = validate_vcf_strict(
        normalized_validation_input,
        expected_reference_build="GRCh38",
    )
    index = Path(str(normalized) + ".csi")
    if not index.is_file():
        raise QualificationBlocked(f"{caller}: normalized output index is missing")
    result["gates"]["normalization"] = {
        "status": "PASS",
        "normalization": normalization,
        "normalized_records": normalized_strict.get("records"),
        "normalized_sha256": sha256_file(normalized),
        "index_sha256": sha256_file(index),
        "normalized_strict_validation": normalized_strict,
        "normalized_validation_input_path": str(normalized_validation_input),
        "normalized_validation_input_sha256": sha256_file(normalized_validation_input),
        "compatibility_projection": normalized_projection_evidence,
    }

    if caller_reference_identity.get("exact_reference_identity_verified") is not True:
        result["gates"]["giab_happy"] = {
            "status": "BLOCKED",
            "reason_code": "CALLER_REFERENCE_EXACT_IDENTITY_UNVERIFIED",
            "interpretation": "No GIAB qualification metric is produced until the caller run manifest binds this VCF to the exact selected reference package.",
        }
        result["review_required"] = True
        result["status"] = "PASS_WITH_REVIEW_REQUIRED"
        result["finished_at"] = utc_now()
        return result

    happy_query = normalized_validation_input
    happy_projection = normalized_projection_evidence
    happy_evidence = run_happy(
        truth, happy_query, confident_bed, Path(reference["fasta_path"]),
        output / caller.lower() / "giab" / "hap.py",
    )
    result["gates"]["giab_happy"] = {
        **happy_evidence,
        "query_input_path": str(happy_query),
        "query_input_sha256": sha256_file(happy_query),
        "compatibility_projection": happy_projection,
        "normalized_source_vcf_sha256": sha256_file(normalized),
    }
    result["review_required"] = bool(
        strict.get("caller_semantic_compatibility_review_required")
        or external_count > 0
    )
    result["status"] = "PASS_WITH_REVIEW_REQUIRED" if result["review_required"] else "PASS"
    result["finished_at"] = utc_now()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--reference-fasta", type=Path, required=True)
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--expected-reference-package-checksum", required=True)
    parser.add_argument("--giab-truth-vcf", type=Path, required=True)
    parser.add_argument("--giab-confident-bed", type=Path, required=True)
    parser.add_argument("--giab-manifest", type=Path, required=True)
    parser.add_argument("--expected-giab-manifest-sha256", required=True)
    parser.add_argument("--gatk-version", required=True)
    parser.add_argument("--caller-attestation-dir", type=Path)
    parser.add_argument("--gatk-vcf", type=Path)
    parser.add_argument("--deepvariant-vcf", type=Path)
    parser.add_argument("--dragen-vcf", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 2,
        "started_at": utc_now(),
        "scope": "FULL_GENOME_GERMLINE_SNV_INDEL_QUALIFICATION",
        "completion_claim": False,
        "results": [],
        "failures": [],
    }
    try:
        reference = load_reference(
            args.reference_manifest,
            args.reference_fasta,
            expected_package_checksum=args.expected_reference_package_checksum,
        )
        report["reference"] = reference
        giab_evidence = validate_giab_manifest(
            args.giab_manifest,
            args.giab_truth_vcf,
            args.giab_confident_bed,
            reference,
            expected_manifest_sha256=args.expected_giab_manifest_sha256,
        )
        report["giab"] = giab_evidence
        gatk = require_gatk(args.gatk_version)
        report["toolchain"] = {"gatk": gatk}
        local_inputs = (args.gatk_vcf, args.deepvariant_vcf, args.dragen_vcf)
        if any(local_inputs) and not all(local_inputs):
            raise QualificationBlocked(
                "LOCAL_CALLSETS_REQUIRE_ALL_THREE: supply --gatk-vcf, --deepvariant-vcf, and --dragen-vcf together."
            )
        if all(local_inputs):
            callsets = build_local_callsets(
                args.gatk_vcf, args.deepvariant_vcf, args.dragen_vcf
            )
        else:
            callsets = download_callsets(args.work_dir)
            for callset in callsets:
                callset["source_kind"] = "PUBLIC_REFERENCE_FIXTURE"
        observed = {item["caller"] for item in callsets}
        if observed != REQUIRED_CALLERS:
            raise QualificationBlocked(
                f"Expected exactly {sorted(REQUIRED_CALLERS)}, observed {sorted(observed)}"
            )
        for callset in callsets:
            try:
                result = qualify_one(
                    callset, reference=reference, truth=args.giab_truth_vcf,
                    confident_bed=args.giab_confident_bed, giab=giab_evidence,
                    output=args.work_dir, gatk=gatk,
                    caller_attestation_dir=args.caller_attestation_dir,
                )
            except Exception as exc:
                result = {
                    "caller": callset.get("caller"),
                    "status": "BLOCKED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "finished_at": utc_now(),
                }
                report["failures"].append(f"{callset.get('caller')}: {type(exc).__name__}: {exc}")
            report["results"].append(result)
    except Exception as exc:
        report["failures"].append(f"{type(exc).__name__}: {exc}")
        report["setup_error"] = {"type": type(exc).__name__, "message": str(exc)}
    all_callers_completed = (
        len(report["results"]) == 3
        and {item.get("caller") for item in report["results"]} == REQUIRED_CALLERS
        and all(
            item.get("status") in {"PASS", "PASS_WITH_REVIEW_REQUIRED"}
            for item in report["results"]
        )
    )
    any_review_required = any(
        item.get("status") == "PASS_WITH_REVIEW_REQUIRED"
        or item.get("review_required") is True
        for item in report["results"]
    )
    if all_callers_completed and not report["failures"]:
        report["overall"] = "PASS_WITH_REVIEW_REQUIRED" if any_review_required else "PASS"
    else:
        report["overall"] = "FAIL"
    report["completion_claim"] = report["overall"] == "PASS"
    report["finished_at"] = utc_now()
    temporary = args.report.with_suffix(args.report.suffix + ".partial")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.report)
    print(json.dumps({
        "overall": report["overall"],
        "completion_claim": report["completion_claim"],
        "callers": [
            {"caller": item.get("caller"), "status": item.get("status")}
            for item in report["results"]
        ],
        "failures": report["failures"],
        "report": str(args.report.resolve()),
    }, indent=2))
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
