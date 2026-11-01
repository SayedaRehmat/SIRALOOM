#!/usr/bin/env python3
"""Execute a predeclared VCF laboratory qualification matrix.

This runner orchestrates the existing production VCF scale benchmark for each
manifest cell. It does not invent acceptance limits and never declares a
clinical validation result. Every cell remains review-required until a
laboratory reviewer accepts the observed evidence against the preapproved
policy identified in the manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
RUN_STATUS = "RUN_COMPLETE_REVIEW_REQUIRED"


class MatrixConfigurationError(ValueError):
    """The qualification manifest is incomplete or unsafe to execute."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MatrixConfigurationError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def require_positive_number(mapping: dict[str, Any], key: str, context: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise MatrixConfigurationError(f"{context}.{key} must be a positive number")
    return float(value)


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixConfigurationError(f"Unable to read matrix manifest: {path}") from exc

    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise MatrixConfigurationError("schema_version must be '1'")
    if manifest.get("status") != "CONFIGURED":
        raise MatrixConfigurationError("status must be CONFIGURED; an example/unconfigured manifest must not run")

    policy = manifest.get("acceptance_policy")
    if not isinstance(policy, dict):
        raise MatrixConfigurationError("acceptance_policy is required")
    require_string(policy, "id", "acceptance_policy")
    require_string(policy, "approved_by", "acceptance_policy")
    require_string(policy, "effective_date", "acceptance_policy")
    criteria = policy.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise MatrixConfigurationError("acceptance_policy.criteria must contain predeclared criteria")
    criterion_ids: set[str] = set()
    for index, criterion in enumerate(criteria):
        if not isinstance(criterion, dict):
            raise MatrixConfigurationError(f"acceptance_policy.criteria[{index}] must be an object")
        criterion_id = require_string(criterion, "id", f"acceptance_policy.criteria[{index}]")
        if criterion_id in criterion_ids:
            raise MatrixConfigurationError(f"duplicate acceptance criterion id: {criterion_id}")
        criterion_ids.add(criterion_id)
        require_string(criterion, "metric", f"acceptance_policy.criteria[{index}]")
        threshold = criterion.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
            raise MatrixConfigurationError(f"acceptance_policy.criteria[{index}].threshold must be finite and numeric")
        operator = criterion.get("operator")
        if operator not in {"<=", "<", ">=", ">", "=="}:
            raise MatrixConfigurationError(f"acceptance_policy.criteria[{index}].operator is invalid")
        if "threshold" not in criterion or isinstance(criterion["threshold"], bool) or not isinstance(criterion["threshold"], (int, float)):
            raise MatrixConfigurationError(f"acceptance_policy.criteria[{index}].threshold must be numeric")

    matrix = manifest.get("matrix")
    if not isinstance(matrix, list) or not matrix:
        raise MatrixConfigurationError("matrix must contain at least one real laboratory workload cell")

    seen_ids: set[str] = set()
    for index, cell in enumerate(matrix):
        context = f"matrix[{index}]"
        if not isinstance(cell, dict):
            raise MatrixConfigurationError(f"{context} must be an object")
        cell_id = require_string(cell, "id", context)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", cell_id):
            raise MatrixConfigurationError(f"{context}.id must be a safe path component (1-64 letters, digits, dot, underscore or hyphen)")
        if cell_id in seen_ids:
            raise MatrixConfigurationError(f"duplicate matrix cell id: {cell_id}")
        seen_ids.add(cell_id)
        for key in ("assay", "caller", "caller_version", "reference_build", "vcf", "reference_fasta", "sample_name"):
            require_string(cell, key, context)
        if cell["assay"] not in {"WES", "WGS"}:
            raise MatrixConfigurationError(f"{context}.assay must be WES or WGS")
        if cell["reference_build"] not in {"GRCh37", "GRCh38"}:
            raise MatrixConfigurationError(f"{context}.reference_build must be GRCh37 or GRCh38")
        timeout = cell.get("timeout_seconds", 1800)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
            raise MatrixConfigurationError(f"{context}.timeout_seconds must be a positive integer")
        for key in ("vcf_sha256", "reference_fasta_sha256"):
            digest = require_string(cell, key, context).lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise MatrixConfigurationError(f"{context}.{key} must be a SHA-256 hex digest")
            cell[key] = digest
        # Verify actual bytes before any benchmark output is created. run_benchmark
        # repeats these checks immediately before execution to detect input drift.
        verify_asset(cell["vcf"], cell["vcf_sha256"], f"{cell_id} VCF")
        reference = verify_asset(
            cell["reference_fasta"],
            cell["reference_fasta_sha256"],
            f"{cell_id} reference FASTA",
        )
        reference_fai = Path(str(reference) + ".fai")
        if not reference_fai.is_file():
            raise MatrixConfigurationError(f"{cell_id} reference FASTA has no adjacent .fai: {reference_fai}")
    return manifest


def verify_asset(path_value: str, expected_sha256: str, label: str) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise MatrixConfigurationError(f"{label} is not a regular file: {path}")
    observed = sha256_file(path)
    if observed.lower() != expected_sha256.lower():
        raise MatrixConfigurationError(
            f"{label} SHA-256 mismatch: expected {expected_sha256}, observed {observed}"
        )
    return path


def run_benchmark(*, cell: dict[str, Any], output_dir: Path, script: Path) -> tuple[int, dict[str, Any]]:
    vcf = verify_asset(cell["vcf"], cell["vcf_sha256"], f"{cell['id']} VCF")
    reference = verify_asset(
        cell["reference_fasta"],
        cell["reference_fasta_sha256"],
        f"{cell['id']} reference FASTA",
    )
    reference_fai = Path(str(reference) + ".fai")
    if not reference_fai.is_file():
        raise MatrixConfigurationError(f"{cell['id']} reference FASTA has no adjacent .fai: {reference_fai}")

    env = os.environ.copy()
    env["SIRALOOM_BENCHMARK_SAMPLE_NAME"] = cell["sample_name"]
    command = [
        sys.executable,
        str(script),
        "--vcf", str(vcf),
        "--reference-fasta", str(reference),
        "--reference-build", cell["reference_build"],
        "--output-dir", str(output_dir),
        "--timeout-seconds", str(cell.get("timeout_seconds", 1800)),
    ]
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    report_path = output_dir / "vcf-scale-benchmark.json"
    failure_path = output_dir / "vcf-scale-benchmark.failure.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    elif failure_path.is_file():
        report = json.loads(failure_path.read_text(encoding="utf-8"))
    else:
        raise RuntimeError(
            f"Benchmark produced neither success nor failure evidence for {cell['id']}; "
            f"runner output: {completed.stdout[-4000:]}"
        )
    # The selected sample name must never enter retained matrix evidence.
    serialized = json.dumps(report, sort_keys=True)
    if cell["sample_name"] in serialized:
        raise RuntimeError(f"Sample identifier leaked into benchmark evidence for {cell['id']}")
    return completed.returncode, report


def get_metric(report: dict[str, Any], path: str) -> float:
    value: Any = report
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            raise KeyError(path)
        value = value[component]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"Metric {path} is not numeric")
    return float(value)


def evaluate_criteria(report: dict[str, Any], criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evaluated: list[dict[str, Any]] = []
    for criterion in criteria:
        result: dict[str, Any] = {
            "id": criterion["id"],
            "metric": criterion["metric"],
            "operator": criterion["operator"],
            "threshold": criterion["threshold"],
            "status": "NOT_EVALUABLE",
        }
        try:
            observed = get_metric(report, criterion["metric"])
        except (KeyError, TypeError):
            evaluated.append(result)
            continue
        threshold = float(criterion["threshold"])
        operator = criterion["operator"]
        passed = {
            "<=": observed <= threshold,
            "<": observed < threshold,
            ">=": observed >= threshold,
            ">": observed > threshold,
            "==": observed == threshold,
        }[operator]
        result.update({"observed": observed, "status": "OBSERVED_MEETS_CRITERION" if passed else "OBSERVED_OUTSIDE_CRITERION"})
        evaluated.append(result)
    return evaluated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--benchmark-script", type=Path, default=Path("scripts/validation/run_vcf_scale_benchmark.py"))
    args = parser.parse_args()

    started = datetime.now(UTC)
    try:
        manifest_path = args.manifest.expanduser().resolve()
        manifest = load_manifest(manifest_path)
        benchmark_script = args.benchmark_script.expanduser().resolve()
        if not benchmark_script.is_file():
            raise MatrixConfigurationError(f"Benchmark script not found: {benchmark_script}")

        output_dir = args.output_dir.expanduser().resolve()
        if output_dir.exists() and any(output_dir.iterdir()):
            raise MatrixConfigurationError(f"Output directory is not empty: {output_dir}")
        output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Existing empty directories are accepted, but evidence must not inherit
        # permissive permissions from a pre-created parent directory.
        os.chmod(output_dir, 0o700)

        policy = manifest["acceptance_policy"]
        cells: list[dict[str, Any]] = []
        for cell in manifest["matrix"]:
            cell_output = output_dir / cell["id"]
            cell_output.mkdir(mode=0o700)
            started_cell = datetime.now(UTC)
            try:
                return_code, report = run_benchmark(cell=cell, output_dir=cell_output, script=benchmark_script)
                criteria = evaluate_criteria(report, policy["criteria"])
                cells.append({
                    "id": cell["id"],
                    "assay": cell["assay"],
                    "caller": cell["caller"],
                    "caller_version": cell["caller_version"],
                    "reference_build": cell["reference_build"],
                    "input_sha256": cell["vcf_sha256"],
                    "reference_fasta_sha256": cell["reference_fasta_sha256"],
                    "benchmark_exit_code": return_code,
                    "benchmark_status": report.get("status"),
                    "criteria": criteria,
                    "cell_status": "REVIEW_REQUIRED",
                    "started_at_utc": started_cell.isoformat(),
                    "completed_at_utc": datetime.now(UTC).isoformat(),
                })
            except Exception as exc:  # noqa: BLE001 - retain only typed class, not sensitive message.
                cells.append({
                    "id": cell["id"],
                    "assay": cell["assay"],
                    "caller": cell["caller"],
                    "caller_version": cell["caller_version"],
                    "reference_build": cell["reference_build"],
                    "input_sha256": cell["vcf_sha256"],
                    "reference_fasta_sha256": cell["reference_fasta_sha256"],
                    "benchmark_exit_code": None,
                    "benchmark_status": "RUN_FAILED",
                    "criteria": [],
                    "cell_status": "REVIEW_REQUIRED_FAILURE",
                    "failure_exception_class": type(exc).__name__,
                    "started_at_utc": started_cell.isoformat(),
                    "completed_at_utc": datetime.now(UTC).isoformat(),
                })

        result = {
            "schema_version": SCHEMA_VERSION,
            "status": RUN_STATUS,
            "matrix_kind": "VCF_STAGE1_LABORATORY_QUALIFICATION",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "started_at_utc": started.isoformat(),
            "runtime": {
                "python_version": platform.python_version(),
                "platform": platform.platform(),
                "repository_commit": os.environ.get("GITHUB_SHA"),
            },
            "manifest": {
                "sha256": sha256_file(manifest_path),
                "acceptance_policy_id": policy["id"],
                "acceptance_policy_approved_by": policy["approved_by"],
                "acceptance_policy_effective_date": policy["effective_date"],
            },
            "cells": cells,
            "release_decision": "NOT_AUTOMATICALLY_QUALIFIED",
            "release_decision_reason": "Observed metrics are evidence for laboratory review; this runner never converts criteria evaluation into clinical validation or release authorization.",
        }
        (output_dir / "qualification-matrix.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary must return controlled failure.
        failure = {
            "schema_version": SCHEMA_VERSION,
            "status": "CONFIGURATION_OR_RUN_FAILED",
            "exception_class": type(exc).__name__,
            "generated_at_utc": datetime.now(UTC).isoformat(),
        }
        try:
            output_dir = args.output_dir.expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(output_dir, 0o700)
            (output_dir / "qualification-matrix.failure.json").write_text(
                json.dumps(failure, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass
        print(f"qualification matrix failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
