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
            "bcftools_version": "bcftools 1.19",
            "hap_py_version": "hap.py 0.3.15",
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
