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
            if header is None or len(header) < 10 or header[8] != "FORMAT":
                raise ConcordanceError(f"{label} must contain exactly one sample column.")
            if len(header) != 10 or not header[9].strip():
                raise ConcordanceError(f"{label} must contain exactly one named sample column.")
            for line in handle:
                if not line or line.startswith("#"):
                    continue
                fields = line.rstrip("\r\n").split("\t")
                if len(fields) < 10:
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

    inputs: dict[str, Path] = {
        "truth_vcf": _regular_file(truth_vcf, "Truth VCF"),
        "query_vcf": _regular_file(query_vcf, "Query VCF"),
        "confident_bed": _regular_file(confident_bed, "GIAB confident-region BED"),
        "reference_fasta": _regular_file(reference_fasta, "Reference FASTA"),
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
    validate_single_sample_vcf(inputs["truth_vcf"], "Truth VCF")
    validate_single_sample_vcf(inputs["query_vcf"], "Query VCF")

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
        "stratification_regions": [
            {
                "name": region["name"],
                "input_key": f"stratification_bed_{index}",
                "sha256": hashes_before[f"stratification_bed_{index}"],
            }
            for index, region in enumerate(stratification_regions, start=1)
        ],
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
