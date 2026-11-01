#!/usr/bin/env python3
"""Run a controlled GA4GH/GIAB small-variant concordance benchmark with hap.py.

This measures analytical concordance of a caller VCF against an independently
defined truth set in declared confident regions. It is not clinical validation,
assay validation, or laboratory authorization.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

REPORT_NAME = "giab-concordance.json"
SUMMARY_SUFFIX = ".summary.csv"
VERSION_RE = re.compile(r"\b\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?\b")


class ConcordanceError(RuntimeError):
    """The benchmark inputs, toolchain, or result violate the run contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(value: str | Path, label: str) -> Path:
    path = Path(value)
    if path.is_symlink():
        raise ConcordanceError(f"{label} must not be a symbolic link.")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ConcordanceError(f"{label} does not exist or is inaccessible.") from exc
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise ConcordanceError(f"{label} must be a non-empty regular file.")
    return resolved


def load_sample_mapping(path_value: str | Path) -> tuple[Path, str, str]:
    """Load a private specimen-to-VCF-column map without exposing IDs in CLI args."""
    path = _regular_file(path_value, "Sample mapping file")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise ConcordanceError("Sample mapping file permissions must deny group and other access.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConcordanceError("Sample mapping file is not valid readable JSON.") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version", "truth_sample_name", "query_sample_name"
    }:
        raise ConcordanceError(
            "Sample mapping file must contain exactly schema_version, truth_sample_name, and query_sample_name."
        )
    if payload.get("schema_version") != "1.0":
        raise ConcordanceError("Sample mapping file schema_version must be 1.0.")
    truth_name = payload.get("truth_sample_name")
    query_name = payload.get("query_sample_name")
    if (
        not isinstance(truth_name, str)
        or not truth_name.strip()
        or not isinstance(query_name, str)
        or not query_name.strip()
    ):
        raise ConcordanceError("Sample mapping file must contain non-empty sample-column names.")
    return path, truth_name, query_name


def _open_text(path: Path) -> TextIO:
    if path.name.endswith((".gz", ".bgz")):
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("rt", encoding="utf-8", errors="strict")


def validate_single_sample_vcf(
    path: Path,
    label: str,
    expected_sample_name: str,
) -> None:
    if not isinstance(expected_sample_name, str) or not expected_sample_name.strip():
        raise ConcordanceError(f"{label} requires an explicit specimen-to-sample-column mapping.")
    header = None
    fixed_columns = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO", "FORMAT"]
    try:
        with _open_text(path) as handle:
            fileformat = handle.readline().rstrip("\r\n")
            if not re.fullmatch(r"##fileformat=VCFv4\.[0-5]", fileformat):
                raise ConcordanceError(f"{label} must begin with a supported VCFv4 fileformat declaration.")
            for line in handle:
                if line.startswith("#CHROM"):
                    header = line.rstrip("\r\n").split("\t")
                    break
                if not line.startswith("#"):
                    raise ConcordanceError(f"{label} contains data before the #CHROM header.")
            if header is None or header[:9] != fixed_columns:
                raise ConcordanceError(f"{label} must contain the nine fixed VCF columns in specification order.")
            if len(header) != 10 or not header[9].strip():
                raise ConcordanceError(f"{label} must contain exactly one named sample column.")
            if header[9] != expected_sample_name:
                raise ConcordanceError(
                    f"{label} sample column does not match the explicitly declared specimen mapping."
                )
            for line in handle:
                if not line.strip():
                    raise ConcordanceError(f"{label} contains an empty data line.")
                if line.startswith("#"):
                    raise ConcordanceError(f"{label} contains a header/comment line after #CHROM.")
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) != len(header):
                    raise ConcordanceError(f"{label} contains a malformed variant record.")
                for allele in fields[4].split(","):
                    if allele == "*" or allele.startswith("<") or any(char in allele for char in "[]"):
                        raise ConcordanceError(
                            f"{label} contains symbolic, spanning-deletion, or breakend alleles outside this small-variant benchmark."
                        )
    except ConcordanceError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile) as exc:
        raise ConcordanceError(f"{label} could not be read.") from exc


def resolve_stratification_beds(tsv_path: Path) -> list[dict[str, Any]]:
    regions: list[dict[str, Any]] = []
    names: set[str] = set()
    try:
        lines = tsv_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ConcordanceError("GA4GH stratification TSV could not be read.") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0].strip() or not fields[1].strip():
            raise ConcordanceError(f"GA4GH stratification TSV row {line_number} must contain region name and BED path.")
        name, raw_path = fields[0].strip(), fields[1].strip()
        if name in names:
            raise ConcordanceError("GA4GH stratification region names must be unique.")
        names.add(name)
        bed_path = Path(raw_path)
        if not bed_path.is_absolute():
            bed_path = tsv_path.parent / bed_path
        bed_path = _regular_file(bed_path, f"Stratification BED for region {name}")
        regions.append({"name": name, "path": bed_path})
    if not regions:
        raise ConcordanceError("GA4GH stratification TSV must define at least one BED region.")
    return regions


def validate_bed_file(
    path: Path,
    *,
    contig_lengths: dict[str, int],
    label: str,
) -> dict[str, Any]:
    """Validate BED3+ coordinates against the exact selected reference contigs."""
    records = 0
    observed_contigs: set[str] = set()
    try:
        with _open_text(path) as handle:
            for line_number, line in enumerate(handle, start=1):
                stripped = line.rstrip("\r\n")
                if not stripped.strip() or stripped.startswith("#"):
                    continue
                if stripped.split(maxsplit=1)[0] in {"track", "browser"}:
                    raise ConcordanceError(
                        f"{label} contains a track/browser directive unsupported by hap.py."
                    )
                fields = stripped.split("\t")
                if len(fields) < 3 or not fields[0]:
                    raise ConcordanceError(f"{label} has a malformed BED record at line {line_number}.")
                chrom = fields[0]
                if chrom not in contig_lengths:
                    raise ConcordanceError(
                        f"{label} uses a contig absent from the exact selected reference at line {line_number}."
                    )
                try:
                    start, end = int(fields[1]), int(fields[2])
                except ValueError as exc:
                    raise ConcordanceError(
                        f"{label} has non-integer BED coordinates at line {line_number}."
                    ) from exc
                if start < 0 or end <= start or end > contig_lengths[chrom]:
                    raise ConcordanceError(
                        f"{label} has out-of-bounds or invalid 0-based half-open coordinates at line {line_number}."
                    )
                records += 1
                observed_contigs.add(chrom)
    except ConcordanceError:
        raise
    except (OSError, UnicodeError, gzip.BadGzipFile) as exc:
        raise ConcordanceError(f"{label} could not be read.") from exc
    if records == 0:
        raise ConcordanceError(f"{label} contains no BED intervals.")
    return {
        "record_count": records,
        "contig_count": len(observed_contigs),
        "contigs": sorted(observed_contigs),
        "sha256": sha256_file(path),
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    p = successes / total
    denominator = 1.0 + (z * z / total)
    center = (p + z * z / (2.0 * total)) / denominator
    margin = z * math.sqrt((p * (1.0 - p) / total) + (z * z / (4.0 * total * total))) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def _integer(row: dict[str, str], key: str, row_number: int) -> int:
    try:
        value = int(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConcordanceError(f"hap.py summary row {row_number} has an invalid {key} count.") from exc
    if value < 0:
        raise ConcordanceError(f"hap.py summary row {row_number} has a negative {key} count.")
    return value


def parse_happy_summary(path: Path) -> list[dict[str, Any]]:
    required = {"Type", "Filter", "TRUTH.TOTAL", "TRUTH.TP", "TRUTH.FN", "QUERY.TOTAL", "QUERY.TP", "QUERY.FP", "QUERY.UNK", "FP.gt", "FP.al"}
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                raise ConcordanceError("hap.py summary.csv is missing required GA4GH count columns.")
            parsed: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for row_number, row in enumerate(reader, start=2):
                variant_type = (row.get("Type") or "").upper()
                filter_name = (row.get("Filter") or "").upper()
                if variant_type not in {"SNP", "INDEL"} or filter_name not in {"ALL", "PASS"}:
                    continue
                key = (variant_type, filter_name)
                if key in seen:
                    raise ConcordanceError("hap.py summary.csv contains duplicate type/filter rows.")
                seen.add(key)
                truth_total = _integer(row, "TRUTH.TOTAL", row_number)
                tp = _integer(row, "TRUTH.TP", row_number)
                fn = _integer(row, "TRUTH.FN", row_number)
                query_total = _integer(row, "QUERY.TOTAL", row_number)
                query_tp = _integer(row, "QUERY.TP", row_number)
                fp = _integer(row, "QUERY.FP", row_number)
                query_unknown = _integer(row, "QUERY.UNK", row_number)
                genotype_mismatches = _integer(row, "FP.gt", row_number)
                allele_mismatches = _integer(row, "FP.al", row_number)
                if truth_total != tp + fn:
                    raise ConcordanceError(f"hap.py summary row {row_number} truth counts do not reconcile.")
                if query_total != query_tp + fp + query_unknown:
                    raise ConcordanceError(f"hap.py summary row {row_number} query counts do not reconcile.")
                if genotype_mismatches > fp or allele_mismatches > fp:
                    raise ConcordanceError(
                        f"hap.py summary row {row_number} mismatch subcounts exceed QUERY.FP."
                    )
                precision_denominator = query_tp + fp
                recall = tp / truth_total if truth_total else None
                precision = query_tp / precision_denominator if precision_denominator else None
                f1 = (
                    2.0 * precision * recall / (precision + recall)
                    if precision is not None and recall is not None and precision + recall > 0
                    else None
                )
                parsed.append({
                    "variant_type": variant_type,
                    "filter": filter_name,
                    "truth_true_positive": tp,
                    "query_true_positive": query_tp,
                    "false_negative": fn,
                    "false_positive": fp,
                    "query_unknown": query_unknown,
                    "genotype_mismatches": genotype_mismatches,
                    "allele_mismatches": allele_mismatches,
                    "fraction_not_assessed": round(query_unknown / query_total, 6) if query_total else None,
                    "truth_total": truth_total,
                    "query_total": query_total,
                    "truth_positive_denominator": truth_total,
                    "query_positive_denominator": precision_denominator,
                    "recall": round(recall, 6) if recall is not None else None,
                    "recall_wilson_95_ci": wilson_interval(tp, truth_total),
                    "precision": round(precision, 6) if precision is not None else None,
                    "precision_wilson_95_ci": wilson_interval(query_tp, precision_denominator),
                    "f1": round(f1, 6) if f1 is not None else None,
                })
    except OSError as exc:
        raise ConcordanceError("hap.py summary.csv could not be read.") from exc
    expected = {(kind, filt) for kind in ("SNP", "INDEL") for filt in ("ALL", "PASS")}
    if seen != expected:
        raise ConcordanceError("hap.py summary.csv must contain SNP and INDEL rows for ALL and PASS.")
    return parsed


def run_concordance(
    *,
    truth_vcf: Path,
    query_vcf: Path,
    confident_bed: Path,
    reference_fasta: Path,
    reference_build: str,
    assay: str,
    caller: str,
    caller_version: str,
    sample_mapping_file: Path,
    truth_set_id: str,
    truth_set_version: str,
    acceptance_policy_id: str,
    output_dir: Path,
    hap_py: str = "hap.py",
    engine: str = "xcmp",
    threads: int = 4,
    target_regions: Path | None = None,
    stratification_tsv: Path | None = None,
    pass_only: bool = False,
    timeout_seconds: int = 86400,
) -> dict[str, Any]:
    if reference_build not in {"GRCh37", "GRCh38"}:
        raise ConcordanceError("reference_build must be GRCh37 or GRCh38.")
    if assay not in {"WES", "WGS", "PANEL"}:
        raise ConcordanceError("assay must be WES, WGS, or PANEL.")
    if not caller.strip() or not caller_version.strip():
        raise ConcordanceError("Exact caller name and version are required.")
    if not truth_set_id.strip() or not truth_set_version.strip() or not acceptance_policy_id.strip():
        raise ConcordanceError("Truth-set identity, release, and preapproved acceptance-policy ID are required.")
    if engine not in {"xcmp", "vcfeval"}:
        raise ConcordanceError("engine must be xcmp or vcfeval.")
    if threads < 1 or timeout_seconds < 1:
        raise ConcordanceError("threads and timeout_seconds must be positive.")
    if assay in {"WES", "PANEL"} and target_regions is None:
        raise ConcordanceError("WES and PANEL comparisons require the assay target BED.")

    sample_mapping_path, truth_sample_name, query_sample_name = load_sample_mapping(sample_mapping_file)
    inputs: dict[str, Path] = {
        "truth_vcf": _regular_file(truth_vcf, "Truth VCF"),
        "query_vcf": _regular_file(query_vcf, "Query VCF"),
        "confident_bed": _regular_file(confident_bed, "GIAB confident-region BED"),
        "reference_fasta": _regular_file(reference_fasta, "Reference FASTA"),
        "sample_mapping": sample_mapping_path,
    }
    reference_fai = _regular_file(str(inputs["reference_fasta"]) + ".fai", "Reference FASTA .fai")
    inputs["reference_fai"] = reference_fai
    reference_gzi = Path(str(inputs["reference_fasta"]) + ".gzi")
    if reference_gzi.is_file():
        inputs["reference_gzi"] = _regular_file(reference_gzi, "Reference FASTA .gzi")
    if target_regions is not None:
        inputs["target_regions"] = _regular_file(target_regions, "Assay target BED")
    stratification_regions: list[dict[str, Any]] = []
    if stratification_tsv is not None:
        inputs["stratification_tsv"] = _regular_file(stratification_tsv, "GA4GH stratification TSV")
        stratification_regions = resolve_stratification_beds(inputs["stratification_tsv"])
        for index, region in enumerate(stratification_regions, start=1):
            inputs[f"stratification_bed_{index}"] = region["path"]

    from backend.app.domain.reference_package import (
        contig_manifest_sha256,
        validate_fasta_index_consistency,
    )

    try:
        reference_contigs = validate_fasta_index_consistency(
            inputs["reference_fasta"], inputs["reference_fai"]
        )
    except (OSError, ValueError) as exc:
        raise ConcordanceError("Reference FASTA and FAI geometry are inconsistent.") from exc
    contig_lengths = {str(item["name"]): int(item["length"]) for item in reference_contigs}
    region_validation: dict[str, Any] = {
        "confident_bed": validate_bed_file(
            inputs["confident_bed"], contig_lengths=contig_lengths, label="GIAB confident-region BED"
        )
    }
    if "target_regions" in inputs:
        region_validation["target_regions"] = validate_bed_file(
            inputs["target_regions"], contig_lengths=contig_lengths, label="Assay target BED"
        )
    for index, region in enumerate(stratification_regions, start=1):
        region_validation[f"stratification_bed_{index}"] = validate_bed_file(
            region["path"], contig_lengths=contig_lengths, label=f"Stratification BED {region['name']}"
        )

    validate_single_sample_vcf(inputs["truth_vcf"], "Truth VCF", truth_sample_name)
    validate_single_sample_vcf(inputs["query_vcf"], "Query VCF", query_sample_name)

    hashes_before = {name: sha256_file(path) for name, path in inputs.items()}
    if output_dir.is_symlink() or output_dir.exists():
        raise ConcordanceError("Output directory must not already exist; prior evidence is preserved.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    output_dir = output_dir.resolve()

    executable = shutil.which(hap_py)
    if executable is None:
        raise ConcordanceError("hap.py executable could not be resolved from PATH.")
    executable_path = Path(executable).resolve(strict=True)
    if not executable_path.is_file():
        raise ConcordanceError("hap.py executable is not a regular file.")
    executable_sha256_before = sha256_file(executable_path)
    version_cmd = [hap_py, "--version"]
    log_path = output_dir / "hap.py.log"
    try:
        version_result = subprocess.run(
            version_cmd, check=False, capture_output=True, text=True, timeout=30, shell=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConcordanceError("hap.py executable/version probe failed.") from exc
    version_text = (version_result.stdout + "\n" + version_result.stderr).strip()
    version_match = VERSION_RE.search(version_text)
    if version_result.returncode != 0 or not version_match:
        raise ConcordanceError("hap.py did not return a parseable runtime version.")
    hap_version = version_match.group(0)

    prefix = output_dir / "comparison"
    # hap.py documents -f for confident regions and -T for dense assay targets.
    command = [
        hap_py, str(inputs["truth_vcf"]), str(inputs["query_vcf"]),
        "-r", str(inputs["reference_fasta"]),
        "-f", str(inputs["confident_bed"]),
        "-o", str(prefix),
        "--engine", engine,
        "--threads", str(threads),
    ]
    if target_regions is not None:
        command.extend(["--target-regions", str(inputs["target_regions"])])
    if pass_only:
        command.append("--pass-only")
    if stratification_tsv is not None:
        command.extend(["--stratification", str(inputs["stratification_tsv"])])

    started = datetime.now(UTC)
    try:
        with log_path.open("x", encoding="utf-8") as log:
            log_path.chmod(0o600)
            completed = subprocess.run(
                command, check=False, stdout=log, stderr=subprocess.STDOUT,
                text=True, timeout=timeout_seconds, shell=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise ConcordanceError("hap.py exceeded the configured timeout.") from exc
    except OSError as exc:
        raise ConcordanceError("hap.py execution could not be started.") from exc
    finished = datetime.now(UTC)
    if completed.returncode != 0:
        raise ConcordanceError(f"hap.py exited with status {completed.returncode}; inspect the restricted run log.")

    summary_path = Path(str(prefix) + SUMMARY_SUFFIX)
    metrics = parse_happy_summary(summary_path)
    runinfo_path = Path(str(prefix) + ".runinfo.json")
    if not runinfo_path.is_file():
        raise ConcordanceError("hap.py runinfo.json is missing; runtime argument provenance is incomplete.")
    extended_path = Path(str(prefix) + ".extended.csv")
    if stratification_tsv is not None and not extended_path.is_file():
        raise ConcordanceError("Stratification was requested but hap.py did not produce extended.csv.")
    hashes_after = {name: sha256_file(path) for name, path in inputs.items()}
    if hashes_before != hashes_after:
        raise ConcordanceError("One or more benchmark inputs changed during execution.")
    if os.name == "posix" and inputs["sample_mapping"].stat().st_mode & 0o077:
        raise ConcordanceError("Sample mapping file permissions became group/other accessible during execution.")
    if sha256_file(executable_path) != executable_sha256_before:
        raise ConcordanceError("The hap.py executable changed during benchmark execution.")

    report = {
        "schema_version": "1",
        "status": "CONCORDANCE_RUN_COMPLETE_REVIEW_REQUIRED",
        "benchmark_kind": "GIAB_GA4GH_SMALL_VARIANT_CONCORDANCE",
        "generated_at_utc": finished.isoformat(),
        "started_at_utc": started.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "environment": {
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "hap_py_version": hap_version,
            "hap_py_executable_sha256": executable_sha256_before,
            "repository_commit": os.environ.get("GITHUB_SHA"),
            "comparison_engine": engine,
            "threads": threads,
        },
        "intended_use_cell": {
            "assay": assay,
            "caller": caller.strip(),
            "caller_version": caller_version.strip(),
            "reference_build": reference_build,
            "truth_set_id": truth_set_id.strip(),
            "truth_set_version": truth_set_version.strip(),
            "acceptance_policy_id": acceptance_policy_id.strip(),
        },
        "inputs": {
            name: {"size_bytes": path.stat().st_size, "sha256": hashes_before[name]}
            for name, path in inputs.items()
        },
        "reference_identity": {
            "declared_build": reference_build,
            "fasta_sha256": hashes_before["reference_fasta"],
            "fai_sha256": hashes_before["reference_fai"],
            "contig_manifest_sha256": contig_manifest_sha256(reference_contigs),
            "contig_count": len(reference_contigs),
        },
        "region_validation": region_validation,
        "stratification_regions": [
            {
                "name": region["name"],
                "input_key": f"stratification_bed_{index}",
                "sha256": hashes_before[f"stratification_bed_{index}"],
            }
            for index, region in enumerate(stratification_regions, start=1)
        ],
        "sample_mapping_schema_version": "1.0",
        "sample_identity": {
            "truth_sample_column_verified": True,
            "query_sample_column_verified": True,
            "sample_identifiers_recorded": False,
        },
        "sample_identifiers_recorded": False,
        "filter_policy": "PASS_ONLY" if pass_only else "ALL_FILTER_STATES_REPORTED",
        "metrics": metrics,
        "source_artifacts": {
            "hap_py_summary": summary_path.name,
            "hap_py_summary_sha256": sha256_file(summary_path),
            "hap_py_runinfo": runinfo_path.name,
            "hap_py_runinfo_sha256": sha256_file(runinfo_path),
            "hap_py_extended": extended_path.name if extended_path.is_file() else None,
            "hap_py_extended_sha256": sha256_file(extended_path) if extended_path.is_file() else None,
            "hap_py_log": log_path.name,
        },
        "acceptance_boundary": (
            "This report is technical small-variant concordance evidence within the declared "
            "GIAB confident regions and optional assay target regions only. It does not qualify "
            "the caller, establish performance outside those regions, validate clinical "
            "interpretation, or authorize clinical use. Laboratory-approved criteria and "
            "independent review are required. Exome/panel estimates require particular caution "
            "and confidence intervals because benchmark variants may be sparse or unrepresentative."
        ),
    }
    report_path = output_dir / REPORT_NAME
    temporary = output_dir / f".{REPORT_NAME}.tmp"
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truth-vcf", required=True, type=Path)
    parser.add_argument("--query-vcf", required=True, type=Path)
    parser.add_argument("--confident-bed", required=True, type=Path)
    parser.add_argument("--reference-fasta", required=True, type=Path)
    parser.add_argument("--reference-build", required=True, choices=("GRCh37", "GRCh38"))
    parser.add_argument("--assay", required=True, choices=("WES", "WGS", "PANEL"))
    parser.add_argument("--caller", required=True)
    parser.add_argument("--caller-version", required=True)
    parser.add_argument("--sample-mapping-file", required=True)
    parser.add_argument("--truth-set-id", required=True)
    parser.add_argument("--truth-set-version", required=True)
    parser.add_argument("--acceptance-policy-id", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--hap-py", default="hap.py")
    parser.add_argument("--engine", choices=("xcmp", "vcfeval"), default="xcmp")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--target-regions", type=Path)
    parser.add_argument("--stratification-tsv", type=Path)
    parser.add_argument("--pass-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    args = parser.parse_args()
    try:
        report = run_concordance(
            truth_vcf=args.truth_vcf, query_vcf=args.query_vcf,
            confident_bed=args.confident_bed, reference_fasta=args.reference_fasta,
            reference_build=args.reference_build, assay=args.assay,
            caller=args.caller, caller_version=args.caller_version,
            sample_mapping_file=Path(args.sample_mapping_file),
            truth_set_id=args.truth_set_id, truth_set_version=args.truth_set_version,
            acceptance_policy_id=args.acceptance_policy_id,
            output_dir=args.output_dir, hap_py=args.hap_py, engine=args.engine,
            threads=args.threads, target_regions=args.target_regions,
            stratification_tsv=args.stratification_tsv,
            pass_only=args.pass_only, timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"GIAB concordance benchmark failed: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": report["status"],
        "report": str(args.output_dir.resolve() / REPORT_NAME),
        "metrics": report["metrics"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
