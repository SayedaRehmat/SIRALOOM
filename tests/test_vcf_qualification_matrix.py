from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.validation.run_vcf_qualification_matrix import (
    MatrixConfigurationError,
    evaluate_criteria,
    load_manifest,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configured_manifest(tmp_path: Path) -> Path:
    vcf = tmp_path / "input.vcf.gz"
    reference = tmp_path / "GRCh38.fa"
    fai = tmp_path / "GRCh38.fa.fai"
    for path, content in (
        (vcf, b"vcf"),
        (reference, b"reference"),
        (fai, b"index"),
    ):
        path.write_bytes(content)

    manifest = {
        "schema_version": "1",
        "status": "CONFIGURED",
        "acceptance_policy": {
            "id": "POLICY-001",
            "approved_by": "laboratory-quality",
            "effective_date": "2026-11-01",
            "criteria": [
                {
                    "id": "MAX_WALL",
                    "metric": "runtime.stages.vcf_validation.wall_seconds",
                    "operator": "<=",
                    "threshold": 60,
                }
            ],
        },
        "matrix": [
            {
                "id": "WES_CALLER_GRCH38",
                "assay": "WES",
                "caller": "approved-caller",
                "caller_version": "1.2.3",
                "reference_build": "GRCh38",
                "vcf": str(vcf),
                "vcf_sha256": _sha256(vcf),
                "reference_fasta": str(reference),
                "reference_fasta_sha256": _sha256(reference),
                "sample_name": "specimen-1",
            }
        ],
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_load_manifest_requires_configured_status(tmp_path: Path) -> None:
    path = _configured_manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["status"] = "UNCONFIGURED"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(MatrixConfigurationError, match="CONFIGURED"):
        load_manifest(path)


def test_load_manifest_requires_real_asset_hashes(tmp_path: Path) -> None:
    path = _configured_manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["matrix"][0]["vcf_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(MatrixConfigurationError):
        load_manifest(path)


def test_load_manifest_accepts_strict_configured_cell(tmp_path: Path) -> None:
    path = _configured_manifest(tmp_path)
    manifest = load_manifest(path)
    assert manifest["matrix"][0]["assay"] == "WES"
    assert manifest["matrix"][0]["reference_build"] == "GRCh38"


def test_evaluate_criteria_preserves_review_boundary() -> None:
    report = {
        "runtime": {"stages": {"vcf_validation": {"wall_seconds": 12.5}}}
    }
    criteria = [
        {
            "id": "MAX_WALL",
            "metric": "runtime.stages.vcf_validation.wall_seconds",
            "operator": "<=",
            "threshold": 60,
        },
        {
            "id": "MISSING_METRIC",
            "metric": "runtime.stages.not_present.wall_seconds",
            "operator": "<=",
            "threshold": 60,
        },
    ]

    evaluated = evaluate_criteria(report, criteria)
    assert evaluated[0]["status"] == "OBSERVED_MEETS_CRITERION"
    assert evaluated[0]["observed"] == pytest.approx(12.5)
    assert evaluated[1]["status"] == "NOT_EVALUABLE"


def test_evaluate_criteria_marks_observed_failure_without_relabeling_run() -> None:
    report = {"runtime": {"stages": {"vcf_validation": {"wall_seconds": 75}}}}
    criteria = [
        {
            "id": "MAX_WALL",
            "metric": "runtime.stages.vcf_validation.wall_seconds",
            "operator": "<=",
            "threshold": 60,
        }
    ]

    evaluated = evaluate_criteria(report, criteria)
    assert evaluated[0]["status"] == "OBSERVED_OUTSIDE_CRITERION"
