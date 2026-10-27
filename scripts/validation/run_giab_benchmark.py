#!/usr/bin/env python3
"""Run a manifest-pinned GIAB small-variant comparison with hap.py/vcfeval.

This runner reports observed metrics and provenance. It deliberately does not
declare a scientific PASS: an approved, intended-use-specific acceptance policy
and discrepancy review are required before the result can be accepted.
"""
from __future__ import annotations

import argparse
import csv
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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REQUIRED_ASSETS = (
    "truth_vcf",
    "confident_regions_bed",
    "reference_fasta",
    "reference_fai",
    "input_vcf",
    "siraloom_normalized_vcf",
)


class BenchmarkConfigurationError(ValueError):
    pass


def verify_version_pin(tool: str, expected: str, version_result: dict[str, Any]) -> None:
    output = str(version_result.get("output") or "")
    version_pattern = r"^bcftools\s+(\S+)" if tool == "bcftools" else r"^Hap\.py\s+v?(\S+)"
    observed = next(
        (match.group(1) for line in output.splitlines() if (match := re.match(version_pattern, line.strip(), re.IGNORECASE))),
        None,
    )
    if version_result.get("exit_code") != 0 or observed != expected:
        raise BenchmarkConfigurationError(
            f"{tool} version could not be confirmed against manifest pin {expected!r}; "
            f"observed version was {observed!r}; version command output was: {output[:1000]!r}"
        )


def hash_vcf_records(path: Path) -> tuple[int, str]:
    """Hash VCF record lines in order, excluding headers and compression bytes."""
    opener = gzip.open if path.suffix.lower() in {".gz", ".bgz"} else open
    digest = hashlib.sha256()
    count = 0
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            digest.update(line.encode("utf-8"))
            count += 1
    return count, digest.hexdigest()


def verify_normalization_derivation(
    *, input_vcf: Path, normalized_vcf: Path, reference_fasta: Path,
    bcftools: str, expected_version: str,
) -> dict[str, Any]:
    """Reproduce production routing and BCFtools sequence normalization, then compare records."""
    from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records

    version = run_command([bcftools, "--version"])
    verify_version_pin("bcftools", expected_version, version)
    with tempfile.TemporaryDirectory(prefix="siraloom-giab-normalization-") as temporary:
        work = Path(temporary)
        routing = route_vcf_records(input_vcf, work / "routed")
        if not routing["sequence_path"]:
            raise BenchmarkConfigurationError(
                "Raw input has no supported sequence-variant records for the configured benchmark."
            )
        normalized = work / "normalized.vcf.gz"
        normalization = normalize_vcf_with_bcftools(
            routing["sequence_path"],
            normalized,
            reference_fasta=reference_fasta,
            expected_bcftools_version=expected_version,
            bcftools_executable=bcftools,
        )
        if not normalized.is_file() or normalized.stat().st_size == 0:
            raise RuntimeError("Pinned BCFtools normalization produced no reproducible VCF.")
        reproduced_count, reproduced_sha256 = hash_vcf_records(normalized)
    observed_count, observed_sha256 = hash_vcf_records(normalized_vcf)
    if (observed_count, observed_sha256) != (reproduced_count, reproduced_sha256):
        raise BenchmarkConfigurationError(
            "Normalized query records do not match the pinned BCFtools transformation of input_vcf "
            "against the manifest reference."
        )
    return {
        "status": "REPRODUCED_RECORDS_MATCH",
        "record_count": observed_count,
        "ordered_record_sha256": observed_sha256,
        "input_routing": {
            "routing_version": routing["routing_version"],
            "records_total": routing["records_total"],
            "sequence_records": routing["sequence_records"],
            "gvcf_reference_blocks": routing["gvcf_reference_blocks"],
            "gvcf_unresolved_variant_records": routing["gvcf_unresolved_variant_records"],
            "structural_variant_records": routing["structural_variant_records"],
            "spanning_deletion_records": routing["spanning_deletion_records"],
            "policy": routing["gvcf_wildcard_policy"],
        },
        "bcftools_version": version["output"],
        "commands": normalization["command"].split(" && "),
        "comparison_scope": "Production-routed sequence VCF data-record lines only; headers/compression bytes are excluded",
    }


def select_benchmark_sample(
    *, vcf: Path, sample_name: str, bcftools: str, output_path: Path,
) -> dict[str, Any]:
    """Create a single-sample VCF only after confirming the requested sample exists."""
    available = run_command([bcftools, "query", "-l", str(vcf)])
    sample_names = [line.strip() for line in available["output"].splitlines() if line.strip()]
    if sample_name not in sample_names:
        raise BenchmarkConfigurationError(
            f"Requested benchmark sample {sample_name!r} is absent from {vcf}; "
            f"available sample columns: {sample_names}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output_path.name}.", dir=output_path.parent) as temporary:
        staged_path = Path(temporary) / output_path.name
        command = [bcftools, "view", "-s", sample_name, "-Ov", "-o", str(staged_path), str(vcf)]
        selection = run_command(command)
        verified = run_command([bcftools, "query", "-l", str(staged_path)])
        selected_names = [line.strip() for line in verified["output"].splitlines() if line.strip()]
        if selected_names != [sample_name]:
            raise RuntimeError(
                f"bcftools sample selection produced columns {selected_names}, expected only {sample_name!r}."
            )
        if not staged_path.is_file() or staged_path.stat().st_size == 0:
            raise RuntimeError("bcftools sample selection produced no VCF artifact.")
        os.replace(staged_path, output_path)
    return {
        "sample_name": sample_name,
        "available_samples": sample_names,
        "selected_vcf": str(output_path),
        "selected_vcf_sha256": sha256_file(output_path),
        "commands": [available["command"], selection["command"], verified["command"]],
        "publication": "validated_staged_file_atomically_replaced_destination",
    }


def parse_happy_summary(path: Path) -> dict[str, Any]:
    """Extract observed hap.py counts/metrics without deciding acceptance.

    hap.py's summary schema is documented by the upstream project. Keep raw
    CSV as the source artifact and fail closed if its expected fields/rows are
    absent, rather than emitting a deceptively successful empty report.
    """
    required = {
        "Type", "Filter", "TRUTH.TOTAL", "TRUTH.TP", "TRUTH.FN",
        "QUERY.TOTAL", "QUERY.TP", "QUERY.FP", "QUERY.UNK",
        "METRIC.Recall", "METRIC.Precision", "METRIC.F1_Score",
    }
    rows_by_type: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise RuntimeError(f"hap.py summary is missing required columns: {missing}")
        for row in reader:
            variant_type = (row.get("Type") or "").strip().upper()
            filter_name = (row.get("Filter") or "").strip()
            if variant_type not in {"SNP", "INDEL"} or filter_name not in {"PASS", "ALL"}:
                continue
            if filter_name in rows_by_type.setdefault(variant_type, {}):
                raise RuntimeError(f"hap.py summary has duplicate {variant_type}/{filter_name} rows")
            try:
                counts = {
                    name: int(row[column])
                    for name, column in {
                        "truth_total": "TRUTH.TOTAL", "truth_tp": "TRUTH.TP",
                        "truth_fn": "TRUTH.FN", "query_total": "QUERY.TOTAL",
                        "query_tp": "QUERY.TP", "query_fp": "QUERY.FP",
                        "query_unk": "QUERY.UNK",
                    }.items()
                }
                metrics: dict[str, float | None] = {}
                for name, column in {
                    "recall": "METRIC.Recall", "precision": "METRIC.Precision",
                    "f1_score": "METRIC.F1_Score",
                }.items():
                    raw_metric = row[column].strip()
                    if raw_metric.lower() in {"", "nan", "na"}:
                        metrics[name] = None
                        continue
                    metric = Decimal(raw_metric)
                    if not metric.is_finite() or not 0 <= metric <= 1:
                        raise ValueError(f"{column} must be finite and between 0 and 1")
                    metrics[name] = float(metric)
            except (ValueError, KeyError, InvalidOperation) as exc:
                raise RuntimeError(f"Invalid hap.py summary values for {variant_type}: {exc}") from exc
            if any(value < 0 for value in counts.values()):
                raise RuntimeError(f"Negative hap.py count in {variant_type} row")
            rows_by_type[variant_type][filter_name] = {"filter": filter_name, **counts, **metrics}
    if not {"SNP", "INDEL"}.issubset(rows_by_type):
        raise RuntimeError("hap.py summary must contain SNP and INDEL rows for PASS or ALL")
    return {
        variant_type: (filters.get("PASS") or filters.get("ALL"))
        for variant_type, filters in rows_by_type.items()
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_and_verify_manifest(path: Path) -> tuple[dict[str, Any], dict[str, Path], dict[str, str]]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    benchmark = manifest.get("benchmark") or {}
    if manifest.get("status") != "CONFIGURED":
        raise BenchmarkConfigurationError(
            "Manifest status must be CONFIGURED. Do not run against placeholder assets."
        )
    if benchmark.get("sample_id") != "HG001":
        raise BenchmarkConfigurationError("This protocol currently expects GIAB sample HG001.")
    if benchmark.get("reference_build") != "GRCh38":
        raise BenchmarkConfigurationError("This protocol currently expects reference build GRCh38.")
    if benchmark.get("release") != "NISTv4.2.1":
        raise BenchmarkConfigurationError("The declared benchmark release must be NISTv4.2.1.")
    for name in ("truth_sample_name", "query_sample_name"):
        if not isinstance(benchmark.get(name), str) or not benchmark[name].strip():
            raise BenchmarkConfigurationError(
                f"benchmark.{name} must explicitly identify the VCF sample column to compare."
            )
    policy = manifest.get("acceptance_policy") or {}
    if not policy.get("id") or not policy.get("approved_by") or not policy.get("criteria"):
        raise BenchmarkConfigurationError(
            "An approved acceptance_policy id, approver, and criteria must be declared before execution."
        )
    toolchain = manifest.get("toolchain") or {}
    for name in ("bcftools_version", "hap_py_version"):
        if not isinstance(toolchain.get(name), str) or not toolchain[name].strip():
            raise BenchmarkConfigurationError(
                f"A verified toolchain.{name} pin is required before benchmark execution."
            )

    paths: dict[str, Path] = {}
    observed_hashes: dict[str, str] = {}
    for name in REQUIRED_ASSETS:
        asset = (manifest.get("assets") or {}).get(name) or {}
        raw_path = asset.get("path")
        expected_hash = asset.get("sha256")
        if not raw_path or not expected_hash:
            raise BenchmarkConfigurationError(
                f"Asset {name!r} requires an explicit local path and expected SHA-256."
            )
        asset_path = Path(raw_path).expanduser().resolve()
        if not asset_path.is_file():
            raise BenchmarkConfigurationError(f"Asset {name!r} is not a file: {asset_path}")
        observed = sha256_file(asset_path)
        if observed.lower() != str(expected_hash).lower():
            raise BenchmarkConfigurationError(
                f"SHA-256 mismatch for {name}: expected {expected_hash}, observed {observed}"
            )
        paths[name] = asset_path
        observed_hashes[name] = observed
    if paths["reference_fai"] != Path(str(paths["reference_fasta"]) + ".fai"):
        raise BenchmarkConfigurationError(
            "reference_fai must be the adjacent FASTA index at <reference_fasta>.fai used by BCFtools."
        )
    return manifest, paths, observed_hashes


def run_command(command: list[str], *, help_mode: bool = False) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0 and not help_mode:
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-8000:]}"
        )
    return {
        "command": command,
        "exit_code": completed.returncode,
        "output": completed.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--hap-py", default="hap.py")
    parser.add_argument("--bcftools", default="bcftools")
    args = parser.parse_args()

    started = datetime.now(timezone.utc)
    try:
        manifest_path = args.manifest.expanduser().resolve()
        manifest, assets, hashes = load_and_verify_manifest(manifest_path)
        hap_py = shutil.which(args.hap_py)
        bcftools = shutil.which(args.bcftools)
        if not hap_py:
            raise BenchmarkConfigurationError(f"hap.py executable not found: {args.hap_py}")
        if not bcftools:
            raise BenchmarkConfigurationError(f"bcftools executable not found: {args.bcftools}")

        output_dir = args.output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        prefix = output_dir / "hg001_grch38"
        bcftools_version = run_command([bcftools, "--version"])
        hap_py_version = run_command([hap_py, "--version"])
        expected_bcftools = (manifest.get("toolchain") or {}).get("bcftools_version")
        verify_version_pin("bcftools", expected_bcftools, bcftools_version)
        expected_hap_py = (manifest.get("toolchain") or {}).get("hap_py_version")
        verify_version_pin("hap.py", expected_hap_py, hap_py_version)

        normalization_lineage = verify_normalization_derivation(
            input_vcf=assets["input_vcf"],
            normalized_vcf=assets["siraloom_normalized_vcf"],
            reference_fasta=assets["reference_fasta"],
            bcftools=bcftools,
            expected_version=expected_bcftools,
        )
        truth_selection = select_benchmark_sample(
            vcf=assets["truth_vcf"],
            sample_name=manifest["benchmark"]["truth_sample_name"],
            bcftools=bcftools,
            output_path=output_dir / "hg001_grch38.truth-selected.vcf",
        )
        query_selection = select_benchmark_sample(
            vcf=assets["siraloom_normalized_vcf"],
            sample_name=manifest["benchmark"]["query_sample_name"],
            bcftools=bcftools,
            output_path=output_dir / "hg001_grch38.query-selected.vcf",
        )

        comparison = run_command([
            hap_py,
            truth_selection["selected_vcf"],
            query_selection["selected_vcf"],
            "-f", str(assets["confident_regions_bed"]),
            "-r", str(assets["reference_fasta"]),
            "-o", str(prefix),
            "--engine=vcfeval",
        ])
        summary_csv = Path(f"{prefix}.summary.csv")
        if not summary_csv.is_file():
            raise RuntimeError(
                f"hap.py completed but expected summary output was not found: {summary_csv}"
            )
        observed_metrics = parse_happy_summary(summary_csv)
        finished = datetime.now(timezone.utc)
        report = {
            "status": "RUN_COMPLETE_REVIEW_REQUIRED",
            "benchmark": manifest["benchmark"],
            "acceptance_policy": manifest["acceptance_policy"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "asset_sha256": hashes,
            "normalization_lineage": normalization_lineage,
            "sample_selection": {"truth": truth_selection, "query": query_selection},
            "toolchain": {
                "bcftools_executable": bcftools,
                "bcftools_version_output": bcftools_version["output"],
                "hap_py_executable": hap_py,
                "hap_py_version_command": hap_py_version,
            },
            "comparison": {
                "engine": "hap.py / vcfeval",
                "truth_vcf": str(assets["truth_vcf"]),
                "query_vcf": str(assets["siraloom_normalized_vcf"]),
                "confident_regions_bed": str(assets["confident_regions_bed"]),
                "reference_fasta": str(assets["reference_fasta"]),
                "summary_csv": str(summary_csv),
                "observed_metrics": observed_metrics,
                "command": comparison["command"],
                "exit_code": comparison["exit_code"],
            },
            "input_vcf_sha256": hashes["input_vcf"],
            "normalized_vcf_sha256": hashes["siraloom_normalized_vcf"],
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "scientific_interpretation": (
                "Raw benchmark outputs only. This runner does not infer acceptance, "
                "clinical validity, annotation accuracy, evidence correctness, or ACMG/ClinGen concordance."
            ),
        }
        report_path = output_dir / "benchmark-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "report": str(report_path), "summary_csv": str(summary_csv)}, indent=2))
        return 0
    except (BenchmarkConfigurationError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"BENCHMARK NOT ACCEPTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
