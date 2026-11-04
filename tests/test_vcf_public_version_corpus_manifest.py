from __future__ import annotations

import json
import re
from pathlib import Path


MANIFEST_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "domain"
    / "vcf_public_version_corpus.json"
)

EXPECTED_VERSIONS = {
    "VCFv4.0",
    "VCFv4.1",
    "VCFv4.2",
    "VCFv4.3",
    "VCFv4.4",
    "VCFv4.5",
}

SUPPORTED_ROUTE_CATEGORIES = {
    "sequence",
    "reference_only",
    "gvcf_reference_blocks",
    "gvcf_unresolved_variants",
    "structural_variants",
    "copy_number_variants",
    "repeat_expansions",
    "mitochondrial_variants",
    "spanning_deletions",
    "telomere_coordinates",
    "after_contig_coordinates",
}


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_public_vcf_corpus_has_explicit_minimum_source_and_producer_coverage() -> None:
    manifest = load_manifest()
    sources = manifest["sources"]
    minimum_sources = manifest["minimum_sources_per_version"]
    minimum_producers = manifest["minimum_unique_producers_per_version"]

    assert set(manifest["version_policy"]) == EXPECTED_VERSIONS
    assert {source["version"] for source in sources} == EXPECTED_VERSIONS
    assert len({source["id"] for source in sources}) == len(sources)

    for version in EXPECTED_VERSIONS:
        version_sources = [source for source in sources if source["version"] == version]
        producers = {source["producer"] for source in version_sources}
        assert len(version_sources) >= minimum_sources[version]
        assert len(producers) >= minimum_producers[version]


def test_every_public_vcf_source_is_immutable_and_has_a_routing_expectation() -> None:
    manifest = load_manifest()

    for source in manifest["sources"]:
        assert source["producer"].strip()
        assert source["repository"].count("/") == 1
        assert re.fullmatch(r"[0-9a-f]{40}", source["commit"])
        assert re.fullmatch(r"[0-9a-f]{40}", source["git_blob_sha1"])
        assert source["size_bytes"] > 0
        assert source["url"].startswith("https://raw.githubusercontent.com/")
        assert source["commit"] in source["url"]
        assert source["path"] in source["url"]
        assert source["expected_route_category"] in SUPPORTED_ROUTE_CATEGORIES
