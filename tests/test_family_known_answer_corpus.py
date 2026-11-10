from __future__ import annotations

import hashlib
import json

import pytest

from scripts.family_known_answer_corpus import (
    ALLOWED_TEST_ROLES,
    REQUIRED_CATEGORIES,
    SCHEMA,
    CorpusValidationError,
    validate_corpus,
)


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _case(tmp_path, case_id, category, test_role):
    artifacts = []
    for role in ("SOURCE_VCF", "NORMALIZED_VCF", "PEDIGREE", "PHENOTYPE"):
        relative = f"{case_id}/{role.lower()}.txt"
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"{case_id}:{role}".encode()
        path.write_bytes(payload)
        artifacts.append({
            "role": role,
            "path": relative,
            "sha256": _sha(payload),
            "size_bytes": len(payload),
        })
    expected = {
        "inheritance_review_state": "REQUIRES_HUMAN_REVIEW",
        "phase_state": "UNRESOLVED",
        "de_novo_evidence_state": "INSUFFICIENT_EVIDENCE",
        "clinical_conclusion": False,
    }
    expected_sha = hashlib.sha256(
        json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    reviewers = [
        {
            "reviewer_id": f"reviewer-{case_id}-1",
            "qualification_category": "CLINICAL_MOLECULAR_GENETICS",
            "reviewed_at": "2026-11-10",
            "review_scope": "FAMILY_GENOTYPE_AND_EXPECTED_EVIDENCE_STATE",
            "decision": "APPROVED",
            "independence_attested": True,
            "implementation_independence_attested": True,
            "conflict_of_interest_checked": True,
            "expected_outcome_sha256": expected_sha,
            "attestation_sha256": "a" * 64,
        },
        {
            "reviewer_id": f"reviewer-{case_id}-2",
            "qualification_category": "CLINICAL_GENETICS",
            "reviewed_at": "2026-11-10",
            "review_scope": "FAMILY_GENOTYPE_AND_EXPECTED_EVIDENCE_STATE",
            "decision": "APPROVED",
            "independence_attested": True,
            "implementation_independence_attested": True,
            "conflict_of_interest_checked": True,
            "expected_outcome_sha256": expected_sha,
            "attestation_sha256": "b" * 64,
        },
    ]
    return {
        "case_id": case_id,
        "qualification_status": "QUALIFIED",
        "categories": [category],
        "test_role": test_role,
        "case_author_id": f"author-{case_id}",
        "source": {
            "dataset_accession": "SYNTHETIC-TEST-ONLY",
            "publication_url": "https://example.invalid/synthetic-test-only",
            "license_or_terms": "SYNTHETIC_NO_PATIENT_DATA",
            "attribution": "Synthetic validator test data; not a clinical known-answer case",
            "data_use_permission_reference": "TEST_FIXTURE_ONLY",
            "source_snapshot_sha256": "c" * 64,
            "access_status": "APPROVED",
            "redistribution_status": "PERMITTED",
        },
        "artifacts": artifacts,
        "evidence": {
            "reference_assembly": "GRCh38",
            "hgnc_resource_release": "2026-10-06",
            "gene_hgnc_id": "HGNC:1234",
            "disease_mondo_id": "MONDO:0000001",
            "gene_disease_resource_id": "test-resource",
            "gene_disease_resource_version": "test-release",
            "gene_disease_source_record_id": "test-record",
            "inheritance_mode": "AUTOSOMAL_RECESSIVE",
            "molecular_mechanism": "loss_of_function",
            "penetrance_status": "UNKNOWN",
            "callability_policy_id": "NOT_ASSESSED_TEST_ONLY",
            "ploidy_policy_id": "NOT_APPLICABLE_TEST_ONLY",
            "sample_identity_status": "NOT_CLINICALLY_QUALIFIED_TEST_ONLY",
            "family_relationship_status": "NOT_CLINICALLY_QUALIFIED_TEST_ONLY",
            "family_members": [
                {"member_id": "member-proband", "sample_name": "SYNTHETIC_PROBAND", "role": "PROBAND", "identity_status": "TEST_ONLY"},
                {"member_id": "member-parent", "sample_name": "SYNTHETIC_PARENT", "role": "MOTHER", "identity_status": "TEST_ONLY"},
            ],
            "relationships": [
                {
                    "parent_member_id": "member-parent",
                    "child_member_id": "member-proband",
                    "relationship_type": "PARENT_CHILD",
                    "relationship_status": "TEST_ONLY_NOT_VERIFIED",
                }
            ],
            "variants": [
                {
                    "variant_id": "synthetic-variant-1",
                    "phase_state": "UNRESOLVED",
                    "callability_state": "NOT_ASSESSED",
                    "quality_state": "NOT_ASSESSED",
                }
            ],
        },
        "expected_outcome": expected,
        "reviewers": reviewers,
    }


def _manifest(tmp_path):
    cases = []
    index = 0
    for category in sorted(REQUIRED_CATEGORIES):
        for role in sorted(ALLOWED_TEST_ROLES):
            index += 1
            cases.append(_case(tmp_path, f"TEST-{index:03d}", category, role))
    return {
        "schema": SCHEMA,
        "implementation_author_ids": ["implementation-author"],
        "cases": cases,
    }


def test_corpus_validator_accepts_complete_reviewed_structure_without_claiming_clinical_truth(tmp_path):
    report = validate_corpus(_manifest(tmp_path), tmp_path)

    assert report["status"] == "QUALIFIED"
    assert report["case_count"] == len(REQUIRED_CATEGORIES) * len(ALLOWED_TEST_ROLES)
    assert report["clinical_conclusions_performed"] is False
    assert set(report["category_coverage"]) == set(REQUIRED_CATEGORIES)


def test_corpus_validator_blocks_missing_known_answer_or_control_coverage(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"].pop()

    report = validate_corpus(manifest, tmp_path)

    assert report["status"] == "BLOCKED_INCOMPLETE_COVERAGE"
    assert report["missing_coverage"]


def test_corpus_validator_rejects_duplicate_or_non_independent_reviewers(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["reviewers"][1]["reviewer_id"] = manifest["cases"][0]["reviewers"][0]["reviewer_id"]

    with pytest.raises(CorpusValidationError, match="reviewer IDs must be distinct"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_implementation_author_as_reviewer(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["reviewers"][0]["reviewer_id"] = "implementation-author"

    with pytest.raises(CorpusValidationError, match="implementation authors"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_reviewer_who_authored_case(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["reviewers"][0]["reviewer_id"] = manifest["cases"][0]["case_author_id"]

    with pytest.raises(CorpusValidationError, match="case or implementation authors"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_artifact_hash_drift(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["artifacts"][0]["sha256"] = "0" * 64

    with pytest.raises(CorpusValidationError, match="SHA-256 mismatch"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_path_traversal(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["artifacts"][0]["path"] = "../outside.vcf"

    with pytest.raises(CorpusValidationError, match="escapes"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_unapproved_source_access(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["source"]["access_status"] = "PENDING"

    with pytest.raises(CorpusValidationError, match="not APPROVED"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_rejects_clinical_conclusion_in_expected_answer(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["expected_outcome"]["clinical_conclusion"] = True

    with pytest.raises(CorpusValidationError, match="cannot assert clinical conclusions"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_requires_reviewer_signoff_for_exact_expected_outcome(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["reviewers"][0]["expected_outcome_sha256"] = "0" * 64

    with pytest.raises(CorpusValidationError, match="did not approve the current expected outcome"):
        validate_corpus(manifest, tmp_path)
