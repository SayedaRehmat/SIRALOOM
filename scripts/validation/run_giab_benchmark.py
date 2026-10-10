#!/usr/bin/env python3
"""Run a manifest-pinned GIAB small-variant comparison with hap.py/vcfeval.

This runner reports observed metrics and provenance. It deliberately does not
declare a scientific PASS: an approved, intended-use-specific acceptance policy
and discrepancy review are required before the result can be accepted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_ASSETS = (
    "truth_vcf",
    "confident_regions_bed",
    "reference_fasta",
    "input_vcf",
    "siraloom_normalized_vcf",
)


class BenchmarkConfigurationError(ValueError):
    pass


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
    policy = manifest.get("acceptance_policy") or {}
    if not policy.get("id") or not policy.get("approved_by") or not policy.get("criteria"):
        raise BenchmarkConfigurationError(
            "An approved acceptance_policy id, approver, and criteria must be declared before execution."
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
        hap_py_help = run_command([hap_py, "--help"], help_mode=True)
        expected_bcftools = (manifest.get("toolchain") or {}).get("bcftools_version")
        if expected_bcftools and expected_bcftools not in bcftools_version["output"]:
            raise BenchmarkConfigurationError(
                f"bcftools version does not match the manifest pin {expected_bcftools!r}."
            )
        expected_hap_py = (manifest.get("toolchain") or {}).get("hap_py_version")
        if expected_hap_py and expected_hap_py not in hap_py_help["output"]:
            raise BenchmarkConfigurationError(
                f"hap.py version could not be confirmed against the manifest pin {expected_hap_py!r}; "
                "record the verified container/package version in the manifest."
            )

        comparison = run_command([
            hap_py,
            str(assets["truth_vcf"]),
            str(assets["siraloom_normalized_vcf"]),
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
        finished = datetime.now(timezone.utc)
        report = {
            "status": "RUN_COMPLETE_REVIEW_REQUIRED",
            "benchmark": manifest["benchmark"],
            "acceptance_policy": manifest["acceptance_policy"],
            "manifest_path": str(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "asset_sha256": hashes,
            "toolchain": {
                "bcftools_executable": bcftools,
                "bcftools_version_output": bcftools_version["output"],
                "hap_py_executable": hap_py,
                "hap_py_help_excerpt": hap_py_help["output"][:4000],
            },
            "comparison": {
                "engine": "hap.py / vcfeval",
                "truth_vcf": str(assets["truth_vcf"]),
                "query_vcf": str(assets["siraloom_normalized_vcf"]),
                "confident_regions_bed": str(assets["confident_regions_bed"]),
                "reference_fasta": str(assets["reference_fasta"]),
                "summary_csv": str(summary_csv),
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
