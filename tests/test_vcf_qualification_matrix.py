from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from scripts.validation import run_vcf_qualification_matrix as matrix_runner
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


def test_load_manifest_rejects_path_traversal_cell_id(tmp_path: Path) -> None:
    path = _configured_manifest(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["matrix"][0]["id"] = "../outside"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(MatrixConfigurationError, match="safe path component"):
        load_manifest(path)


def test_load_manifest_requires_adjacent_reference_fai(tmp_path: Path) -> None:
    path = _configured_manifest(tmp_path)
    fai = tmp_path / "GRCh38.fa.fai"
    fai.unlink()

    with pytest.raises(MatrixConfigurationError, match="adjacent .fai"):
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


@pytest.mark.parametrize("observed", [float("nan"), float("inf"), float("-inf")])
def test_evaluate_criteria_rejects_non_finite_observed_metrics(observed: float) -> None:
    report = {"runtime": {"stages": {"vcf_validation": {"wall_seconds": observed}}}}
    criteria = [
        {
            "id": "MAX_WALL",
            "metric": "runtime.stages.vcf_validation.wall_seconds",
            "operator": "<=",
            "threshold": 60,
        }
    ]

    with pytest.raises(ValueError, match="not finite"):
        evaluate_criteria(report, criteria)


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



def test_matrix_runner_marks_failed_benchmark_cell_and_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _configured_manifest(tmp_path)
    benchmark_script = tmp_path / "run_vcf_scale_benchmark.py"
    benchmark_script.write_text("# controlled test executable\\n", encoding="utf-8")
    output_dir = tmp_path / "matrix-failed-output"

    def fake_failed_benchmark(*, cell: dict, output_dir: Path, script: Path):
        output_dir.mkdir(mode=0o700)
        return 2, {"status": "FAILED", "failed_stage": "reference_validation"}

    monkeypatch.setattr(matrix_runner, "run_benchmark", fake_failed_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_vcf_qualification_matrix.py",
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--benchmark-script",
            str(benchmark_script),
        ],
    )

    assert matrix_runner.main() == 1
    result = json.loads((output_dir / "qualification-matrix.json").read_text(encoding="utf-8"))
    assert result["cells"][0]["benchmark_exit_code"] == 2
    assert result["cells"][0]["benchmark_status"] == "FAILED"
    assert result["cells"][0]["failure_stage"] == "reference_validation"
    assert result["cells"][0]["cell_status"] == "REVIEW_REQUIRED_FAILURE"
    assert result["cells"][0]["criteria"][0]["status"] == "NOT_EVALUABLE"
    assert result["release_decision"] == "NOT_AUTOMATICALLY_QUALIFIED"


def test_matrix_runner_leaves_cell_output_path_for_atomic_benchmark_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = _configured_manifest(tmp_path)
    benchmark_script = tmp_path / "run_vcf_scale_benchmark.py"
    benchmark_script.write_text("# controlled test executable\n", encoding="utf-8")
    output_dir = tmp_path / "matrix-output"

    def fake_run_benchmark(*, cell: dict, output_dir: Path, script: Path):
        # The production scale benchmark requires a non-existent destination and
        # owns its atomic directory reservation.
        assert not output_dir.exists()
        output_dir.mkdir(mode=0o700)
        return 0, {
            "status": "RUN_COMPLETE_REVIEW_REQUIRED",
            "runtime": {"stages": {"vcf_validation": {"wall_seconds": 2.0}}},
        }

    monkeypatch.setattr(matrix_runner, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_vcf_qualification_matrix.py",
            "--manifest",
            str(manifest_path),
            "--output-dir",
            str(output_dir),
            "--benchmark-script",
            str(benchmark_script),
        ],
    )

    assert matrix_runner.main() == 0
    result = json.loads((output_dir / "qualification-matrix.json").read_text(encoding="utf-8"))
    assert result["cells"][0]["benchmark_status"] == "RUN_COMPLETE_REVIEW_REQUIRED"
    assert result["cells"][0]["criteria"][0]["status"] == "OBSERVED_MEETS_CRITERION"
    assert (output_dir / "WES_CALLER_GRCH38").is_dir()
