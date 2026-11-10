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
    for role in ("SOURCE_MANIFEST", "SOURCE_VCF", "NORMALIZED_VCF", "PEDIGREE", "PHENOTYPE"):
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
        "supporting_evidence": ["synthetic fixture evidence"],
        "blocking_evidence": ["clinical qualification not performed"],
    }
    expected_sha = hashlib.sha256(
        json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    source_vcf_sha256 = next(item["sha256"] for item in artifacts if item["role"] == "SOURCE_VCF")
    reviewers = [
        {
            "reviewer_id": f"reviewer-{case_id}-1",
            "qualification_category": "CLINICAL_MOLECULAR_GENETICS",
            "reviewed_at": "2026-11-10",
            "review_scope": "FAMILY_GENOTYPE_AND_EXPECTED_EVIDENCE_STATE",
            "rationale": "Synthetic validator test only",
            "attestation_reference": "TEST_ONLY_ATTESTATION",
            "source_material_reviewed": True,
            "rationale": "Synthetic validator test only",
            "attestation_reference": "TEST_ONLY_ATTESTATION",
            "source_material_reviewed": True,
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
            "rationale": "Synthetic validator test only",
            "attestation_reference": "TEST_ONLY_ATTESTATION",
            "source_material_reviewed": True,
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
            "source_snapshot_sha256": artifacts[0]["sha256"],
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
                {"member_id": "member-proband", "sample_name": "SYNTHETIC_PROBAND", "role": "PROBAND", "identity_status": "TEST_ONLY", "is_proband": True, "source_artifact_sha256": source_vcf_sha256, "binding_id": "binding-proband", "binding_fingerprint": "e" * 64, "analysis_id": "analysis-proband"},
                {"member_id": "member-parent", "sample_name": "SYNTHETIC_PARENT", "role": "MOTHER", "identity_status": "TEST_ONLY", "is_proband": False, "source_artifact_sha256": source_vcf_sha256, "binding_id": "binding-parent", "binding_fingerprint": "f" * 64, "analysis_id": "analysis-parent"},
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
                    "source_record_sha256": "d" * 64,
                    "genotypes": [
                        {"member_id": "member-proband", "call_state": "CALL_PRESENT", "genotype": "0/1", "callability_state": "NOT_ASSESSED", "quality_state": "NOT_ASSESSED"},
                        {"member_id": "member-parent", "call_state": "NO_RECORD", "genotype": None, "callability_state": "NOT_ASSESSED", "quality_state": "NOT_ASSESSED"},
                    ],
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


def test_corpus_validator_allows_reused_sample_names_across_distinct_source_vcfs(tmp_path):
    manifest = _manifest(tmp_path)
    case = manifest["cases"][0]
    payload = b"separate source VCF for parent"
    parent_vcf = tmp_path / case["case_id"] / "parent-source.vcf"
    parent_vcf.write_bytes(payload)
    parent_sha = _sha(payload)
    case["artifacts"].append({
        "role": "SOURCE_VCF",
        "path": f'{case["case_id"]}/parent-source.vcf',
        "sha256": parent_sha,
        "size_bytes": len(payload),
    })
    parent = case["evidence"]["family_members"][1]
    parent["sample_name"] = case["evidence"]["family_members"][0]["sample_name"]
    parent["source_artifact_sha256"] = parent_sha

    report = validate_corpus(manifest, tmp_path)

    assert report["status"] == "QUALIFIED"


def test_corpus_validator_rejects_source_snapshot_hash_not_bound_to_manifest_artifact(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["source"]["source_snapshot_sha256"] = "0" * 64

    with pytest.raises(CorpusValidationError, match="does not match the preserved source manifest"):
        validate_corpus(manifest, tmp_path)


def test_corpus_validator_never_treats_no_record_as_reference_genotype(tmp_path):
    manifest = _manifest(tmp_path)
    manifest["cases"][0]["evidence"]["variants"][0]["genotypes"][1]["genotype"] = "0|0"

    with pytest.raises(CorpusValidationError, match="must remain null, not reference"):
        validate_corpus(manifest, tmp_path)
