import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_giab_runner_refuses_placeholder_manifest(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validation" / "run_giab_benchmark.py"),
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
    # Import the script as a module so the manifest verifier can be tested
    # without invoking external benchmarking tools or downloading reference data.
    import importlib.util

    script = ROOT / "scripts" / "validation" / "run_giab_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_giab_benchmark", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

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

    try:
        module.load_and_verify_manifest(manifest_path)
    except module.BenchmarkConfigurationError as exc:
        assert "SHA-256 mismatch for truth_vcf" in str(exc)
    else:
        raise AssertionError("Hash drift must fail closed")
