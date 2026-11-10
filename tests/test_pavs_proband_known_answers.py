from __future__ import annotations

import hashlib
import json
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "clinical_known_answers" / "pavs"


def test_pavs_proband_known_answers_are_pinned_and_reproducible():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_commit"] == "ca56e453b9090f7b90ef256c5aca8e8c672c18b4"
    assert manifest["data_license"] == "CC-BY-4.0"
    assert "proband-level" in manifest["intended_use"]

    assert len(manifest["cases"]) == 4
    for expected in manifest["cases"]:
        path = FIXTURE_DIR / Path(expected["path"]).name
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected["sha256"]
        packet = json.loads(raw)
        assert packet["id"] == expected["id"]
        assert packet["metaData"]["phenopacketSchemaVersion"] in {"2.0", "2.0.2"}
        assert packet["phenotypicFeatures"]

        disease = packet["diseases"][0]
        assert disease["term"]["id"] == expected["disease"]
        assert disease["modeOfInheritance"]["label"] == expected["moi"]

        interpretation = packet["interpretations"][0]
        assert interpretation["progressStatus"] == "SOLVED"
        genomic = interpretation["diagnosis"]["genomicInterpretations"]
        assert genomic
        causative = [
            item for item in genomic
            if item["interpretationStatus"] == expected["variant_status"]
        ]
        assert causative
        # This corpus is explicitly proband-level: no parent or sibling calls
        # are present, and the records cannot be used as segregation truth.
        assert {
            item["subjectOrBiosampleId"] for item in genomic
        } == {packet["id"]}

        descriptors = [
            item["variantInterpretation"]["variationDescriptor"]
            for item in causative
        ]
        matching = [
            descriptor for descriptor in descriptors
            if descriptor.get("geneContext", {}).get("symbol") == expected["gene"]
        ]
        assert matching
        assert any(
            descriptor.get("allelicState", {}).get("label") == expected["allelic_state"]
            for descriptor in matching
        )
        assert any(
            item["variantInterpretation"].get("acmgPathogenicityClassification") == expected["acmg"]
            for item in causative
        )
        assert any(
            feature.get("type", {}).get("id", "").startswith("HP:")
            for feature in packet["phenotypicFeatures"]
        )
        assert any(
            ref.get("id", "").startswith("PMID:")
            for ref in packet["metaData"].get("externalReferences", [])
        )


def test_pavs_corpus_explicitly_blocks_family_inheritance_qualification():
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    limitations = " ".join(manifest["limitations"]).casefold()
    assert "parent/relative genotype calls" in limitations
    assert "segregation" in limitations
    assert "de novo" in limitations
    assert "x-linked dominant versus recessive" in limitations
