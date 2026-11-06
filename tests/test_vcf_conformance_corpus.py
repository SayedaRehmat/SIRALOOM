from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = (
    REPOSITORY_ROOT
    / "backend"
    / "app"
    / "domain"
    / "vcf_conformance_cases.json"
)
with CORPUS_PATH.open("r", encoding="utf-8") as corpus_file:
    CONFORMANCE_CORPUS = json.load(corpus_file)

CASES = [
    (version, case)
    for version, version_cases in CONFORMANCE_CORPUS["versions"].items()
    for case in version_cases
]


@pytest.mark.parametrize(
    ("version", "case"),
    CASES,
    ids=[f"{version}-{case['id']}" for version, case in CASES],
)
def test_vcf_conformance_corpus_case_executes(
    tmp_path: Path, version: str, case: dict[str, object]
):
    lines = case["lines"]
    assert isinstance(lines, list) and lines
    assert lines[0] == f"##fileformat={version}"

    vcf_path = tmp_path / f"{version}-{case['id']}.vcf"
    vcf_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    expected = case["expected"]
    if expected == "PASS":
        result = validate_vcf_strict(vcf_path)
        expected_record_count = sum(not line.startswith("#") for line in lines)
        assert result["records"] == expected_record_count
        return

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(vcf_path)

    assert exc.value.code == expected


def test_vcf_conformance_corpus_fixture_ids_are_unique_per_version():
    for version, version_cases in CONFORMANCE_CORPUS["versions"].items():
        fixture_ids = [case["id"] for case in version_cases]
        assert len(fixture_ids) == len(set(fixture_ids)), version


def test_vcf_conformance_coverage_references_existing_fixtures():
    for version, coverage in CONFORMANCE_CORPUS["normative_coverage"].items():
        available_ids = {
            case["id"] for case in CONFORMANCE_CORPUS["versions"][version]
        }
        for section in coverage.get("tested_sections", []):
            assert set(section["fixture_ids"]) <= available_ids, (
                version,
                section["section_title"],
            )


def test_vcf40_conformance_fixtures_have_atomic_clause_links():
    for case in CONFORMANCE_CORPUS["versions"]["VCFv4.0"]:
        clause_ids = case.get("clause_ids", [])
        assert clause_ids, case["id"]
        assert all(
            clause_id.startswith("V40-CORE-") for clause_id in clause_ids
        ), case["id"]


def test_no_vcf_version_is_declared_fully_conformant_by_regression_corpus():
    for version, coverage in CONFORMANCE_CORPUS["normative_coverage"].items():
        assert coverage["status"] != "COMPLETE", version
