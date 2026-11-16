#!/usr/bin/env python3
"""Full-genome qualification runner for real germline SNV/indel caller VCFs.

This is deliberately separate from run_real_caller_vcf_smoke.py. It never
constructs a chromosome projection or substitutes a reference. It requires an
already-built reference package plus a versioned GIAB truth VCF and confident
BED. A caller is qualified only when every required gate executes and passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.domain.ebi_vcf_validator import (
    assess_ebi_vcf_compatibility,
    run_ebi_vcf_assembly_checker,
    run_ebi_vcf_validator,
)
from backend.app.domain.reference_package import sha256_file, validate_fasta_index_consistency
from backend.app.domain.vcf_caller_profiles import inspect_caller_provenance
from backend.app.domain.vcf_compatibility import create_dragen_v42_event_projection
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import validate_vcf_reference_alleles, validate_vcf_strict
from scripts.validation.run_real_caller_vcf_smoke import (
    download_callsets,
    EXPECTED_PROFILES,
    dragen_gp_attestation,
)

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


def load_reference(manifest_path: Path, fasta_arg: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fasta = fasta_arg.resolve()
    fai = Path(str(fasta) + ".fai")
    if not fasta.is_file() or not fai.is_file():
        raise QualificationBlocked("REFERENCE_ASSET_MISSING: full FASTA and adjacent .fai are required")
    expected_fasta = manifest.get("fasta_sha256")
    expected_fai = manifest.get("fai_sha256")
    if not expected_fasta or sha256_file(fasta) != expected_fasta:
        raise QualificationBlocked("REFERENCE_FASTA_CHECKSUM_MISMATCH")
    if not expected_fai or sha256_file(fai) != expected_fai:
        raise QualificationBlocked("REFERENCE_FAI_CHECKSUM_MISMATCH")
    contigs = validate_fasta_index_consistency(fasta, fai)
    if contigs != manifest.get("contigs"):
        raise QualificationBlocked("REFERENCE_CONTIG_MANIFEST_MISMATCH")
    if manifest.get("contig_policy") != "EXACT":
        raise QualificationBlocked("REFERENCE_CONTIG_POLICY_MUST_BE_EXACT")
    if not manifest.get("assembly_accession") or not manifest.get("sequence_scope"):
        raise QualificationBlocked("REFERENCE_ASSEMBLY_IDENTITY_INCOMPLETE")
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256_file(manifest_path),
        "fasta_path": str(fasta),
        "fasta_sha256": expected_fasta,
        "fai_path": str(fai),
        "fai_sha256": expected_fai,
        "assembly_name": manifest["assembly_name"],
        "assembly_accession": manifest["assembly_accession"],
        "sequence_scope": manifest["sequence_scope"],
        "package_version": manifest["package_version"],
        "package_checksum": manifest.get("package_checksum"),
        "contigs": contigs,
        "contig_count": len(contigs),
        "scope": "FULL_REFERENCE_PACKAGE",
    }


def require_gatk() -> str:
    executable = shutil.which("gatk")
    if not executable:
        raise QualificationBlocked("GATK_VALIDATEVARIANTS_UNAVAILABLE")
    return executable


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
    confident_bed: Path, output: Path, gatk: str,
) -> dict[str, Any]:
    caller = callset["caller"]
    source = Path(callset["local_path"]).resolve()
    result: dict[str, Any] = {
        "caller": caller,
        "source_filename": callset["filename"],
        "source_bytes": source.stat().st_size,
        "source_sha256": sha256_file(source),
        "source_publisher_checksum": callset.get("zenodo_checksum"),
        "source_checksum_verified": callset.get("verified_source_checksum", False),
        "scope": "FULL_SOURCE_VCF",
        "started_at": utc_now(),
        "gates": {},
    }
    if not result["source_checksum_verified"]:
        raise QualificationBlocked(f"{caller}: publisher checksum was not verified")
    provenance = inspect_caller_provenance(source)
    result["caller_provenance"] = provenance
    if provenance.get("caller_profile_id") != EXPECTED_PROFILES[caller]:
        raise QualificationBlocked(f"{caller}: caller profile identity does not match expected profile")

    caller_attestation = dragen_gp_attestation(callset, source)
    strict = validate_vcf_strict(
        source,
        caller_attestation=caller_attestation,
        artifact_sha256=result["source_sha256"],
        expected_reference_build="GRCh38",
    )
    result["caller_semantic_attestation"] = strict.get("caller_semantic_attestation")
    result["gates"]["siraloom_strict"] = {
        "status": "PASS",
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
        projection_ebi_compatibility = projection_ebi.get("compatibility_assessment") or {}
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
    if caller == "DRAGEN" and strict.get("caller_semantic_compatibility_review_required"):
        sequence_attestation = dragen_gp_attestation(callset, sequence_vcf)
        sequence_strict = validate_vcf_strict(
            sequence_vcf,
            caller_attestation=sequence_attestation,
            artifact_sha256=result["source_sha256"],
            expected_reference_build="GRCh38",
        )
        gatk_projection_path = gatk_dir / "sequence.event-projected.vcf"
        gatk_projection_evidence = create_dragen_v42_event_projection(
            sequence_vcf,
            gatk_projection_path,
            caller_semantic_attestation=sequence_strict.get("caller_semantic_attestation"),
        )
        gatk_input_vcf = gatk_projection_path
    gatk_log = gatk_dir / "validatevariants.stdout.log"
    gatk_evidence = run_command(
        [gatk, "ValidateVariants", "-R", reference["fasta_path"], "-V", str(gatk_input_vcf)],
        timeout=6 * 60 * 60,
        stdout_path=gatk_log,
    )
    result["gates"]["gatk_validate_variants"] = {
        **gatk_evidence,
        "input_path": str(gatk_input_vcf),
        "input_sha256": sha256_file(gatk_input_vcf),
        "input_scope": "REFERENCE_RESOLVED_SEQUENCE_RECORDS",
        "source_vcf_sha256": result["source_sha256"],
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
    normalized_attestation = dragen_gp_attestation(callset, normalized)
    normalized_strict = validate_vcf_strict(
        normalized,
        caller_attestation=normalized_attestation,
        artifact_sha256=result["source_sha256"],
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
    }

    result["gates"]["giab_happy"] = run_happy(
        truth, normalized, confident_bed, Path(reference["fasta_path"]),
        output / caller.lower() / "giab" / "hap.py",
    )
    result["status"] = "PASS"
    result["finished_at"] = utc_now()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--reference-fasta", type=Path, required=True)
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--giab-truth-vcf", type=Path, required=True)
    parser.add_argument("--giab-confident-bed", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": 1,
        "started_at": utc_now(),
        "scope": "FULL_GENOME_GERMLINE_SNV_INDEL_QUALIFICATION",
        "completion_claim": False,
        "results": [],
        "failures": [],
    }
    try:
        reference = load_reference(args.reference_manifest, args.reference_fasta)
        report["reference"] = reference
        report["giab"] = {
            "truth_vcf": str(args.giab_truth_vcf.resolve()),
            "truth_vcf_sha256": sha256_file(args.giab_truth_vcf),
            "confident_bed": str(args.giab_confident_bed.resolve()),
            "confident_bed_sha256": sha256_file(args.giab_confident_bed),
            "truth_version_and_assembly_must_be_reviewed": True,
        }
        gatk = require_gatk()
        callsets = download_callsets(args.work_dir)
        observed = {item["caller"] for item in callsets}
        if observed != REQUIRED_CALLERS:
            raise QualificationBlocked(
                f"Expected exactly {sorted(REQUIRED_CALLERS)}, observed {sorted(observed)}"
            )
        for callset in callsets:
            try:
                result = qualify_one(
                    callset, reference=reference, truth=args.giab_truth_vcf,
                    confident_bed=args.giab_confident_bed, output=args.work_dir,
                    gatk=gatk,
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
    all_callers_pass = (
        len(report["results"]) == 3
        and {item.get("caller") for item in report["results"]} == REQUIRED_CALLERS
        and all(item.get("status") == "PASS" for item in report["results"])
    )
    report["overall"] = "PASS" if all_callers_pass and not report["failures"] else "FAIL"
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
