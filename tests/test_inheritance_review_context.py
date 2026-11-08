from __future__ import annotations

import pytest

from backend.app.domain.inheritance_review_context import (
    InheritanceReviewContextError,
    build_inheritance_review_context,
)


def _association():
    return {
        "gene": "GENE1",
        "disease_id": "MONDO:0000001",
        "molecular_mechanism": "loss_of_function",
        "inheritance_modes": ["AUTOSOMAL_RECESSIVE"],
        "penetrance": {"status": "UNKNOWN", "source": "NOT_RECORDED"},
        "resource_id": "gene-disease-resource",
        "resource_version": "2026-10",
        "resource_sha256": "a" * 64,
        "source_record_id": "GENE1:MONDO:0000001",
    }


def _matrix():
    return {
        "matrix_fingerprint": "b" * 64,
        "snapshot_id": "matrix-snapshot-1",
        "variant_ids": ["variant-1"],
        "provenance_completeness_status": "COMPLETE",
        "qualification_status": "PROVENANCE_PROJECTION_ONLY_NOT_CLINICALLY_QUALIFIED",
        "biological_relatedness_status": "NOT_ESTABLISHED",
        "callability_status": "NOT_ASSESSED; REQUIRES_LAB_QC_POLICY",
        "ploidy_status": "PROVENANCE_ONLY; LOCUS_SPECIFIC_POLICY_NOT_APPLIED",
        "samples": [
            {
                "member_id": "member-1",
                "member_identifier": "proband",
                "is_proband": True,
                "sex": "FEMALE",
                "affected_status": "AFFECTED",
                "binding_id": "binding-1",
                "binding_fingerprint": "c" * 64,
                "analysis_id": "analysis-1",
                "analysis_version": 1,
                "source_artifact_sha256": "d" * 64,
                "identity_interpretation": "CHAIN_OF_CUSTODY_AND_SAMPLE_IDENTITY_QC_ACCEPTED; BIOLOGICAL_RELATEDNESS_NOT_ESTABLISHED",
                "identity_evidence": {"status": "ACCEPTED"},
                "normalization_provenance_status": "COMPLETE",
                "ploidy_evidence_status": "NOT_ASSESSED",
                "ploidy_evidence": {"status": "NOT_ASSESSED"},
                "calls": [
                    {
                        "variant_id": "variant-1",
                        "call_state": "CALL_PRESENT",
                        "projected_genotype": "0/1",
                        "zygosity": "HET",
                        "phase": "UNSPECIFIED",
                        "phase_set": None,
                        "quality_metrics": {"DP": 30, "GQ": 60},
                        "source_record_sha256": "e" * 64,
                        "callability": "NOT_ASSESSED",
                        "quality_assessment_status": "NOT_ASSESSED_REQUIRES_LAB_QC_POLICY",
                    }
                ],
            }
        ],
        "relationships_as_recorded": [
            {
                "parent_member_identifier": "mother",
                "child_member_identifier": "proband",
                "relationship_type": "PARENT_CHILD",
                "relationship_status": "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
                "metadata": {},
            }
        ],
    }


def test_inheritance_context_preserves_source_and_exposes_every_unqualified_gate():
    result = build_inheritance_review_context(
        disease_association=_association(),
        family_matrix=_matrix(),
    )

    assert result["status"] == "REQUIRES_HUMAN_REVIEW"
    assert result["compatibility_conclusion"] is None
    assert result["segregation_conclusion"] is None
    assert result["de_novo_conclusion"] is None
    assert result["clinical_interpretation_performed"] is False
    assert result["clinical_qualification_status"] == "NOT_QUALIFIED_PENDING_INDEPENDENT_KNOWN_ANSWER_REVIEW"
    assert "BIOLOGICAL_RELATEDNESS_NOT_INDEPENDENTLY_ESTABLISHED" in result["evidence_gaps"]
    assert "LAB_APPROVED_CALLABILITY_POLICY_NOT_APPLIED" in result["evidence_gaps"]
    assert "DISEASE_PENETRANCE_NOT_ESTABLISHED" in result["evidence_gaps"]
    assert result["association_provenance"]["resource_version"] == "2026-10"
    assert result["family_matrix_fingerprint"] == "b" * 64
    assert len(result["review_context_fingerprint"]) == 64


def test_inheritance_context_requires_exactly_one_proband():
    matrix = _matrix()
    matrix["samples"].append({**matrix["samples"][0], "member_id": "member-2", "is_proband": True})
    with pytest.raises(InheritanceReviewContextError, match="Exactly one"):
        build_inheritance_review_context(disease_association=_association(), family_matrix=matrix)


def test_inheritance_context_rejects_collapsed_x_linked_mode():
    association = {**_association(), "inheritance_modes": ["X_LINKED"]}
    with pytest.raises(InheritanceReviewContextError, match="Unsupported disease inheritance modes"):
        build_inheritance_review_context(disease_association=association, family_matrix=_matrix())


def test_inheritance_context_requires_persisted_gene_disease_release_provenance():
    association = {**_association(), "resource_version": ""}
    with pytest.raises(InheritanceReviewContextError, match="resource_version"):
        build_inheritance_review_context(disease_association=association, family_matrix=_matrix())


def test_inheritance_context_rejects_invalid_call_state():
    matrix = _matrix()
    matrix["samples"][0]["calls"][0]["call_state"] = "REFERENCE_ASSUMED"
    with pytest.raises(InheritanceReviewContextError, match="Unsupported family genotype call state"):
        build_inheritance_review_context(disease_association=_association(), family_matrix=matrix)


@pytest.mark.parametrize(
    ("source_label", "expected"),
    [
        ("Autosomal dominant inheritance", "AUTOSOMAL_DOMINANT"),
        ("Autosomal Dominant (AD)", "AUTOSOMAL_DOMINANT"),
        ("Autosomal recessive inheritance", "AUTOSOMAL_RECESSIVE"),
        ("Autosomal Recessive (AR)", "AUTOSOMAL_RECESSIVE"),
        ("X-linked dominant inheritance", "X_LINKED_DOMINANT"),
        ("X-linked recessive inheritance", "X_LINKED_RECESSIVE"),
        ("Mitochondrial inheritance", "MITOCHONDRIAL"),
        ("Y-linked inheritance", "Y_LINKED"),
        ("Autosomal semidominant inheritance", "AUTOSOMAL_SEMIDOMINANT"),
        ("Semidominant", "AUTOSOMAL_SEMIDOMINANT"),
        ("X-linked inheritance", None),
        ("", None),
    ],
)
def test_clingen_moi_mapping_requires_explicit_dominant_recessive_distinction(source_label, expected):
    from backend.app.domain.inheritance_review_context import normalize_clingen_moi_label

    assert normalize_clingen_moi_label(source_label) == expected
