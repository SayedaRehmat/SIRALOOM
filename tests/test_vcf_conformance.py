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
            line for line in lines if line.startswith("#CHROM\t")
        )
        expected_columns = len(header.split("\t"))
        data_lines = [line for line in lines if line and not line.startswith("#")]
        if fixture["expected"] == "VCF_RECORD_INVALID":
            assert any(
                len(line.split("\t")) != expected_columns
                for line in data_lines
            ), fixture["id"]
        else:
            for line in data_lines:
                assert len(line.split("\t")) == expected_columns, (
                    fixture["id"],
                    line,
                    expected_columns,
                )

    assert any(
        fixture["id"] == "legacy_invalid_pos_rejected"
        and fixture["expected"] == "VCF_POS_INVALID"
        for fixture in fixtures
    )


def test_vcf40_supported_sequence_records_survive_unsupported_sv_cnv_routing(tmp_path):
    from backend.app.domain.vcf_tools import route_vcf_records
    from backend.app.domain.vcf_validation import validate_vcf_strict

    source = tmp_path / "mixed-vcf40.vcf"
    source.write_text(
        "\n".join(
            [
                "##fileformat=VCFv4.0",
                '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Structural variant type">',
                '##INFO=<ID=END,Number=1,Type=Integer,Description="End position">',
                "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO",
                "1\t100\trsV40\tA\tC\t50\tPASS\t.",
                "1\t200\tsvV40\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=210",
                "1\t300\tcnvV40\tA\t<CNV>\t.\tPASS\tSVTYPE=CNV;END=350",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    profile = validate_vcf_strict(source)
    assert profile["fileformat"] == "VCFv4.0"
    assert profile["records"] == 3

    output = tmp_path / "routed"
    routing = route_vcf_records(source, output)

    assert routing["sequence_records"] == 1
    assert routing["structural_variant_records"] == 1
    assert routing["cnv_variant_records"] == 1
    assert routing["record_reconciliation"]["balanced"] is True
    assert routing["record_reconciliation"]["source_records"] == 3
    assert routing["record_reconciliation"]["routed_records"] == 3

    sequence_text = (output / "sequence-input.vcf").read_text(encoding="utf-8")
    structural_text = (output / "structural-variants.vcf").read_text(encoding="utf-8")
    cnv_text = (output / "copy-number-variants.vcf").read_text(encoding="utf-8")
    exclusions = [
        json.loads(line)
        for line in (output / "excluded-source-records.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert "rsV40" in sequence_text
    assert "svV40" not in sequence_text
    assert "svV40" in structural_text
    assert "cnvV40" in cnv_text
    assert {item["reason_code"] for item in exclusions} == {
        "STRUCTURAL_VARIANT_INTERPRETATION_UNSUPPORTED",
        "CNV_PIPELINE_PENDING",
    }
