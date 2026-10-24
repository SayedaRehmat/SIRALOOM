from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest

from backend.app.adapters.phenotype.hpo_obo import HPOOboProvider, HPOOntologyError
from backend.app.domain.provider_registry import register_builtin_providers
from backend.app.domain.resource_capabilities import (
    ResourceCapability,
    get_scientific_provider,
    infer_capabilities,
)
from backend.app.evidence.engine import EvidenceEngine

OBO = """format-version: 1.2
data-version: releases/2026-09-01
ontology: hp.obo

[Term]
id: HP:0000001
name: Root

[Term]
id: HP:0000002
name: Parent
is_a: HP:0000001 ! Root

[Term]
id: HP:0000003
name: Current term
alt_id: HP:0000099
is_a: HP:0000002 ! Parent

[Term]
id: HP:0000004
name: obsolete old term
is_obsolete: true
replaced_by: HP:0000003

[Term]
id: HP:0000005
name: obsolete without replacement
is_obsolete: true
consider: HP:0000002
"""


def _provider(tmp_path):
    path = tmp_path / "hp.obo"
    path.write_text(OBO, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")


def test_hpo_obo_resolves_canonical_and_alternate_ids_and_is_a_ancestors(tmp_path):
    provider = _provider(tmp_path)

    assert provider.release == "2026-09-01"
    assert provider.resolve("HP:0000003").status == "CURRENT"
    alternate = provider.resolve("hp:0000099")
    assert (alternate.status, alternate.canonical_id) == ("ALTERNATE_ID", "HP:0000003")
    assert provider.ancestors("HP:0000003") == {"HP:0000001", "HP:0000002"}
    assert provider.ancestor_map(["HP:0000099"]) == {
        "HP:0000099": ["HP:0000001", "HP:0000002"]
    }


def test_hpo_obo_accepts_official_base_ontology_identity(tmp_path):
    obo = OBO.replace("ontology: hp.obo", "ontology: hp/hp-base").replace(
        "data-version: releases/2026-09-01",
        "data-version: hp/releases/2026-09-01/hp-base.owl",
    )
    path = tmp_path / "hp-base.obo"
    path.write_text(obo, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    provider = HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")

    assert provider.release == "2026-09-01"
    assert provider.resolve("HP:0000003").status == "CURRENT"
    assert provider.ancestors("HP:0000003") == {"HP:0000001", "HP:0000002"}


def test_hpo_obo_accepts_obo_relationship_modifiers_and_diamond_dag(tmp_path):
    obo = """format-version: 1.2
data-version: releases/2026-09-01
ontology: hp.obo

[Term]
id: HP:0000001
name: Root

[Term]
id: HP:0000002
name: Left
is_a: HP:0000001 {xref="PMID:1"} ! Root

[Term]
id: HP:0000003
name: Right
is_a: HP:0000001 {xref="PMID:2"} ! Root

[Term]
id: HP:0000004
name: Diamond leaf
is_a: HP:0000002 ! Left
is_a: HP:0000003 {xref="PMID:3"} ! Right
"""
    path = tmp_path / "hp-qualified.obo"
    path.write_text(obo, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    provider = HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")

    assert provider.ancestors("HP:0000004") == {
        "HP:0000001", "HP:0000002", "HP:0000003"
    }


def test_hpo_obo_uses_only_explicit_unambiguous_obsolete_replacement(tmp_path):
    provider = _provider(tmp_path)

    obsolete = provider.resolve("HP:0000004")
    assert obsolete.status == "OBSOLETE_REPLACED"
    assert obsolete.canonical_id == "HP:0000003"
    assert obsolete.replacement_candidates == ("HP:0000003",)
    assert provider.ancestors("HP:0000004") == {"HP:0000001", "HP:0000002"}
    consider = provider.resolve("HP:0000005")
    assert consider.status == "OBSOLETE"
    assert consider.canonical_id is None
    assert consider.consider == ("HP:0000002",)
    assert provider.resolve("HP:9999999").status == "UNKNOWN"
    assert provider.resolve("not-an-hpo-id").status == "INVALID"


def test_hpo_obo_marks_conflicting_obsolete_and_alternate_ids_ambiguous(tmp_path):
    obo = """format-version: 1.2
data-version: releases/2026-09-01
ontology: hp.obo

[Term]
id: HP:0000001
name: Root

[Term]
id: HP:0000002
name: Current broad term
alt_id: HP:0000003
is_a: HP:0000001

[Term]
id: HP:0000003
name: obsolete specific term
is_obsolete: true
consider: HP:0000002
"""
    path = tmp_path / "hp-ambiguous.obo"
    path.write_text(obo, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    provider = HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")

    resolution = provider.resolve("HP:0000003")

    assert resolution.status == "AMBIGUOUS"
    assert resolution.canonical_id is None
    assert resolution.ambiguous_candidates == ("HP:0000002", "HP:0000003")


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("format-version: 1.2\n", "ontology identity"),
        ("format-version: 1.2\nontology: other.obo\n", "ontology identity"),
        ("format-version: 1.0\nontology: hp.obo\n", "Unsupported HPO OBO format version"),
        ("format-version: 1.2\nformat-version: 1.2\n", "repeats field format-version"),
        ("ontology: hp.obo\nontology: hp.obo\n", "repeats field ontology"),
    ],
)
def test_hpo_obo_requires_supported_unambiguous_header(tmp_path, header, message):
    path = tmp_path / "header-check.obo"
    path.write_text(
        f"{header}data-version: releases/2026-09-01\n\n"
        "[Term]\nid: HP:0000001\nname: Root\n",
        encoding="utf-8",
    )
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(HPOOntologyError, match=message):
        HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")


def test_hpo_obo_requires_matching_checksum_and_release(tmp_path):
    path = tmp_path / "hp.obo"
    path.write_text(OBO, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(HPOOntologyError, match="checksum"):
        HPOOboProvider(path, expected_sha256="0" * 64, expected_release="2026-09-01")
    with pytest.raises(HPOOntologyError, match="release mismatch"):
        HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-01-01")
    with pytest.raises(HPOOntologyError, match="SHA-256 pin is required"):
        HPOOboProvider(path, expected_sha256="", expected_release="2026-09-01")


def test_hpo_parser_uses_the_exact_bytes_that_passed_checksum_validation(tmp_path, monkeypatch):
    path = tmp_path / "hp.obo"
    path.write_text(OBO, encoding="utf-8")
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    original_open = type(path).open
    open_count = 0

    def replace_between_reads(target, *args, **kwargs):
        nonlocal open_count
        if target == path:
            open_count += 1
            if open_count == 2:
                with original_open(target, "wb") as stream:
                    stream.write(OBO.replace("Current term", "Changed after checksum").encode("utf-8"))
        return original_open(target, *args, **kwargs)

    monkeypatch.setattr(type(path), "open", replace_between_reads)
    provider = HPOOboProvider(
        path, expected_sha256=checksum, expected_release="2026-09-01"
    )

    assert provider.sha256 == checksum
    assert provider.resolve("HP:0000003").label == "Current term"
    assert "Changed after checksum" in path.read_text(encoding="utf-8")


def test_hpo_obo_rejects_cyclic_is_a_graph(tmp_path):
    path = tmp_path / "cyclic.obo"
    path.write_text(
        "format-version: 1.2\nontology: hp.obo\ndata-version: releases/2026-09-01\n\n"
        "[Term]\nid: HP:0000001\nname: One\nis_a: HP:0000002\n\n"
        "[Term]\nid: HP:0000002\nname: Two\nis_a: HP:0000001\n",
        encoding="utf-8",
    )
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(HPOOntologyError, match="contains a cycle"):
        HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")


@pytest.mark.parametrize("field_value", ["yes", "1", "true\nis_obsolete: false"])
def test_hpo_obo_rejects_invalid_or_duplicate_obsolete_flags(tmp_path, field_value):
    path = tmp_path / "invalid-obsolete.obo"
    path.write_text(
        "format-version: 1.2\nontology: hp.obo\ndata-version: releases/2026-09-01\n\n"
        "[Term]\nid: HP:0000001\nname: Term\n"
        f"is_obsolete: {field_value}\n",
        encoding="utf-8",
    )
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()

    with pytest.raises(HPOOntologyError, match="invalid is_obsolete value|repeats field is_obsolete"):
        HPOOboProvider(path, expected_sha256=checksum, expected_release="2026-09-01")


def test_broader_patient_term_does_not_imply_specific_disease_term(tmp_path):
    ontology = _provider(tmp_path)
    resource_id = uuid4()
    provenance = {
        "resource_id": str(resource_id),
        "resource_version": "2026-09-01",
        "resource_checksum": ontology.sha256,
        "request_fingerprint": "a" * 64,
        "response_sha256": "b" * 64,
    }
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id": "HP:0000002", "present": True}],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1",
            "disease": "Example disorder",
            "hpo_terms": ["HP:0000003"],
            "hpo_ancestor_map": {"HP:0000003": ["HP:0000002"]},
        }],
        hpo_ontology=ontology,
        hpo_provenance=provenance,
    )
    phenotype = next(record for record in records if record.evidence_type == "PHENOTYPE")
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert phenotype.resource_id == resource_id
    assert phenotype.source_version == "2026-09-01"
    assert phenotype.response_sha256 == "b" * 64
    assert disease.payload["phenotype_match"]["status"] == "SCORED"
    assert disease.payload["phenotype_match"]["clinical_prioritization_validated"] is False
    assert "priority_adjustment" not in disease.payload["phenotype_match"]
    assert disease.payload["phenotype_match"]["method"] == "HPO_PATIENT_DESCENDANT_OVERLAP"
    assert disease.payload["phenotype_match"]["matched_terms"] == []
    assert disease.payload["phenotype_match"]["score"] == 0.0
    assert disease.payload["phenotype_match"]["ontology_provenance"]["resource_checksum"] == ontology.sha256
    assert "hpo_ancestor_map" not in disease.payload


def test_more_specific_patient_term_matches_broader_disease_annotation(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id": "HP:0000003", "present": True}],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000002"]
        }],
        hpo_ontology=ontology,
    )
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")

    assert disease.payload["phenotype_match"]["status"] == "SCORED"
    assert disease.payload["phenotype_match"]["matched_terms"] == ["HP:0000003"]
    assert disease.payload["phenotype_match"]["score"] == 1.0
    assert disease.payload["phenotype_match"]["clinical_prioritization_validated"] is False


def test_invalid_or_obsolete_phenotypes_require_review_in_pinned_ontology(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id": "HP:0000005", "present": True}],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000003"]
        }],
        hpo_ontology=ontology,
    )
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert disease.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert disease.payload["phenotype_match"]["unresolved_patient_terms"] == [
        {"hpo_id": "HP:0000005", "status": "OBSOLETE"}
    ]


def test_negative_only_patient_phenotypes_do_not_become_a_zero_similarity_score(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id": "HP:0000002", "present": False}],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000003"]
        }],
        hpo_ontology=ontology,
    )

    phenotype = next(record for record in records if record.evidence_type == "PHENOTYPE")
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert phenotype.payload["negative_terms"] == [{"hpo_id": "HP:0000002", "label": None}]
    assert disease.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert disease.payload["phenotype_match"]["negative_patient_terms"] == ["HP:0000002"]
    assert "score" not in disease.payload["phenotype_match"]


def test_contradictory_patient_presence_and_absence_requires_review(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[
            {"hpo_id": "HP:0000002", "present": True},
            {"hpo_id": "HP:0000002", "present": False},
        ],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000003"]
        }],
        hpo_ontology=ontology,
    )

    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert disease.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert disease.payload["phenotype_match"]["contradictory_patient_terms"] == ["HP:0000002"]
    assert "score" not in disease.payload["phenotype_match"]


def test_hpo_explicit_obsolete_replacement_keeps_original_id_and_scores_canonical_term(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[{"hpo_id": "HP:0000004", "present": True}],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000003"]
        }],
        hpo_ontology=ontology,
    )

    phenotype = next(record for record in records if record.evidence_type == "PHENOTYPE")
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert phenotype.payload["ontology_term_resolutions"] == [{
        "hpo_id": "HP:0000004",
        "phenotype_status": "PRESENT",
        "status": "OBSOLETE_REPLACED",
        "canonical_id": "HP:0000003",
        "replacement_candidates": ["HP:0000003"],
        "consider": [],
        "ambiguous_candidates": [],
    }]
    assert disease.payload["phenotype_match"]["status"] == "SCORED"
    assert disease.payload["phenotype_match"]["score"] == 1.0


def test_nonpresent_and_uncertain_patient_statuses_are_preserved_not_scored(tmp_path):
    ontology = _provider(tmp_path)
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=[
            {"hpo_id": "HP:0000002", "phenotype_status": "ABSENT", "present": False},
            {"hpo_id": "HP:0000003", "phenotype_status": "EXCLUDED", "present": False},
            {"hpo_id": "HP:0000004", "phenotype_status": "UNKNOWN", "present": False},
            {"hpo_id": "HP:0000005", "phenotype_status": "NOT_ASSESSED", "present": False},
        ],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1", "disease": "Example disorder", "hpo_terms": ["HP:0000003"]
        }],
        hpo_ontology=ontology,
    )

    phenotype = next(record for record in records if record.evidence_type == "PHENOTYPE")
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert [item["hpo_id"] for item in phenotype.payload["negative_terms"]] == ["HP:0000002"]
    assert [item["hpo_id"] for item in phenotype.payload["excluded_terms"]] == ["HP:0000003"]
    assert [item["hpo_id"] for item in phenotype.payload["uncertain_terms"]] == ["HP:0000004"]
    assert [item["hpo_id"] for item in phenotype.payload["not_assessed_terms"]] == ["HP:0000005"]
    assert disease.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert "score" not in disease.payload["phenotype_match"]


def test_caller_supplied_ancestor_map_is_never_used_without_ontology(tmp_path):
    records = EvidenceEngine().build_case_context_evidence(
        variant_id=uuid4(),
        case_hpo_terms=["HP:0000002"],
        gene="GENE1",
        gene_disease_records=[{
            "gene": "GENE1",
            "disease": "Example disorder",
            "hpo_terms": ["HP:0000003"],
            "hpo_ancestor_map": {"HP:0000003": ["HP:0000002"]},
        }],
    )
    disease = next(record for record in records if record.evidence_type == "GENE_DISEASE")
    assert disease.payload["phenotype_match"]["status"] == "REQUIRES_REVIEW"
    assert disease.payload["phenotype_match"]["exact_overlap_score"] == 0.0
    assert disease.payload["phenotype_match"]["method"] == "EXACT_HPO_OVERLAP_UNVALIDATED"
    assert "score" not in disease.payload["phenotype_match"]
    assert "hpo_ancestor_map" not in disease.payload


def test_builtin_registry_exposes_executable_hpo_provider():
    registered = register_builtin_providers().require(
        provider_id="HPO", provider_version="2026-09-01"
    )

    assert registered.provider_version == "*"
    assert "PHENOTYPE" in {item.value for item in registered.descriptor.capabilities}


def test_hpo_capability_inference_matches_canonical_resource_type_and_local_adapter():
    provider = get_scientific_provider("HPO")

    assert ResourceCapability.PHENOTYPE in infer_capabilities(
        resource_type="PHENOTYPE_ONTOLOGY",
        provider="HPO",
    )
    assert provider.access_methods == ("LOCAL", "FILE", "LOCAL_ONLY")
