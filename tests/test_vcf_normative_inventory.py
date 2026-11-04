"""Verify source-pinned VCF specification inventory and fixture traceability."""
from __future__ import annotations

import json
import re
import pytest
from pathlib import Path

from backend.app.domain.vcf_normative_inventory import (
    SPEC_BLOB_SHA1,
    SPEC_EXPECTED_CANDIDATE_LINES,
    extract_vcf_normative_candidates,
    git_blob_sha1,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "backend" / "app" / "domain" / "vcf_conformance_cases.json"
INVENTORY_PATH = (
    REPO_ROOT / "docs" / "implementation" / "VCF_NORMATIVE_SECTION_INVENTORY.json"
)


def test_official_vcf_normative_section_inventory_is_source_pinned():
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    documents = {item["version"]: item for item in inventory["documents"]}
    assert set(documents) == {
        "VCFv4.1",
        "VCFv4.2",
        "VCFv4.3",
        "VCFv4.4",
        "VCFv4.5",
    }
    for version, document in documents.items():
        assert document["document_url"].endswith(f"/{version}.pdf")
        assert re.fullmatch(r"[0-9a-f]{40}", document["git_blob_sha1"])
        assert document["heading_count"] == len(document["headings"])
        assert document["table_caption_count"] == len(document["table_captions"])
        assert document["heading_count"] >= 40
        assert document["table_caption_count"] >= 10


def test_versioned_fixture_evidence_maps_only_to_official_inventory_sections():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    documents = {item["version"]: item for item in inventory["documents"]}

    for version, document in documents.items():
        coverage = manifest["normative_coverage"][version]
        fixture_ids = {case["id"] for case in manifest["versions"][version]}
        official_sections = {heading["title"] for heading in document["headings"]}
        assert coverage["status"] == "PARTIAL"
        assert coverage["covered_sections"] == []
        assert coverage["tested_sections"]
        for evidence in coverage["tested_sections"]:
            assert evidence["section_title"] in official_sections
            assert evidence["fixture_ids"]
            assert len(evidence["fixture_ids"]) == len(set(evidence["fixture_ids"]))
            assert set(evidence["fixture_ids"]).issubset(fixture_ids)


def test_producer_interoperability_is_not_counted_as_normative_vcf_conformance():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for version, cases in manifest["versions"].items():
        for case in cases:
            if case.get("qualification_scope") == "producer_interoperability":
                assert case["normative_vcf_conformance"] is False
                assert case["producer"] == "GATK"


def test_normative_candidate_extraction_is_deterministic_and_tracks_sections(tmp_path: Path):
    source_dir = tmp_path / "specs"
    source_dir.mkdir()
    slash = chr(92)
    fixture = (
        f"{slash}section{{The VCF specification}}\n"
        + "The fileformat line must be present.\n"
        + f"{slash}subsection{{Samples}}\n"
        + "A sample field should not be omitted.\n"
        + "% A commented rule must not be counted.\n"
    ).encode("utf-8")
    expected_blobs = {}
    for version in SPEC_BLOB_SHA1:
        path = source_dir / f"{version}.tex"
        path.write_bytes(fixture)
        expected_blobs[version] = git_blob_sha1(fixture)

    inventory = extract_vcf_normative_candidates(
        source_dir,
        expected_blob_shas=expected_blobs,
        expected_candidate_lines={version: 2 for version in SPEC_BLOB_SHA1},
    )
    assert inventory["inventory_status"] == "EXTRACTED_UNREVIEWED"
    assert inventory["qualification_status"] == "BLOCKED_PENDING_CLAUSE_REVIEW_AND_TRACEABILITY"
    for version in SPEC_BLOB_SHA1:
        candidates = inventory["versions"][version]["candidates"]
        assert [candidate["source_line"] for candidate in candidates] == [2, 4]
        assert candidates[1]["section_path"][-1]["heading"] == "Samples"
        assert candidates[0]["review_status"] == "UNREVIEWED"
        assert candidates[0]["traceability_status"] == "UNMAPPED"
        assert candidates[0]["section_path"][0]["heading"] == "The VCF specification"
        assert "text" not in candidates[0]


def test_normative_candidate_extractor_rejects_unpinned_source_content(tmp_path: Path):
    source_dir = tmp_path / "specs"
    source_dir.mkdir()
    for version in SPEC_BLOB_SHA1:
        (source_dir / f"{version}.tex").write_text(
            "untrusted replacement source\n", encoding="utf-8"
        )

    with pytest.raises(ValueError, match="Official source blob mismatch"):
        extract_vcf_normative_candidates(source_dir)


def test_public_vcf_corpus_has_independent_freebayes_and_gatk_sources():
    manifest = json.loads(
        (REPO_ROOT / "backend" / "app" / "domain" / "vcf_public_version_corpus.json").read_text(
            encoding="utf-8"
        )
    )
    by_version = {}
    for source in manifest["sources"]:
        by_version.setdefault(source["version"], []).append(source)

    assert len(by_version["VCFv4.1"]) == 2
    assert {source["repository"] for source in by_version["VCFv4.1"]} == {
        "jamescasbon/PyVCF",
        "vcflib/vcflib",
    }
    assert any(
        source["source_class"] == "upstream_freebayes_producer_regression_file"
        and source["expected_route_category"] == "sequence"
        for source in by_version["VCFv4.1"]
    )

    assert len(by_version["VCFv4.2"]) == 2
    assert {source["repository"] for source in by_version["VCFv4.2"]} == {
        "jamescasbon/PyVCF",
        "broadinstitute/gatk",
    }
    gatk_gvcf = next(
        source for source in by_version["VCFv4.2"]
        if source["repository"] == "broadinstitute/gatk"
    )
    assert gatk_gvcf["expected_route_category"] == "gvcf_reference_blocks"
    assert gatk_gvcf["git_blob_sha1"] == "858c09398d54d680767860c6dfbad6ca8f1ceda9"


def test_public_vcf_corpus_route_categories_cover_gvcf_reference_blocks():
    runner_path = REPO_ROOT / "scripts" / "validation" / "qualify_public_vcf_version_corpus.py"
    runner_source = runner_path.read_text(encoding="utf-8")
    assert '"gvcf_reference_blocks": routing.get("gvcf_reference_blocks", 0)' in runner_source


def test_public_vcf_corpus_separates_malformed_real_world_sources_from_positive_sources():
    manifest = json.loads(
        (REPO_ROOT / "backend" / "app" / "domain" / "vcf_public_version_corpus.json").read_text(
            encoding="utf-8"
        )
    )
    positive_ids = {source["id"] for source in manifest["sources"]}
    negative_ids = {source["id"] for source in manifest["negative_sources"]}

    assert positive_ids.isdisjoint(negative_ids)
    assert "pyvcf-example-v4.2" not in positive_ids
    negative = next(
        source for source in manifest["negative_sources"]
        if source["id"] == "pyvcf-example-v4.2"
    )
    assert negative["expected_outcome"] == "REJECT"
    assert negative["expected_strict_error_code"] == "VCF_HEADER_DEFINITION_INVALID"
    assert negative["expected_bcftools_stderr_contains"] == "could not parse"
    assert manifest["minimum_sources_per_version"]["VCFv4.2"] == 4
    assert manifest["minimum_unique_producers_per_version"]["VCFv4.2"] == 3


def test_public_vcf_corpus_runner_executes_negative_sources():
    runner_source = (
        REPO_ROOT / "scripts" / "validation" / "qualify_public_vcf_version_corpus.py"
    ).read_text(encoding="utf-8")
    assert "def qualify_negative_source(" in runner_source
    assert 'manifest.get("negative_sources", [])' in runner_source
    assert '"negative_source_results": negative_reports' in runner_source


def test_production_container_report_distinguishes_source_rows_and_alt_expansion():
    script = (
        REPO_ROOT / "scripts" / "validation" / "qualify_public_vcf_in_container.py"
    ).read_text(encoding="utf-8")
    assert '"source_record_count": source_record_count' in script
    assert '"alternate_allele_count": intake.metadata["alternate_allele_count"]' in script
    assert '"parsed_variant_record_count": intake.metadata["parsed_variant_record_count"]' in script
    assert '"source_record_count_matches_routing": True' in script
    assert "ALT-expanded parsed variant records" in script
