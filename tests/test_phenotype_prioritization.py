from __future__ import annotations

from dataclasses import dataclass

import pytest

from backend.app.domain.phenotype_prioritization import (
    PhenotypePrioritizationError,
    prioritize_disease_context,
)


class Ontology:
    release = "2026-09-01"
    sha256 = "a" * 64

    def ancestors(self, term_id):
        return {
            "HP:0000003": {"HP:0000001", "HP:0000002"},
            "HP:0000004": {"HP:0000001"},
        }.get(term_id, set())


@dataclass(frozen=True)
class Hpoa:
    hpo_id: str
    qualifier: str = ""
    aspect: str = "P"
    frequency: str | None = None
    onset: str | None = None
    sex: str | None = None
    evidence: str = "PCS"
    reference: str = "PMID:123"
    biocuration: tuple[str, ...] = ("HPO:curator[2026-01-01]",)


def _association(gene="GENE1", disease_id="MONDO:0000001", record_id="GENE1:MONDO:1"):
    return {
        "gene": gene,
        "disease_id": disease_id,
        "disease_name": "Example disorder",
        "validity_status": "STRONG",
        "molecular_mechanism": "loss_of_function",
        "inheritance_modes": ["AUTOSOMAL_RECESSIVE"],
        "penetrance": {"status": "UNKNOWN", "source": "NOT_RECORDED"},
        "resource_id": "00000000-0000-0000-0000-000000000001",
        "resource_version": "2026-10",
        "resource_sha256": "b" * 64,
        "source_record_id": record_id,
    }


def test_context_order_uses_only_present_proband_terms_and_preserves_provenance():
    result = prioritize_disease_context(
        patient_observations=[
            {"id": "p1", "canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT"},
            {"id": "p2", "canonical_hpo_id": "HP:0000004", "phenotype_status": "PRESENT"},
            {"id": "f1", "canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT", "subject_member_id": "sibling"},
            {"id": "a1", "canonical_hpo_id": "HP:0000002", "phenotype_status": "ABSENT"},
            {"id": "u1", "canonical_hpo_id": "HP:0000001", "phenotype_status": "UNKNOWN"},
        ],
        gene_disease_records=[_association()],
        hpoa_provenance={"resource_id": "00000000-0000-0000-0000-000000000002", "resource_version": "2026-09-02", "resource_sha256": "f" * 64},
        annotations_by_disease={
            "mondo:0000001": [
                Hpoa("HP:0000001", frequency="1/2"),
                Hpoa("HP:0000002", qualifier="NOT", frequency="0/3"),
            ]
        },
        hpo_ontology=Ontology(),
    )

    candidate = result["candidates"][0]
    assert candidate["contextual_order"] == 1
    assert candidate["matched_patient_term_count"] == 2
    assert {item["patient_hpo_id"] for item in candidate["matched_terms"]} == {
        "HP:0000003", "HP:0000004"
    }
    assert candidate["potential_discordances"][0]["hpoa_frequency"] == "0/3"
    assert result["non_matching_phenotype_states"][0]["status"] in {"ABSENT", "UNKNOWN"}
    assert result["clinical_prioritization_validated"] is False
    assert candidate["inheritance"]["modes"] == ["AUTOSOMAL_RECESSIVE"]
    assert candidate["inheritance"]["penetrance"]["status"] == "UNKNOWN"
    assert candidate["association_provenance"]["resource_version"] == "2026-10"


def test_context_order_is_deterministic_for_equal_match_counts():
    result = prioritize_disease_context(
        patient_observations=[
            {"canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT"},
        ],
        gene_disease_records=[
            _association("GENE2", "MONDO:0000002", "r2"),
            _association("GENE1", "MONDO:0000001", "r1"),
        ],
        hpoa_provenance={"resource_id": "00000000-0000-0000-0000-000000000002", "resource_version": "2026-09-02", "resource_sha256": "f" * 64},
        annotations_by_disease={
            "mondo:0000001": [Hpoa("HP:0000001")],
            "mondo:0000002": [Hpoa("HP:0000001")],
        },
        hpo_ontology=Ontology(),
    )

    assert [(item["gene"], item["contextual_order"]) for item in result["candidates"]] == [
        ("GENE1", 1), ("GENE2", 2)
    ]


@pytest.mark.parametrize(
    ("association", "message"),
    [
        ({**_association(), "resource_version": ""}, "resource_version"),
        ({**_association(), "inheritance_modes": []}, "inheritance_modes"),
        ({**_association(), "penetrance": None}, "penetrance"),
    ],
)
def test_context_order_fails_closed_without_governed_association_contract(association, message):
    with pytest.raises(PhenotypePrioritizationError, match=message):
        prioritize_disease_context(
            patient_observations=[],
            gene_disease_records=[association],
            annotations_by_disease={"mondo:0000001": [Hpoa("HP:0000001")]},
            hpoa_provenance={"resource_id": "00000000-0000-0000-0000-000000000002", "resource_version": "2026-09-02", "resource_sha256": "f" * 64},
            hpo_ontology=Ontology(),
        )


def test_no_exact_disease_identifier_crosswalk_is_inferred():
    result = prioritize_disease_context(
        patient_observations=[{"canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT"}],
        gene_disease_records=[_association(disease_id="MONDO:0000001")],
        annotations_by_disease={"orpha:123": [Hpoa("HP:0000001")]},
        hpoa_provenance={"resource_id": "00000000-0000-0000-0000-000000000002", "resource_version": "2026-09-02", "resource_sha256": "f" * 64},
        hpo_ontology=Ontology(),
    )
    assert result["candidates"] == []


def test_snapshot_proband_member_id_is_included_but_sibling_id_is_excluded():
    result = prioritize_disease_context(
        patient_observations=[
            {
                "id": "proband-observation",
                "hpo_id": "HP:0000003",
                "phenotype_status": "PRESENT",
                "subject_member_id": "member-proband",
            },
            {
                "id": "sibling-observation",
                "hpo_id": "HP:0000004",
                "phenotype_status": "PRESENT",
                "subject_member_id": "member-sibling",
            },
        ],
        proband_member_ids=["member-proband"],
        gene_disease_records=[_association()],
        annotations_by_disease={"mondo:0000001": [Hpoa("HP:0000001")]},
        hpoa_provenance={
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": "2026-09-02",
            "resource_sha256": "f" * 64,
        },
        hpo_ontology=Ontology(),
    )
    assert result["observed_proband_present_terms"] == ["HP:0000003"]
    assert result["candidates"][0]["matched_terms"][0]["patient_observation_ids"] == [
        "proband-observation"
    ]


def test_candidate_keeps_clingen_validity_and_penetrance_provenance_distinct_from_g2p():
    association = {
        **_association(),
        "validity_status": "Definitive",
        "g2p_confidence": "definitive",
        "validity_provenance": {
            "resource_id": "00000000-0000-0000-0000-000000000003",
            "resource_name": "ClinGen Gene-Disease Validity",
            "resource_version": "GeneValidity",
            "resource_sha256": "c" * 64,
            "source": "CLINGEN_GENE_DISEASE_VALIDITY",
            "matched_assertion_count": 1,
        },
        "inheritance_mode_sources": {
            "g2p_allelic_requirement": "biallelic_autosomal",
            "clingen_moi_assertions": ["Autosomal recessive inheritance"],
        },
        "inheritance_mode_conflict": False,
    }
    result = prioritize_disease_context(
        patient_observations=[{"canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT"}],
        gene_disease_records=[association],
        annotations_by_disease={"mondo:0000001": [Hpoa("HP:0000001")]},
        hpoa_provenance={
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": "2026-09-02",
            "resource_sha256": "f" * 64,
        },
        hpo_ontology=Ontology(),
    )
    candidate = result["candidates"][0]
    assert candidate["association_validity"] == "Definitive"
    assert candidate["g2p_confidence"] == "definitive"
    assert candidate["association_validity_provenance"]["source"] == "CLINGEN_GENE_DISEASE_VALIDITY"
    assert candidate["inheritance"]["mode_sources"]["g2p_allelic_requirement"] == "biallelic_autosomal"
    assert candidate["inheritance"]["penetrance_provenance"]["source"] == "NOT_PROVIDED_BY_G2P_OR_CLINGEN_GDV"
    assert candidate["inheritance"]["qualification_status"] == "REQUIRES_INDEPENDENT_QUALIFICATION"


def test_disputed_or_refuted_source_assertions_do_not_rank_ahead_of_supported_context():
    supported = {
        **_association("GENE2", "MONDO:0000002", "supported"),
        "g2p_confidence": "strong",
        "validity_status": "Definitive",
    }
    conflicting = {
        **_association("GENE1", "MONDO:0000001", "refuted"),
        "g2p_confidence": "refuted",
        "validity_status": "Definitive",
    }
    result = prioritize_disease_context(
        patient_observations=[{"canonical_hpo_id": "HP:0000003", "phenotype_status": "PRESENT"}],
        gene_disease_records=[conflicting, supported],
        annotations_by_disease={
            "mondo:0000001": [Hpoa("HP:0000001"), Hpoa("HP:0000002")],
            "mondo:0000002": [Hpoa("HP:0000001")],
        },
        hpoa_provenance={
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": "2026-09-02",
            "resource_sha256": "f" * 64,
        },
        hpo_ontology=Ontology(),
    )
    assert result["candidates"][0]["gene"] == "GENE2"
    assert result["candidates"][0]["association_evidence_state"] == "SUPPORTED_SOURCE_CONTEXT_ONLY"
    assert result["candidates"][1]["gene"] == "GENE1"
    assert result["candidates"][1]["association_evidence_state"] == "CONFLICTING_OR_REFUTED_REQUIRES_REVIEW"


def test_no_known_disease_relationship_is_not_mislabelled_as_refuted():
    association = {
        **_association(),
        "validity_status": "No Known Disease Relationship",
        "g2p_confidence": None,
    }
    result = prioritize_disease_context(
        patient_observations=[],
        gene_disease_records=[association],
        annotations_by_disease={"mondo:0000001": [Hpoa("HP:0000001")]},
        hpoa_provenance={
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": "2026-09-02",
            "resource_sha256": "f" * 64,
        },
        hpo_ontology=Ontology(),
    )
    assert result["candidates"][0]["association_evidence_state"] == "NO_KNOWN_DISEASE_RELATIONSHIP_REQUIRES_REVIEW"



def test_unmapped_or_incomplete_inheritance_comparison_is_not_coerced_to_no_conflict():
    association = {
        **_association(),
        "inheritance_mode_conflict": None,
        "inheritance_mode_sources": {
            "g2p_allelic_requirement": "biallelic_autosomal",
            "clingen_moi_assertions": ["XL"],
            "comparison_status": "UNMAPPED",
        },
    }
    result = prioritize_disease_context(
        patient_observations=[],
        gene_disease_records=[association],
        annotations_by_disease={"mondo:0000001": [Hpoa("HP:0000001")]},
        hpoa_provenance={
            "resource_id": "00000000-0000-0000-0000-000000000002",
            "resource_version": "2026-09-02",
            "resource_sha256": "f" * 64,
        },
        hpo_ontology=Ontology(),
    )
    inheritance = result["candidates"][0]["inheritance"]
    assert inheritance["mode_conflict"] is None
    assert inheritance["qualification_status"] == (
        "REQUIRES_REVIEW_FOR_UNMAPPED_OR_INCOMPLETE_SOURCE_EVIDENCE"
    )
