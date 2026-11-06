#!/usr/bin/env python3
"""Measure the production VCF intake/normalization path on a lab-supplied VCF.

This is an operational scale-qualification harness, not a clinical validation
or acceptance test. It records reproducible counts, hashes, timings and process
peak RSS without recording sample identifiers or raw VCF content.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import platform
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

try:
    import resource
except ImportError:  # pragma: no cover - Windows is not the target runtime.
    resource = None  # type: ignore[assignment]

from backend.app.config import settings
from backend.app.domain.ingestion import validate_vcf
from backend.app.domain.normalization import iter_normalized_vcf
from backend.app.domain.vcf_tools import normalize_vcf_with_bcftools, route_vcf_records
from backend.app.domain.vcf_validation import validate_vcf_reference_alleles

REPORT_NAME = "vcf-scale-benchmark.json"
FAILURE_NAME = "vcf-scale-benchmark.failure.json"


class ScaleBenchmarkError(RuntimeError):
    """The input or execution did not satisfy the benchmark contract."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reference_artifact_snapshot(reference_fasta: Path, reference_fai: Path) -> dict[str, dict[str, Any]]:
    artifacts = {
        "fasta": reference_fasta,
        "fai": reference_fai,
    }
    gzi = Path(str(reference_fasta) + ".gzi")
    if gzi.is_file():
        artifacts["gzi"] = gzi
    return {
        name: {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for name, path in artifacts.items()
    }


def _rss_to_mb(value: float) -> float:
    # Linux reports KiB; macOS reports bytes. This harness is intended for Linux.
    return round(value / (1024 * 1024), 2) if sys.platform == "darwin" else round(value / 1024, 2)


def python_peak_rss_mb() -> float | None:
    if resource is None:
        return None
    return _rss_to_mb(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def largest_child_peak_rss_mb() -> float | None:
    if resource is None:
        return None
    return _rss_to_mb(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)


CGROUP_V1_UNLIMITED_MEMORY_LIMIT = (1 << 63) - 4096


def _read_cgroup_integer(
    path: Path, *, unlimited_sentinel: int | None = None
) -> int | None:
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError):
        return None
    if value in {"", "max"}:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed < 0 or (unlimited_sentinel is not None and parsed == unlimited_sentinel):
        return None
    return parsed


def deployment_resource_snapshot(
    output_dir: Path,
    *,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
) -> dict[str, Any]:
    """Capture container-level memory and output-filesystem capacity evidence.

    cgroup peak is a container/workload-group measurement, not an attribution
    to this Python process. Missing cgroup interfaces remain null rather than
    being inferred from process RSS.
    """
    v2_current = cgroup_root / "memory.current"
    v2_peak = cgroup_root / "memory.peak"
    v2_limit = cgroup_root / "memory.max"
    v1_root = cgroup_root / "memory"
    if any(path.is_file() for path in (v2_current, v2_peak, v2_limit)):
        memory = {
            "cgroup_version": 2,
            "current_bytes": _read_cgroup_integer(v2_current),
            "peak_bytes": _read_cgroup_integer(v2_peak),
            "limit_bytes": _read_cgroup_integer(v2_limit),
        }
    else:
        memory = {
            "cgroup_version": 1 if any(
                (v1_root / name).is_file()
                for name in ("memory.usage_in_bytes", "memory.max_usage_in_bytes", "memory.limit_in_bytes")
            ) else None,
            "current_bytes": _read_cgroup_integer(v1_root / "memory.usage_in_bytes"),
            "peak_bytes": _read_cgroup_integer(v1_root / "memory.max_usage_in_bytes"),
            "limit_bytes": _read_cgroup_integer(
                v1_root / "memory.limit_in_bytes",
                unlimited_sentinel=CGROUP_V1_UNLIMITED_MEMORY_LIMIT,
            ),
        }
    usage = shutil.disk_usage(output_dir)
    return {
        "container_memory": {
            **memory,
            "measurement_scope": "cgroup workload/container; not process-attributed",
        },
        "output_filesystem": {
            "device_id": output_dir.stat().st_dev,
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "output_directory_mode": oct(output_dir.stat().st_mode & 0o777),
        },
    }


def child_cpu_seconds() -> float | None:
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def prepare_output_dir(path: Path) -> Path:
    if path.is_symlink() or path.exists():
        raise ScaleBenchmarkError("Output directory must not already exist; prior evidence is preserved.")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ScaleBenchmarkError("Output directory was created by another process; choose a unique run path.") from exc
    path.chmod(0o700)
    return path.resolve()


def timed_stage(
    name: str,
    operation: Callable[[], Any],
    measurements: dict[str, dict[str, Any]],
) -> Any:
    wall_start = time.perf_counter()
    python_cpu_start = time.process_time()
    child_cpu_start = child_cpu_seconds()
    result = operation()
    child_cpu_end = child_cpu_seconds()
    measurements[name] = {
        "wall_seconds": round(time.perf_counter() - wall_start, 3),
        "python_process_cpu_seconds": round(time.process_time() - python_cpu_start, 3),
        "child_process_cpu_seconds": (
            round(child_cpu_end - child_cpu_start, 3)
            if child_cpu_start is not None and child_cpu_end is not None else None
        ),
        "python_process_peak_rss_mb_after_stage": python_peak_rss_mb(),
        "largest_child_peak_rss_mb_after_stage": largest_child_peak_rss_mb(),
    }
    return result


def add_record_throughput(
    measurements: dict[str, dict[str, Any]],
    stage_name: str,
    *,
    record_count: int,
    record_basis: str,
) -> None:
    elapsed = measurements[stage_name]["wall_seconds"]
    measurements[stage_name]["throughput_record_count"] = record_count
    measurements[stage_name]["throughput_record_basis"] = record_basis
    measurements[stage_name]["records_per_second"] = (
        round(record_count / elapsed, 2) if elapsed > 0 else None
    )


def _route_summary(routing: dict[str, Any]) -> dict[str, Any]:
    reconciliation = routing.get("record_reconciliation") or {}
    return {
        "routing_version": routing.get("routing_version"),
        "source_record_count": routing.get("source_record_count"),
        "records_total": routing.get("records_total"),
        "record_reconciliation": reconciliation,
        "sequence_records": routing.get("sequence_records"),
        "gvcf_reference_blocks": routing.get("gvcf_reference_blocks"),
        "gvcf_unresolved_variant_records": routing.get("gvcf_unresolved_variant_records"),
        "structural_variant_records": routing.get("structural_variant_records"),
        "cnv_variant_records": routing.get("cnv_variant_records"),
        "repeat_expansion_records": routing.get("repeat_expansion_records"),
        "mitochondrial_variant_records": routing.get("mitochondrial_variant_records"),
        "spanning_deletion_records": routing.get("spanning_deletion_records"),
        "telomere_records": routing.get("telomere_records"),
        "telomere_after_contig_records": routing.get("telomere_after_contig_records"),
        "reference_only_records": routing.get("reference_only_records"),
    }


def run_benchmark(
    *,
    vcf_path: Path,
    reference_fasta: Path,
    reference_build: str,
    sample_name: str,
    output_dir: Path,
    timeout_seconds: int = 1800,
) -> dict[str, Any]:
    vcf_path = vcf_path.resolve(strict=True)
    reference_fasta = reference_fasta.resolve(strict=True)
    if not vcf_path.is_file() or not reference_fasta.is_file():
        raise ScaleBenchmarkError("VCF and reference FASTA must be regular files.")
    reference_fai = Path(str(reference_fasta) + ".fai")
    if not reference_fai.is_file():
        raise ScaleBenchmarkError("The selected reference FASTA index (.fai) is required.")
    if reference_build not in {"GRCh37", "GRCh38"}:
        raise ScaleBenchmarkError("Reference build must be GRCh37 or GRCh38.")
    if not sample_name or not sample_name.strip():
        raise ScaleBenchmarkError("An explicit specimen-mapped VCF sample name is required.")
    if timeout_seconds < 1:
        raise ScaleBenchmarkError("Normalization timeout must be positive.")

    input_size_bytes = vcf_path.stat().st_size
    output_dir = prepare_output_dir(output_dir)
    stage_metrics: dict[str, dict[str, Any]] = {}
    current_stage = "input_hashing"
    try:
        input_sha256 = timed_stage(
            current_stage,
            lambda: sha256_file(vcf_path),
            stage_metrics,
        )
        current_stage = "reference_hashing"
        reference_artifacts = timed_stage(
            current_stage,
            lambda: reference_artifact_snapshot(reference_fasta, reference_fai),
            stage_metrics,
        )

        current_stage = "vcf_validation"
        validation = timed_stage(
            current_stage,
            lambda: validate_vcf(vcf_path),
            stage_metrics,
        )
        if validation.status != "VALID":
            raise ScaleBenchmarkError("VCF intake validation did not return VALID.")
        if validation.detected_build and validation.detected_build != reference_build:
            raise ScaleBenchmarkError("The VCF-declared reference build conflicts with the selected reference build.")
        if sample_name not in validation.sample_names:
            raise ScaleBenchmarkError("The explicitly selected sample is absent from the VCF header.")
        if not validation.metadata:
            raise ScaleBenchmarkError("VCF validation did not provide toolchain attestation metadata.")
        if validation.metadata.get("toolchain_validation_status") != "PASS":
            raise ScaleBenchmarkError("Pinned BCFtools/HTSlib toolchain attestation did not pass.")
        source_record_count = int(validation.metadata.get("source_record_count") or 0)
        add_record_throughput(
            stage_metrics,
            current_stage,
            record_count=source_record_count,
            record_basis="source_vcf_records",
        )

        current_stage = "reference_validation"
        reference_validation = timed_stage(
            current_stage,
            lambda: validate_vcf_reference_alleles(vcf_path, reference_fasta),
            stage_metrics,
        )
        add_record_throughput(
            stage_metrics,
            current_stage,
            record_count=source_record_count,
            record_basis="source_vcf_records",
        )

        current_stage = "record_routing"
        routing = timed_stage(
            current_stage,
            lambda: route_vcf_records(vcf_path, output_dir / "routed"),
            stage_metrics,
        )
        route_summary = _route_summary(routing)
        reconciliation = route_summary["record_reconciliation"]
        if not reconciliation or reconciliation.get("balanced") is not True:
            raise ScaleBenchmarkError("Source-record and exclusive-routing disposition counts do not reconcile.")
        validated_source_count = validation.metadata.get("source_record_count")
        if validated_source_count is None or routing.get("source_record_count") != validated_source_count:
            raise ScaleBenchmarkError("Validation and routing source-record counts disagree.")
        add_record_throughput(
            stage_metrics,
            current_stage,
            record_count=source_record_count,
            record_basis="source_vcf_records",
        )
        if not routing.get("sequence_path"):
            raise ScaleBenchmarkError("The input contains no supported SNV/INDEL records to normalize.")

        current_stage = "reference_aware_normalization"
        normalized_path = output_dir / "normalized.vcf.gz"
        normalization = timed_stage(
            current_stage,
            lambda: normalize_vcf_with_bcftools(
                routing["sequence_path"],
                normalized_path,
                reference_fasta=reference_fasta,
                expected_bcftools_version=settings.bcftools_version,
                source_only_format_fields=validation.metadata.get("base_modification_format_fields", []),
                timeout_seconds=timeout_seconds,
            ),
            stage_metrics,
        )
        index_path = Path(str(normalized_path) + ".csi")
        if not normalized_path.is_file() or normalized_path.stat().st_size == 0:
            raise ScaleBenchmarkError("Normalization did not publish a non-empty BGZF VCF.")
        if not index_path.is_file() or index_path.stat().st_size == 0:
            raise ScaleBenchmarkError("Normalization did not publish its CSI index.")
        source_reconciliation = normalization.get("source_child_reconciliation") or {}
        if source_reconciliation.get("status") != "VALIDATED" or source_reconciliation.get("balanced") is not True:
            raise ScaleBenchmarkError("Normalized child records do not reconcile to their immutable source ALTs.")
        index_validation = normalization.get("index_validation") or {}
        if (
            index_validation.get("records") is None
            or index_validation.get("indexed_query_records_verified") != index_validation.get("records")
            or index_validation.get("indexed_query_contigs_verified") != index_validation.get("contigs")
            or source_reconciliation.get("normalized_child_records") != index_validation.get("records")
        ):
            raise ScaleBenchmarkError("CSI indexed-query record streams do not reconcile with the sequential VCF stream.")
        add_record_throughput(
            stage_metrics,
            current_stage,
            record_count=int(routing.get("sequence_records") or 0),
            record_basis="routed_sequence_source_records",
        )

        current_stage = "selected_sample_iteration"
        def count_selected_sample_records() -> int:
            count = 0
            for _variant in iter_normalized_vcf(
                normalized_path,
                reference_build,
                sample_name=sample_name,
            ):
                count += 1
            return count

        selected_normalized_record_count = timed_stage(
            current_stage,
            count_selected_sample_records,
            stage_metrics,
        )
        stage_metrics[current_stage]["selected_sample_normalized_record_count"] = selected_normalized_record_count
        add_record_throughput(
            stage_metrics,
            current_stage,
            record_count=selected_normalized_record_count,
            record_basis="selected_sample_normalized_records",
        )

        current_stage = "input_integrity_postcheck"
        input_sha256_after = timed_stage(
            current_stage,
            lambda: sha256_file(vcf_path),
            stage_metrics,
        )
        if input_sha256_after != input_sha256 or vcf_path.stat().st_size != input_size_bytes:
            raise ScaleBenchmarkError("The source VCF changed during the benchmark run.")

        current_stage = "reference_integrity_postcheck"
        reference_artifacts_after = timed_stage(
            current_stage,
            lambda: reference_artifact_snapshot(reference_fasta, reference_fai),
            stage_metrics,
        )
        if reference_artifacts_after != reference_artifacts:
            raise ScaleBenchmarkError("The selected reference FASTA/index artifacts changed during the benchmark run.")

        report = {
            "schema_version": "1",
            "status": "RUN_COMPLETE_REVIEW_REQUIRED",
            "benchmark_kind": "LAB_SUPPLIED_VCF_PROCESSING_SCALE",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "repository_commit": os.environ.get("GITHUB_SHA"),
            "runtime": {
                "platform": platform.platform(),
                "python_version": platform.python_version(),
                "python_process_peak_rss_mb": python_peak_rss_mb(),
                "largest_child_peak_rss_mb": largest_child_peak_rss_mb(),
                "stages": stage_metrics,
            },
            "deployment_resources": deployment_resource_snapshot(output_dir),
            "input": {
                "reference_build": reference_build,
                "size_bytes": input_size_bytes,
                "sha256": input_sha256,
                "integrity_verified_across_run": True,
                "sample_count": len(validation.sample_names),
                "selected_sample_identifier_recorded": False,
                "fileformat": validation.fileformat,
                "vcf_declared_reference_build": validation.detected_build,
            },
            "reference": {
                "artifacts": reference_artifacts,
                "integrity_verified_across_run": True,
                "validation": {
                    "checked_record_count": reference_validation.get("checked_record_count"),
                    "checked_breakend_mate_count": reference_validation.get("checked_breakend_mate_count"),
                    "unvalidated_telomere_record_count": reference_validation.get("unvalidated_telomere_record_count"),
                    "result": reference_validation.get("result"),
                },
            },
            "validation": {
                "status": validation.status,
                "source_record_count": validation.metadata.get("source_record_count"),
                "alternate_allele_count": validation.metadata.get("alternate_allele_count"),
                "parsed_variant_record_count": validation.record_count,
                "bcftools_version": validation.metadata.get("bcftools_version"),
                "htslib_version": validation.metadata.get("htslib_version"),
                "toolchain_validation_status": validation.metadata.get("toolchain_validation_status"),
            },
            "routing": route_summary,
            "normalization": {
                "tool": normalization.get("tool"),
                "tool_version": normalization.get("tool_version"),
                "operation": normalization.get("operation"),
                "compression": normalization.get("compression"),
                "index": normalization.get("index"),
                "index_validation": normalization.get("index_validation"),
                "source_child_reconciliation": normalization.get("source_child_reconciliation"),
                "source_only_format_fields": normalization.get("source_only_format_fields"),
                "source_only_format_fields_policy": normalization.get("source_only_format_fields_policy"),
                "normalized_vcf_size_bytes": normalized_path.stat().st_size,
                "normalized_vcf_sha256": sha256_file(normalized_path),
                "csi_size_bytes": index_path.stat().st_size,
                "selected_sample_normalized_record_count": selected_normalized_record_count,
            },
            "acceptance_boundary": (
                "This run measures this input and deployment only. It does not establish clinical "
                "validity, caller qualification, GIAB concordance, production capacity, or a PASS "
                "against laboratory-defined performance thresholds. A laboratory reviewer must "
                "evaluate the metrics against preapproved intended-use criteria."
            ),
        }
        report_path = output_dir / REPORT_NAME
        temporary_report = output_dir / f".{REPORT_NAME}.tmp"
        temporary_report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_report, report_path)
        return report
    except Exception as exc:
        failure = {
            "schema_version": "1",
            "status": "FAILED",
            "failed_stage": current_stage,
            "exception_type": type(exc).__name__,
            "generated_at_utc": datetime.now(UTC).isoformat(),
        }
        failure_path = output_dir / FAILURE_NAME
        temporary_failure = output_dir / f".{FAILURE_NAME}.tmp"
        temporary_failure.write_text(
            json.dumps(failure, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_failure, failure_path)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure VCF validation, reference checking, routing and normalization on a lab-supplied VCF."
    )
    parser.add_argument("--vcf", required=True, type=Path, help="De-identified VCF/VCF.GZ input.")
    parser.add_argument("--reference-fasta", required=True, type=Path, help="Exact GRCh37/GRCh38 FASTA used by the lab.")
    parser.add_argument("--reference-build", required=True, choices=("GRCh37", "GRCh38"))
    parser.add_argument("--output-dir", required=True, type=Path, help="New, non-existent directory for benchmark artifacts; existing paths are never reused.")
    parser.add_argument(
        "--sample-name-env",
        default="SIRALOOM_BENCHMARK_SAMPLE_NAME",
        help="Environment variable containing the specimen-mapped sample name (default: SIRALOOM_BENCHMARK_SAMPLE_NAME).",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    sample_name = os.environ.get(args.sample_name_env)
    if not sample_name:
        sample_name = getpass.getpass("Specimen-mapped VCF sample name (input hidden): ").strip()
    try:
        report = run_benchmark(
            vcf_path=args.vcf,
            reference_fasta=args.reference_fasta,
            reference_build=args.reference_build,
            sample_name=sample_name,
            output_dir=args.output_dir,
            timeout_seconds=args.timeout_seconds,
        )
    except Exception as exc:
        print(f"VCF scale benchmark failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "status": report["status"],
        "report": str(args.output_dir.resolve() / REPORT_NAME),
        "source_record_count": report["validation"]["source_record_count"],
        "selected_sample_normalized_record_count": report["normalization"]["selected_sample_normalized_record_count"],
        "python_process_peak_rss_mb": report["runtime"]["python_process_peak_rss_mb"],
        "largest_child_peak_rss_mb": report["runtime"]["largest_child_peak_rss_mb"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
