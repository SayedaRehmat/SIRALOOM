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
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

REPORT_NAME = "giab-concordance.json"
FAILURE_NAME = "giab-concordance.failure.json"
SUMMARY_SUFFIX = ".summary.csv"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
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


def _open_text(path: Path) -> TextIO:
    if path.name.endswith((".gz", ".bgz")):
        return gzip.open(path, "rt", encoding="utf-8", errors="strict")
    return path.open("rt", encoding="utf-8", errors="strict")


def validate_single_sample_vcf(path: Path, label: str) -> None:
    header = None
    try:
        with _open_text(path) as handle:
            for line in handle:
                if line.startswith("#CHROM"):
                    header = line.rstrip("\r\n").split("\t")
                    break
    except (OSError, UnicodeError, gzip.BadGzipFile) as exc:
        raise ConcordanceError(f"{label} header could not be read.") from exc
    if header is None or len(header) < 10 or header[8] != "FORMAT":
        raise ConcordanceError(f"{label} must contain exactly one sample column.")
    if len(header) != 10 or not header[9].strip():
        raise ConcordanceError(f"{label} must contain exactly one named sample column.")


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
    required = {"Type", "Filter", "TRUTH.TP", "TRUTH.FN", "QUERY.FP"}
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
                tp = _integer(row, "TRUTH.TP", row_number)
                fn = _integer(row, "TRUTH.FN", row_number)
                fp = _integer(row, "QUERY.FP", row_number)
                truth_total = tp + fn
                precision_denominator = tp + fp
                recall = tp / truth_total if truth_total else None
                precision = tp / precision_denominator if precision_denominator else None
                f1 = (
                    2.0 * precision * recall / (precision + recall)
                    if precision is not None and recall is not None and precision + recall > 0
                    else None
                )
                parsed.append({
                    "variant_type": variant_type,
                    "filter": filter_name,
                    "true_positive": tp,
                    "false_negative": fn,
                    "false_positive": fp,
                    "truth_positive_denominator": truth_total,
                    "query_positive_denominator": precision_denominator,
                    "recall": round(recall, 6) if recall is not None else None,
                    "recall_wilson_95_ci": wilson_interval(tp, truth_total),
                    "precision": round(precision, 6) if precision is not None else None,
                    "precision_wilson_95_ci": wilson_interval(tp, precision_denominator),
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
    output_dir: Path,
    hap_py: str = "hap.py",
    engine: str = "xcmp",
    threads: int = 4,
    target_regions: Path | None = None,
    pass_only: bool = False,
    timeout_seconds: int = 86400,
) -> dict[str, Any]:
    if reference_build not in {"GRCh37", "GRCh38"}:
        raise ConcordanceError("reference_build must be GRCh37 or GRCh38.")
    if assay not in {"WES", "WGS", "PANEL"}:
        raise ConcordanceError("assay must be WES, WGS, or PANEL.")
    if not caller.strip() or not caller_version.strip():
        raise ConcordanceError("Exact caller name and version are required.")
    if engine not in {"xcmp", "vcfeval"}:
        raise ConcordanceError("engine must be xcmp or vcfeval.")
    if threads < 1 or timeout_seconds < 1:
        raise ConcordanceError("threads and timeout_seconds must be positive.")

    inputs: dict[str, Path] = {
        "truth_vcf": _regular_file(truth_vcf, "Truth VCF"),
        "query_vcf": _regular_file(query_vcf, "Query VCF"),
        "confident_bed": _regular_file(confident_bed, "GIAB confident-region BED"),
        "reference_fasta": _regular_file(reference_fasta, "Reference FASTA"),
    }
    reference_fai = _regular_file(str(inputs["reference_fasta"]) + ".fai", "Reference FASTA .fai")
    inputs["reference_fai"] = reference_fai
    if target_regions is not None:
        inputs["target_regions"] = _regular_file(target_regions, "Assay target BED")
    validate_single_sample_vcf(inputs["truth_vcf"], "Truth VCF")
    validate_single_sample_vcf(inputs["query_vcf"], "Query VCF")

    hashes_before = {name: sha256_file(path) for name, path in inputs.items()}
    if output_dir.is_symlink() or output_dir.exists():
        raise ConcordanceError("Output directory must not already exist; prior evidence is preserved.")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(mode=0o700)
    output_dir.chmod(0o700)
    output_dir = output_dir.resolve()

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
    command = [
        hap_py,
        str(inputs["truth_vcf"]),
        str(inputs["query_vcf"]),
        "--reference", str(inputs["reference_fasta"]),
        "--confident-regions", str(inputs["confident_bed"]),
        "--engine", engine,
        "--threads", str(threads),
        "--output", str(prefix),
    ]
    # hap.py's documented short options are stable across supported releases.
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
    hashes_after = {name: sha256_file(path) for name, path in inputs.items()}
    if hashes_before != hashes_after:
        raise ConcordanceError("One or more benchmark inputs changed during execution.")

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
            "comparison_engine": engine,
            "threads": threads,
        },
        "intended_use_cell": {
            "assay": assay,
            "caller": caller.strip(),
            "caller_version": caller_version.strip(),
            "reference_build": reference_build,
        },
        "inputs": {
            name: {"size_bytes": path.stat().st_size, "sha256": hashes_before[name]}
            for name, path in inputs.items()
        },
        "sample_identifiers_recorded": False,
        "filter_policy": "PASS_ONLY" if pass_only else "ALL_FILTER_STATES_REPORTED",
        "metrics": metrics,
        "source_artifacts": {
            "hap_py_summary": summary_path.name,
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
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--hap-py", default="hap.py")
    parser.add_argument("--engine", choices=("xcmp", "vcfeval"), default="xcmp")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--target-regions", type=Path)
    parser.add_argument("--pass-only", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    args = parser.parse_args()
    try:
        report = run_concordance(
            truth_vcf=args.truth_vcf, query_vcf=args.query_vcf,
            confident_bed=args.confident_bed, reference_fasta=args.reference_fasta,
            reference_build=args.reference_build, assay=args.assay,
            caller=args.caller, caller_version=args.caller_version,
            output_dir=args.output_dir, hap_py=args.hap_py, engine=args.engine,
            threads=args.threads, target_regions=args.target_regions,
            pass_only=args.pass_only, timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        # Keep failure records free of exception messages, paths and sample identifiers.
        try:
            if args.output_dir.is_dir() and not args.output_dir.is_symlink():
                failure = {
                    "schema_version": "1",
                    "status": "FAILED",
                    "exception_type": type(exc).__name__,
                    "generated_at_utc": datetime.now(UTC).isoformat(),
                }
                path = args.output_dir / FAILURE_NAME
                path.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                path.chmod(0o600)
        except OSError:
            pass
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
