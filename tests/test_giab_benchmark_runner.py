import hashlib
import importlib.util
import json
import shutil
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
        if name == "reference_fai":
            asset = Path(str(assets["reference_fasta"]["path"]) + ".fai")
        else:
            asset = tmp_path / f"{name}.dat"
        asset.write_text(f"fixture:{name}\n", encoding="utf-8")
        assets[name] = {"path": str(asset), "sha256": _sha256(asset)}

    manifest = {
        "status": "CONFIGURED",
        "benchmark": {
            "name": "Genome in a Bottle HG001 small-variant benchmark",
            "sample_id": "HG001",
            "truth_sample_name": "HG001",
            "query_sample_name": "S1",
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
            "truth_sample_name": "HG001",
            "query_sample_name": "SAMPLE",
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
    module.verify_version_pin("bcftools", "1.19", {"exit_code": 0, "output": "bcftools 1.19\nUsing htslib 1.19\n"})
    with pytest.raises(module.BenchmarkConfigurationError, match="could not be confirmed"):
        module.verify_version_pin("hap.py", "0.3.15", {"exit_code": 0, "output": "usage: hap.py"})
    with pytest.raises(module.BenchmarkConfigurationError, match="could not be confirmed"):
        module.verify_version_pin("hap.py", "0.3.15", {"exit_code": 0, "output": "Hap.py v0.3.150"})
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


@pytest.mark.parametrize("sample_field", ["truth_sample_name", "query_sample_name"])
def test_benchmark_sample_columns_must_be_explicit(tmp_path, sample_field):
    module = _load_runner()
    path = _configured_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["benchmark"][sample_field] = None
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match=sample_field):
        module.load_and_verify_manifest(path)


def test_sample_selection_publishes_verified_output_atomically(tmp_path, monkeypatch):
    module = _load_runner()
    source = tmp_path / "input.vcf"
    source.write_text("input\n", encoding="utf-8")
    destination = tmp_path / "selected.vcf"
    destination.write_text("previous verified artifact\n", encoding="utf-8")

    def fake_run(command, *, help_mode=False):
        if command[1:3] == ["query", "-l"] and command[-1] == str(source):
            return {"command": command, "exit_code": 0, "output": "S1\nS2\n"}
        if command[1] == "view":
            Path(command[command.index("-o") + 1]).write_text("selected S2\n", encoding="utf-8")
            return {"command": command, "exit_code": 0, "output": ""}
        if command[1:3] == ["query", "-l"]:
            return {"command": command, "exit_code": 0, "output": "S2\n"}
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(module, "run_command", fake_run)
    selected = module.select_benchmark_sample(
        vcf=source, sample_name="S2", bcftools="bcftools", output_path=destination
    )

    assert destination.read_text(encoding="utf-8") == "selected S2\n"
    assert selected["selected_vcf_sha256"] == _sha256(destination)
    assert selected["publication"] == "validated_staged_file_atomically_replaced_destination"


def test_sample_selection_failure_preserves_previous_output(tmp_path, monkeypatch):
    module = _load_runner()
    source = tmp_path / "input.vcf"
    source.write_text("input\n", encoding="utf-8")
    destination = tmp_path / "selected.vcf"
    destination.write_text("preserve me\n", encoding="utf-8")

    def fake_run(command, *, help_mode=False):
        if command[1:3] == ["query", "-l"] and command[-1] == str(source):
            return {"command": command, "exit_code": 0, "output": "S1\nS2\n"}
        if command[1] == "view":
            Path(command[command.index("-o") + 1]).write_text("partial output\n", encoding="utf-8")
            return {"command": command, "exit_code": 0, "output": ""}
        if command[1:3] == ["query", "-l"]:
            return {"command": command, "exit_code": 0, "output": "S1\nS2\n"}
        raise AssertionError(f"unexpected command: {command}")

    monkeypatch.setattr(module, "run_command", fake_run)
    with pytest.raises(RuntimeError, match="expected only 'S2'"):
        module.select_benchmark_sample(
            vcf=source, sample_name="S2", bcftools="bcftools", output_path=destination
        )

    assert destination.read_text(encoding="utf-8") == "preserve me\n"


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


def test_manifest_requires_the_fasta_index_used_by_bcftools(tmp_path):
    module = _load_runner()
    path = _configured_manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    other_index = tmp_path / "other.fai"
    other_index.write_text("index\n", encoding="utf-8")
    manifest["assets"]["reference_fai"] = {"path": str(other_index), "sha256": _sha256(other_index)}
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(module.BenchmarkConfigurationError, match="adjacent FASTA index"):
        module.load_and_verify_manifest(path)


@pytest.mark.skipif(shutil.which("bcftools") is None, reason="pinned bcftools required for derivation integration")
def test_benchmark_lineage_reproduces_production_normalized_records(tmp_path):
    from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records

    module = _load_runner()
    reference = tmp_path / "ref.fa"
    reference.write_text(">1\nCAAAAAC\n", encoding="utf-8")
    (tmp_path / "ref.fa.fai").write_text("1\t7\t3\t7\t8\n", encoding="utf-8")
    source = tmp_path / "input.vcf"
    source.write_text(
        "##fileformat=VCFv4.3\n##contig=<ID=1,length=7>\n"
        '##ALT=<ID=NON_REF,Description="Any possible alternate allele">\n'
        '##INFO=<ID=END,Number=1,Type=Integer,Description="End position">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t1\t.\tC\t<NON_REF>\t.\tPASS\tEND=3\tGT\t0/0\n"
        "1\t2\trsMix\tA\tG,<NON_REF>\t50\tPASS\t.\tGT\t0/1\n"
        "1\t4\t.\tAA\tA\t.\tPASS\t.\tGT\t0/1\n"
        "1\t5\t.\tA\t<DEL>\t.\tPASS\tEND=6\tGT\t0/1\n"
        "1\t6\t.\tA\tA]1:7]\t.\tPASS\tSVTYPE=BND\tGT\t0/1\n",
        encoding="utf-8",
    )
    production_routing = route_vcf_records(source, tmp_path / "production-routed")
    assert production_routing["sequence_records"] == 2
    assert production_routing["gvcf_reference_blocks"] == 1
    assert production_routing["structural_variant_records"] == 2
    normalized = tmp_path / "normalized.vcf.gz"
    normalize_vcf_with_bcftools(
        production_routing["sequence_path"], normalized, reference_fasta=reference,
        expected_bcftools_version="1.19",
    )

    lineage = module.verify_normalization_derivation(
        input_vcf=source,
        normalized_vcf=normalized,
        reference_fasta=reference,
        bcftools=shutil.which("bcftools"),
        expected_version="1.19",
    )

    assert lineage["status"] == "REPRODUCED_RECORDS_MATCH"
    assert lineage["record_count"] == 2
    assert len(lineage["ordered_record_sha256"]) == 64
    assert lineage["input_routing"] == {
        "routing_version": "1",
        "records_total": 5,
        "sequence_records": 2,
        "gvcf_reference_blocks": 1,
        "gvcf_unresolved_variant_records": 0,
        "structural_variant_records": 2,
        "spanning_deletion_records": 0,
        "policy": "BCFTOOLS_VIEW_TRIM_UNSEEN_AT_VARIANT_SITES",
    }
    selection = module.select_benchmark_sample(
        vcf=normalized,
        sample_name="S1",
        bcftools=shutil.which("bcftools"),
        output_path=tmp_path / "selected.vcf",
    )
    assert selection["sample_name"] == "S1"
    assert selection["available_samples"] == ["S1"]
    assert selection["selected_vcf_sha256"] == _sha256(tmp_path / "selected.vcf")
    with pytest.raises(module.BenchmarkConfigurationError, match="absent"):
        module.select_benchmark_sample(
            vcf=normalized,
            sample_name="WRONG_SAMPLE",
            bcftools=shutil.which("bcftools"),
            output_path=tmp_path / "wrong-sample.vcf",
        )

    tampered = tmp_path / "unrelated.vcf"
    tampered.write_text(
        "##fileformat=VCFv4.3\n##contig=<ID=1,length=7>\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1\n"
        "1\t2\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    with pytest.raises(module.BenchmarkConfigurationError, match="do not match the pinned BCFtools"):
        module.verify_normalization_derivation(
            input_vcf=source,
            normalized_vcf=tampered,
            reference_fasta=reference,
            bcftools=shutil.which("bcftools"),
            expected_version="1.19",
        )
