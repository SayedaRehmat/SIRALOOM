"""Verify source-pinned VCF specification inventory and fixture traceability."""
from __future__ import annotations

import json
import re
from pathlib import Path


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
