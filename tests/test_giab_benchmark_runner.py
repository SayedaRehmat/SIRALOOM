import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "run_giab_benchmark.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_giab_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _configured_manifest(tmp_path: Path) -> Path:
    module = _load_runner()
    assets = {}
    for name in module.REQUIRED_ASSETS:
        asset = tmp_path / f"{name}.dat"
        asset.write_text(f"fixture:{name}\n", encoding="utf-8")
        assets[name] = {"path": str(asset), "sha256": _sha256(asset)}

    manifest = {
        "status": "CONFIGURED",
        "benchmark": {
            "name": "Genome in a Bottle HG001 small-variant benchmark",
            "sample_id": "HG001",
            "release": "NISTv4.2.1",
            "reference_build": "GRCh38",
        },
        "assets": assets,
        "toolchain": {
            "bcftools_version": "1.19",
            "hap_py_version": "0.3.15",
        },
        "acceptance_policy": {
            "id": "LAB-SNV-BENCHMARK-001",
            "approved_by": "Laboratory Quality Manager",
            "criteria": {"requires_discrepancy_review": True},
        },
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_giab_runner_refuses_placeholder_manifest(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(ROOT / "benchmarks" / "giab" / "hg001_grch38.manifest.example.json"),
            "--output-dir",
            str(tmp_path / "benchmark-output"),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "Manifest status must be CONFIGURED" in result.stderr
    assert not (tmp_path / "benchmark-output").exists()


def test_giab_runner_rejects_asset_hash_drift(tmp_path):
    module = _load_runner()
    asset = tmp_path / "truth.vcf"
    asset.write_text("truth-fixture\n", encoding="utf-8")
    manifest = {
        "status": "CONFIGURED",
        "benchmark": {
            "sample_id": "HG001",
            "release": "NISTv4.2.1",
            "reference_build": "GRCh38",
        },
        "assets": {
            name: {"path": str(asset), "sha256": "0" * 64}
            for name in module.REQUIRED_ASSETS
        },
        "toolchain": {"bcftools_version": "1.19", "hap_py_version": "0.3.15"},
        "acceptance_policy": {
            "id": "LAB-POLICY-001",
            "approved_by": "test-reviewer",
            "criteria": {"review_required": True},
        },
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match="SHA-256 mismatch for truth_vcf"):
        module.load_and_verify_manifest(manifest_path)


def test_configured_manifest_verifies_all_required_assets(tmp_path):
    module = _load_runner()
    path = _configured_manifest(tmp_path)

    manifest, paths, hashes = module.load_and_verify_manifest(path)

    assert manifest["status"] == "CONFIGURED"
    assert set(paths) == set(module.REQUIRED_ASSETS)
    assert set(hashes) == set(module.REQUIRED_ASSETS)
    for name in module.REQUIRED_ASSETS:
        assert hashes[name] == _sha256(paths[name])


def test_missing_approval_metadata_fails_closed(tmp_path):
    module = _load_runner()
    path = _configured_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["acceptance_policy"]["approved_by"] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match="acceptance_policy"):
        module.load_and_verify_manifest(path)


@pytest.mark.parametrize("tool_pin", ["bcftools_version", "hap_py_version"])
def test_toolchain_version_pins_are_required(tmp_path, tool_pin):
    module = _load_runner()
    path = _configured_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["toolchain"][tool_pin] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match=f"toolchain.{tool_pin} pin is required"):
        module.load_and_verify_manifest(path)


def test_tool_version_pin_requires_version_command_output_match():
    module = _load_runner()

    module.verify_version_pin("hap.py", "0.3.15", {"exit_code": 0, "output": "Hap.py v0.3.15\n"})
    with pytest.raises(module.BenchmarkConfigurationError, match="could not be confirmed"):
        module.verify_version_pin("hap.py", "0.3.15", {"exit_code": 0, "output": "usage: hap.py"})
    with pytest.raises(module.BenchmarkConfigurationError, match="could not be confirmed"):
        module.verify_version_pin("hap.py", "0.3.15", {"exit_code": 2, "output": "Hap.py v0.3.15"})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sample_id", "HG002", "expects GIAB sample HG001"),
        ("reference_build", "GRCh37", "expects reference build GRCh38"),
        ("release", "NISTv4.2.0", "release must be NISTv4.2.1"),
    ],
)
def test_wrong_benchmark_identity_fails_closed(tmp_path, field, value, message):
    module = _load_runner()
    path = _configured_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["benchmark"][field] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match=message):
        module.load_and_verify_manifest(path)


def test_happy_summary_reports_observed_snp_and_indel_metrics(tmp_path):
    module = _load_runner()
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.TP,QUERY.FP,QUERY.UNK,METRIC.Recall,METRIC.Precision,METRIC.F1_Score\n"
        "SNP,ALL,100,90,10,95,90,5,2,0.9,0.947368,0.923077\n"
        "INDEL,PASS,40,36,4,38,36,2,1,0.9,0.947368,0.923077\n",
        encoding="utf-8",
    )

    metrics = module.parse_happy_summary(summary)

    assert metrics["SNP"]["filter"] == "ALL"
    assert metrics["SNP"]["truth_fn"] == 10
    assert metrics["SNP"]["query_fp"] == 5
    assert metrics["SNP"]["recall"] == 0.9
    assert metrics["INDEL"]["filter"] == "PASS"
    assert metrics["INDEL"]["f1_score"] == pytest.approx(0.923077)


def test_happy_summary_prefers_pass_rows_when_both_are_present(tmp_path):
    module = _load_runner()
    summary = tmp_path / "summary.csv"
    header = "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.TP,QUERY.FP,QUERY.UNK,METRIC.Recall,METRIC.Precision,METRIC.F1_Score\n"
    summary.write_text(
        header
        + "SNP,ALL,100,90,10,95,90,5,2,0.9,0.947368,0.923077\n"
        + "SNP,PASS,80,78,2,79,78,1,0,0.975,0.987342,0.981132\n"
        + "INDEL,ALL,40,36,4,38,36,2,1,0.9,0.947368,0.923077\n",
        encoding="utf-8",
    )

    metrics = module.parse_happy_summary(summary)

    assert metrics["SNP"]["filter"] == "PASS"
    assert metrics["SNP"]["truth_total"] == 80


def test_happy_summary_rejects_missing_metric_rows_or_columns(tmp_path):
    module = _load_runner()
    summary = tmp_path / "summary.csv"
    summary.write_text("Type,Filter\nSNP,PASS\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required columns"):
        module.parse_happy_summary(summary)


def test_happy_summary_rejects_absent_indel_row(tmp_path):
    module = _load_runner()
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.TP,QUERY.FP,QUERY.UNK,METRIC.Recall,METRIC.Precision,METRIC.F1_Score\n"
        "SNP,PASS,100,90,10,95,90,5,2,0.9,0.947368,0.923077\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must contain SNP and INDEL"):
        module.parse_happy_summary(summary)


def test_happy_summary_rejects_nonfinite_or_out_of_range_metrics(tmp_path):
    module = _load_runner()
    summary = tmp_path / "summary.csv"
    summary.write_text(
        "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.TP,QUERY.FP,QUERY.UNK,METRIC.Recall,METRIC.Precision,METRIC.F1_Score\n"
        "SNP,PASS,100,90,10,95,90,5,2,Infinity,0.95,0.92\n"
        "INDEL,PASS,40,36,4,38,36,2,1,0.9,0.95,0.92\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="must be finite and between 0 and 1"):
        module.parse_happy_summary(summary)
