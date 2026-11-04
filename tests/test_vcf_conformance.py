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
    # Execution success is deliberately distinct from complete normative
    # coverage; the current corpus is a regression suite, not a full spec
    # certification corpus.
    assert report["normative_coverage_sections"] == []
    assert report["normative_coverage_status"] == "PARTIAL"
    assert report["normative_uncovered_sections"]
    if version == "VCFv4.0":
        assert "Original historical source response bytes and SHA-256 not yet archived" in report["normative_uncovered_sections"]
    else:
        assert "Complete normative clause inventory with stable clause identifiers for this VCF release" in report["normative_uncovered_sections"]
    assert report["fixture_categories_exercised"]
    assert report["specification_requirements_exercised"]
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


def test_vcf40_fixtures_have_unique_ids_atomic_clause_links_and_consistent_columns():
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / "backend"
        / "app"
        / "domain"
        / "vcf_conformance_cases.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    fixtures = manifest["versions"]["VCFv4.0"]

    fixture_ids = [fixture["id"] for fixture in fixtures]
    assert len(fixture_ids) == len(set(fixture_ids))

    for fixture in fixtures:
        assert fixture.get("clause_ids"), fixture["id"]
        assert all(
            clause_id.startswith("V40-CORE-")
            for clause_id in fixture["clause_ids"]
        ), fixture["id"]

        lines = fixture["lines"]
        header = next(
            line for line in lines if line.startswith("#CHROM\\t")
        )
        expected_columns = len(header.split("\\t"))
        for line in lines:
            if line and not line.startswith("#"):
                assert len(line.split("\\t")) == expected_columns, (
                    fixture["id"],
                    line,
                    expected_columns,
                )

    assert any(
        fixture["id"] == "legacy_invalid_pos_rejected"
        and fixture["expected"] == "VCF_POS_INVALID"
        for fixture in fixtures
    )
