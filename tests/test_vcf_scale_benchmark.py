from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validation" / "run_vcf_scale_benchmark.py"


def _load_runner():
    spec = importlib.util.spec_from_file_location("run_vcf_scale_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    vcf = tmp_path / "case.vcf"
    vcf.write_text("deidentified VCF fixture\n", encoding="utf-8")
    reference = tmp_path / "GRCh38.fa"
    reference.write_text(">1\nAAAA\n", encoding="utf-8")
    Path(str(reference) + ".fai").write_text("1\t4\t4\t4\t5\n", encoding="utf-8")
    return vcf, reference


def test_deployment_resource_snapshot_captures_cgroup_v2_and_output_filesystem(tmp_path):
    module = _load_runner()
    cgroup = tmp_path / "cgroup"
    cgroup.mkdir()
    (cgroup / "memory.current").write_text("1048576\n", encoding="ascii")
    (cgroup / "memory.peak").write_text("2097152\n", encoding="ascii")
    (cgroup / "memory.max").write_text("4194304\n", encoding="ascii")
    output = tmp_path / "evidence"
    output.mkdir(mode=0o700)

    snapshot = module.deployment_resource_snapshot(output, cgroup_root=cgroup)

    assert snapshot["container_memory"] == {
        "cgroup_version": 2,
        "current_bytes": 1048576,
        "peak_bytes": 2097152,
        "limit_bytes": 4194304,
        "measurement_scope": "cgroup workload/container; not process-attributed",
    }
    filesystem = snapshot["output_filesystem"]
    assert filesystem["total_bytes"] > 0
    assert filesystem["free_bytes"] > 0
    assert filesystem["used_bytes"] >= 0
    assert filesystem["device_id"] == output.stat().st_dev
    assert filesystem["output_directory_mode"] == "0o700"


def test_deployment_resource_snapshot_supports_cgroup_v1_and_unavailable_metrics(tmp_path):
    module = _load_runner()
    cgroup = tmp_path / "cgroup"
    memory = cgroup / "memory"
    memory.mkdir(parents=True)
    (memory / "memory.usage_in_bytes").write_text("512\n", encoding="ascii")
    (memory / "memory.max_usage_in_bytes").write_text("1024\n", encoding="ascii")
    (memory / "memory.limit_in_bytes").write_text(str((1 << 63) - 4096) + "\n", encoding="ascii")
    output = tmp_path / "evidence"
    output.mkdir()

    snapshot = module.deployment_resource_snapshot(output, cgroup_root=cgroup)

    assert snapshot["container_memory"]["cgroup_version"] == 1
    assert snapshot["container_memory"]["current_bytes"] == 512
    assert snapshot["container_memory"]["peak_bytes"] == 1024
    assert snapshot["container_memory"]["limit_bytes"] is None

    (memory / "memory.limit_in_bytes").write_text("max\\n", encoding="ascii")
    unlimited_text = module.deployment_resource_snapshot(output, cgroup_root=cgroup)
    assert unlimited_text["container_memory"]["limit_bytes"] is None

    empty_cgroup = tmp_path / "no-cgroup"
    empty_cgroup.mkdir()
    unavailable = module.deployment_resource_snapshot(output, cgroup_root=empty_cgroup)
    assert unavailable["container_memory"]["cgroup_version"] is None
    assert unavailable["container_memory"]["current_bytes"] is None
    assert unavailable["container_memory"]["peak_bytes"] is None


def test_prepare_output_dir_preserves_existing_evidence(tmp_path):
    module = _load_runner()
    output = tmp_path / "existing"
    output.mkdir()
    evidence = output / "previous.json"
    evidence.write_text('{"preserve":true}\n', encoding="utf-8")

    with pytest.raises(module.ScaleBenchmarkError, match="must not already exist"):
        module.prepare_output_dir(output)

    assert evidence.read_text(encoding="utf-8") == '{"preserve":true}\n'


def test_prepare_output_dir_rejects_existing_empty_directory(tmp_path):
    module = _load_runner()
    output = tmp_path / "empty-existing"
    output.mkdir()

    with pytest.raises(module.ScaleBenchmarkError, match="must not already exist"):
        module.prepare_output_dir(output)


def test_prepare_output_dir_sets_private_permissions(tmp_path):
    module = _load_runner()
    output = module.prepare_output_dir(tmp_path / "benchmark")

    assert output.is_dir()
    assert output.stat().st_mode & 0o777 == 0o700


def test_benchmark_requires_an_explicit_sample_mapping(tmp_path, monkeypatch):
    module = _load_runner()
    vcf, reference = _inputs(tmp_path)
    monkeypatch.setattr(
        module,
        "validate_vcf",
        lambda _path: SimpleNamespace(
            status="VALID",
            sample_names=["SAMPLE_A"],
            detected_build=None,
            metadata={"toolchain_validation_status": "PASS"},
            record_count=1,
            fileformat="VCFv4.5",
        ),
    )

    with pytest.raises(module.ScaleBenchmarkError, match="selected sample is absent"):
        module.run_benchmark(
            vcf_path=vcf,
            reference_fasta=reference,
            reference_build="GRCh38",
            sample_name="SAMPLE_B",
            output_dir=tmp_path / "output",
        )

    failure = json.loads((tmp_path / "output" / module.FAILURE_NAME).read_text(encoding="utf-8"))
    assert failure["status"] == "FAILED"
    assert failure["failed_stage"] == "vcf_validation"
    assert "SAMPLE_B" not in json.dumps(failure)





def test_scale_benchmark_executes_real_pinned_vcf_pipeline(tmp_path):
    import shutil
    import subprocess

    from backend.app.config import settings

    executable = shutil.which("bcftools")
    if executable is None:
        pytest.skip("Pinned BCFtools is not installed in this test environment.")
    version = subprocess.run(
        [executable, "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    first_line = next((line for line in version.stdout.splitlines() if line.strip()), "")
    detected = first_line.split()[1] if len(first_line.split()) > 1 else None
    if version.returncode != 0 or detected != settings.bcftools_version:
        pytest.skip("The test environment does not provide the repository-pinned BCFtools version.")

    module = _load_runner()
    vcf = tmp_path / "one-sample.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.3\n"
        "##contig=<ID=1,length=7>\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t4\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )
    reference = tmp_path / "GRCh38.fa"
    reference.write_text(">1\nCAAAAAC\n", encoding="utf-8")
    Path(str(reference) + ".fai").write_text("1\t7\t3\t7\t8\n", encoding="utf-8")

    output = tmp_path / "real-run"
    report = module.run_benchmark(
        vcf_path=vcf,
        reference_fasta=reference,
        reference_build="GRCh38",
        sample_name="SAMPLE1",
        output_dir=output,
    )

    assert report["status"] == "RUN_COMPLETE_REVIEW_REQUIRED"
    assert report["validation"]["status"] == "VALID"
    assert report["validation"]["source_record_count"] == 1
    assert report["reference"]["validation"]["result"] == "PASS"
    assert report["routing"]["record_reconciliation"]["balanced"] is True
    assert report["normalization"]["source_child_reconciliation"]["status"] == "VALIDATED"
    assert report["normalization"]["index_validation"]["indexed_query_records_verified"] == 1
    assert report["normalization"]["selected_sample_normalized_record_count"] == 1
    assert (output / "normalized.vcf.gz").is_file()
    assert (output / "normalized.vcf.gz.csi").is_file()
    assert "SAMPLE1" not in json.dumps(report)


def test_benchmark_records_stage_metrics_without_recording_sample_identifier(tmp_path, monkeypatch):
    module = _load_runner()
    vcf, reference = _inputs(tmp_path)
    sample_name = "PRIVATE_SAMPLE_IDENTIFIER"
    monkeypatch.setattr(
        module,
        "validate_vcf",
        lambda _path: SimpleNamespace(
            status="VALID",
            sample_names=[sample_name],
            detected_build="GRCh38",
            metadata={
                "source_record_count": 3,
                "alternate_allele_count": 3,
                "base_modification_format_fields": [],
                "bcftools_version": "1.25",
                "htslib_version": "1.25",
                "toolchain_validation_status": "PASS",
            },
            record_count=3,
            fileformat="VCFv4.5",
        ),
    )
    monkeypatch.setattr(
        module,
        "validate_vcf_reference_alleles",
        lambda *_args: {
            "checked_record_count": 3,
            "checked_breakend_mate_count": 0,
            "unvalidated_telomere_record_count": 0,
            "result": "PASS",
        },
    )

    def fake_route(_source, output_dir):
        output_dir.mkdir(parents=True)
        sequence = output_dir / "sequence-input.vcf"
        sequence.write_text("routed sequence records\n", encoding="utf-8")
        return {
            "routing_version": "3",
            "source_record_count": 3,
            "records_total": 3,
            "record_reconciliation": {"balanced": True, "delta": 0},
            "sequence_records": 2,
            "gvcf_reference_blocks": 1,
            "gvcf_unresolved_variant_records": 0,
            "structural_variant_records": 0,
            "cnv_variant_records": 0,
            "repeat_expansion_records": 0,
            "mitochondrial_variant_records": 0,
            "spanning_deletion_records": 0,
            "telomere_records": 0,
            "telomere_after_contig_records": 0,
            "reference_only_records": 0,
            "sequence_path": str(sequence),
        }

    def fake_normalize(_source, output_path, **_kwargs):
        output_path.write_bytes(b"normalized BGZF placeholder for isolated harness test")
        Path(str(output_path) + ".csi").write_bytes(b"CSI")
        return {
            "tool": "bcftools",
            "tool_version": "bcftools 1.25",
            "operation": "reference_aware_normalization_sort_index",
            "compression": "BGZF",
            "index": "CSI",
            "index_validation": {
                "records": 2,
                "contigs": 1,
                "indexed_query_records_verified": 2,
                "indexed_query_contigs_verified": 1,
            },
            "source_child_reconciliation": {
                "status": "VALIDATED",
                "balanced": True,
                "normalized_child_records": 2,
            },
            "source_only_format_fields": [],
            "source_only_format_fields_policy": None,
        }

    consumed = {"count": 0}

    def fake_iter(_path, _build, *, sample_name):
        assert sample_name == sample_name_expected
        for _ in range(2):
            consumed["count"] += 1
            yield object()

    sample_name_expected = sample_name
    monkeypatch.setattr(module, "route_vcf_records", fake_route)
    monkeypatch.setattr(module, "normalize_vcf_with_bcftools", fake_normalize)
    monkeypatch.setattr(module, "iter_normalized_vcf", fake_iter)

    output = tmp_path / "output"
    report = module.run_benchmark(
        vcf_path=vcf,
        reference_fasta=reference,
        reference_build="GRCh38",
        sample_name=sample_name,
        output_dir=output,
    )

    serialized = json.dumps(report)
    assert report["status"] == "RUN_COMPLETE_REVIEW_REQUIRED"
    assert report["input"]["integrity_verified_across_run"] is True
    assert report["reference"]["integrity_verified_across_run"] is True
    assert report["routing"]["record_reconciliation"]["balanced"] is True
    assert report["normalization"]["selected_sample_normalized_record_count"] == 2
    assert consumed["count"] == 2
    assert "selected_sample_iteration" in report["runtime"]["stages"]
    iteration_metrics = report["runtime"]["stages"]["selected_sample_iteration"]
    assert iteration_metrics["wall_seconds"] >= 0
    assert iteration_metrics["python_process_cpu_seconds"] >= 0
    assert iteration_metrics["throughput_record_basis"] == "selected_sample_normalized_records"
    assert iteration_metrics["throughput_record_count"] == 2
    assert "records_per_second" in iteration_metrics
    assert "child_process_cpu_seconds" in iteration_metrics
    assert "largest_child_peak_rss_mb_after_stage" in iteration_metrics
    assert sample_name not in serialized
    assert (output / module.REPORT_NAME).is_file()
    assert (output / "normalized.vcf.gz.csi").is_file()
