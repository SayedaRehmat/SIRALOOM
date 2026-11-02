"""Execution-level qualification checks for the packaged VCF parser corpus."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from backend.app.domain.vcf_conformance import execute_vcf_conformance_suite
from backend.app.domain.vcf_spec_registry import BUILTIN_VCF_SPECIFICATION_VERSIONS


@pytest.mark.parametrize("version", sorted(BUILTIN_VCF_SPECIFICATION_VERSIONS))
def test_packaged_vcf_conformance_executes_for_each_builtin_version(version):
    report = execute_vcf_conformance_suite(version)

    assert report["suite_id"] == "siraloom-vcf-native-conformance-v1"
    assert report["target_version"] == version
    assert report["test_case_count"] > 0
    assert report["failed_test_count"] == 0
    assert report["passed_test_count"] == report["test_case_count"]
    assert report["execution_status"] == "PASSED"
    assert len(report["corpus_sha256"]) == 64
    assert len(report["parser_source_sha256"]) == 64
    assert len(report["runner_source_sha256"]) == 64

    claimed_digest = report.pop("report_sha256")
    canonical = json.dumps(
        report,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == claimed_digest


def test_unknown_vcf_version_has_no_implicit_conformance_suite():
    report = execute_vcf_conformance_suite("VCFv99.0")

    assert report["target_version"] == "VCFv99.0"
    assert report["test_case_count"] == 0
    assert report["execution_status"] == "FAILED"
    assert report["failed_test_count"] == 0
