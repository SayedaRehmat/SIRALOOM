"""Validate the source, evidence, review, and coverage gates for C1.3.

This is a qualification utility, not a runtime inheritance engine. It never
computes clinical inheritance conclusions. Only independently reviewed,
source-pinned cases may count toward the C1.3 corpus gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "siraloom.family-known-answer-corpus.v1"
REQUIRED_CATEGORIES = frozenset({
    "AR_HOMOZYGOUS",
    "COMPOUND_HET_TRANS",
    "COMPOUND_HET_CIS",
    "COMPOUND_HET_UNRESOLVED",
    "AUTOSOMAL_DOMINANT",
    "X_LINKED_RECESSIVE",
    "X_LINKED_DOMINANT",
    "DE_NOVO",
    "INCOMPLETE_PENETRANCE",
    "SEX_CHROMOSOME_PLOIDY",
    "MISSING_LOW_QUALITY_GENOTYPES",
    "UNCERTAIN_FAMILY_RELATIONSHIPS",
})
ALLOWED_TEST_ROLES = frozenset({"KNOWN_ANSWER", "ADVERSARIAL_CONTROL"})
ALLOWED_REVIEW_STATES = frozenset({
    "SUPPORTED_FOR_REVIEW",
    "INCONSISTENT",
    "INSUFFICIENT_DATA",
    "CONFLICTING_EVIDENCE",
    "UNSUPPORTED_MODEL",
    "REQUIRES_HUMAN_REVIEW",
})
ALLOWED_PHASE_STATES = frozenset({"TRANS", "CIS", "UNRESOLVED", "NOT_APPLICABLE"})
ALLOWED_DE_NOVO_STATES = frozenset({
    "TECHNICALLY_SUPPORTED",
    "NOT_SUPPORTED",
    "INSUFFICIENT_EVIDENCE",
    "NOT_APPLICABLE",
})
REQUIRED_ARTIFACT_ROLES = frozenset({
    "SOURCE_MANIFEST",
    "SOURCE_VCF",
    "NORMALIZED_VCF",
    "PEDIGREE",
    "PHENOTYPE",
})
REQUIRED_EVIDENCE_FIELDS = (
    "reference_assembly",
    "hgnc_resource_release",
    "gene_hgnc_id",
    "disease_mondo_id",
    "gene_disease_resource_id",
    "gene_disease_resource_version",
    "gene_disease_source_record_id",
    "inheritance_mode",
    "molecular_mechanism",
    "penetrance_status",
    "callability_policy_id",
    "ploidy_policy_id",
    "sample_identity_status",
    "family_relationship_status",
)


class CorpusValidationError(ValueError):
    """The C1.3 corpus manifest is structurally invalid."""


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.lower())
    )


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusValidationError(f"Required non-empty text is missing: {field}")
    return value.strip()


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _artifact_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root):
        raise CorpusValidationError("Artifact path escapes the configured artifact root")
    return candidate


def _validate_source(case: dict[str, Any], case_id: str) -> None:
    source = case.get("source")
    if not isinstance(source, dict):
        raise CorpusValidationError(f"{case_id}: source must be an object")
    _required_text(source.get("dataset_accession"), f"{case_id}.source.dataset_accession")
    _required_text(source.get("publication_url"), f"{case_id}.source.publication_url")
    _required_text(source.get("license_or_terms"), f"{case_id}.source.license_or_terms")
    _required_text(source.get("attribution"), f"{case_id}.source.attribution")
    _required_text(source.get("data_use_permission_reference"), f"{case_id}.source.data_use_permission_reference")
    if not _is_sha256(source.get("source_snapshot_sha256")):
        raise CorpusValidationError(f"{case_id}: source_snapshot_sha256 must be SHA-256")
    if source.get("access_status") != "APPROVED":
        raise CorpusValidationError(f"{case_id}: source access status is not APPROVED")
    if source.get("redistribution_status") not in {
        "PERMITTED",
        "RESTRICTED_ARTIFACTS_EXTERNAL",
    }:
        raise CorpusValidationError(f"{case_id}: redistribution permission is not explicit")


def _validate_artifacts(case: dict[str, Any], case_id: str, root: Path) -> None:
    artifacts = case.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise CorpusValidationError(f"{case_id}: artifacts must be a non-empty list")
    observed_roles: set[str] = set()
    observed_paths: set[str] = set()
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            raise CorpusValidationError(f"{case_id}: artifact {index} must be an object")
        role = _required_text(artifact.get("role"), f"{case_id}.artifacts[{index}].role")
        relative_path = _required_text(
            artifact.get("path"), f"{case_id}.artifacts[{index}].path"
        )
        digest = artifact.get("sha256")
        if not _is_sha256(digest):
            raise CorpusValidationError(f"{case_id}: artifact {role} has an invalid SHA-256")
        if relative_path in observed_paths:
            raise CorpusValidationError(f"{case_id}: duplicate artifact path {relative_path}")
        observed_paths.add(relative_path)
        observed_roles.add(role)
        artifact_path = _artifact_path(root, relative_path)
        if not artifact_path.is_file():
            raise CorpusValidationError(f"{case_id}: artifact is missing: {relative_path}")
        actual_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_digest != digest.lower():
            raise CorpusValidationError(f"{case_id}: artifact SHA-256 mismatch: {relative_path}")
        size_bytes = artifact.get("size_bytes")
        if not isinstance(size_bytes, int) or size_bytes < 1:
            raise CorpusValidationError(f"{case_id}: artifact size_bytes must be positive")
        if artifact_path.stat().st_size != size_bytes:
            raise CorpusValidationError(f"{case_id}: artifact size mismatch: {relative_path}")
    missing_roles = sorted(REQUIRED_ARTIFACT_ROLES - observed_roles)
    if missing_roles:
        raise CorpusValidationError(
            f"{case_id}: required evidence artifacts are missing: {', '.join(missing_roles)}"
        )


def _validate_evidence(case: dict[str, Any], case_id: str) -> None:
    evidence = case.get("evidence")
    if not isinstance(evidence, dict):
        raise CorpusValidationError(f"{case_id}: evidence must be an object")
    for field in REQUIRED_EVIDENCE_FIELDS:
        _required_text(evidence.get(field), f"{case_id}.evidence.{field}")
    if evidence.get("reference_assembly") not in {"GRCh37", "GRCh38"}:
        raise CorpusValidationError(f"{case_id}: unsupported or missing reference assembly")
    if not str(evidence.get("gene_hgnc_id", "")).startswith("HGNC:"):
        raise CorpusValidationError(f"{case_id}: gene_hgnc_id must be a canonical HGNC identifier")
    if not str(evidence.get("disease_mondo_id", "")).startswith("MONDO:"):
        raise CorpusValidationError(f"{case_id}: disease_mondo_id must be a canonical MONDO identifier")
    family_members = evidence.get("family_members")
    relationships = evidence.get("relationships")
    variants = evidence.get("variants")
    if not isinstance(family_members, list) or len(family_members) < 2:
        raise CorpusValidationError(f"{case_id}: at least two family members are required")
    if not isinstance(relationships, list) or not relationships:
        raise CorpusValidationError(f"{case_id}: recorded family relationships are required")
    if not isinstance(variants, list) or not variants:
        raise CorpusValidationError(f"{case_id}: at least one variant evidence record is required")
    member_ids = set()
    sample_names = set()
    proband_count = 0
    for member in family_members:
        if not isinstance(member, dict):
            raise CorpusValidationError(f"{case_id}: family member entries must be objects")
        member_id = _required_text(member.get("member_id"), f"{case_id}.family_member.member_id")
        if member_id in member_ids:
            raise CorpusValidationError(f"{case_id}: duplicate family member ID {member_id}")
        member_ids.add(member_id)
        sample_name = _required_text(member.get("sample_name"), f"{case_id}.family_member.sample_name")
        if sample_name in sample_names:
            raise CorpusValidationError(f"{case_id}: duplicate VCF sample name {sample_name}")
        sample_names.add(sample_name)
        _required_text(member.get("role"), f"{case_id}.family_member.role")
        if not isinstance(member.get("is_proband"), bool):
            raise CorpusValidationError(f"{case_id}: family member is_proband must be explicit boolean")
        proband_count += int(member["is_proband"])
        _required_text(member.get("identity_status"), f"{case_id}.family_member.identity_status")
    if proband_count != 1:
        raise CorpusValidationError(f"{case_id}: exactly one family proband is required")
    for relationship in relationships:
        if not isinstance(relationship, dict):
            raise CorpusValidationError(f"{case_id}: relationship entries must be objects")
        parent = _required_text(relationship.get("parent_member_id"), f"{case_id}.relationship.parent_member_id")
        child = _required_text(relationship.get("child_member_id"), f"{case_id}.relationship.child_member_id")
        _required_text(relationship.get("relationship_type"), f"{case_id}.relationship.relationship_type")
        _required_text(relationship.get("relationship_status"), f"{case_id}.relationship.relationship_status")
        if parent not in member_ids or child not in member_ids:
            raise CorpusValidationError(f"{case_id}: relationship references an unknown family member")
    for variant in variants:
        if not isinstance(variant, dict):
            raise CorpusValidationError(f"{case_id}: variant entries must be objects")
        _required_text(variant.get("variant_id"), f"{case_id}.variant.variant_id")
        _required_text(variant.get("phase_state"), f"{case_id}.variant.phase_state")
        _required_text(variant.get("callability_state"), f"{case_id}.variant.callability_state")
        _required_text(variant.get("quality_state"), f"{case_id}.variant.quality_state")
        if not _is_sha256(variant.get("source_record_sha256")):
            raise CorpusValidationError(f"{case_id}: variant source_record_sha256 must be SHA-256")
        genotypes = variant.get("genotypes")
        if not isinstance(genotypes, list) or len(genotypes) != len(member_ids):
            raise CorpusValidationError(f"{case_id}: each variant requires one genotype state per family member")
        genotype_members = set()
        for genotype in genotypes:
            if not isinstance(genotype, dict):
                raise CorpusValidationError(f"{case_id}: genotype entries must be objects")
            member_id = _required_text(genotype.get("member_id"), f"{case_id}.genotype.member_id")
            if member_id not in member_ids or member_id in genotype_members:
                raise CorpusValidationError(f"{case_id}: genotype member mapping is missing, duplicated, or unknown")
            genotype_members.add(member_id)
            call_state = _required_text(genotype.get("call_state"), f"{case_id}.genotype.call_state")
            if call_state not in {"NO_RECORD", "GENOTYPE_UNAVAILABLE", "NO_CALL", "PARTIAL_NO_CALL", "CALL_PRESENT", "OTHER_ALT_PRESENT", "OTHER_ALT_AND_MISSING", "INVALID_CALL"}:
                raise CorpusValidationError(f"{case_id}: unsupported family genotype call state {call_state}")
            if call_state in {"NO_RECORD", "GENOTYPE_UNAVAILABLE", "NO_CALL", "PARTIAL_NO_CALL"} and genotype.get("genotype") == "0/0":
                raise CorpusValidationError(f"{case_id}: missing/no-record calls cannot be imputed as reference")
            _required_text(genotype.get("callability_state"), f"{case_id}.genotype.callability_state")
            _required_text(genotype.get("quality_state"), f"{case_id}.genotype.quality_state")


def _validate_expected(case: dict[str, Any], case_id: str) -> str:
    expected = case.get("expected_outcome")
    if not isinstance(expected, dict):
        raise CorpusValidationError(f"{case_id}: expected_outcome must be an object")
    review_state = _required_text(
        expected.get("inheritance_review_state"),
        f"{case_id}.expected_outcome.inheritance_review_state",
    )
    phase_state = _required_text(expected.get("phase_state"), f"{case_id}.expected_outcome.phase_state")
    de_novo_state = _required_text(
        expected.get("de_novo_evidence_state"),
        f"{case_id}.expected_outcome.de_novo_evidence_state",
    )
    if review_state not in ALLOWED_REVIEW_STATES:
        raise CorpusValidationError(f"{case_id}: unsupported inheritance review state")
    if phase_state not in ALLOWED_PHASE_STATES:
        raise CorpusValidationError(f"{case_id}: unsupported phase state")
    if de_novo_state not in ALLOWED_DE_NOVO_STATES:
        raise CorpusValidationError(f"{case_id}: unsupported de novo evidence state")
    if expected.get("clinical_conclusion") is not False:
        raise CorpusValidationError(f"{case_id}: corpus expected outcomes cannot assert clinical conclusions")
    if not isinstance(expected.get("supporting_evidence"), list) or not expected["supporting_evidence"]:
        raise CorpusValidationError(f"{case_id}: expected supporting_evidence must be a non-empty list")
    if not isinstance(expected.get("blocking_evidence"), list) or not expected["blocking_evidence"]:
        raise CorpusValidationError(f"{case_id}: expected blocking_evidence must be a non-empty list")
    return _canonical_sha256(expected)


def _validate_reviewers(
    case: dict[str, Any],
    case_id: str,
    expected_sha256: str,
    implementation_author_ids: set[str],
) -> None:
    reviewers = case.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) < 2:
        raise CorpusValidationError(f"{case_id}: at least two independent reviewers are required")
    reviewer_ids: set[str] = set()
    case_author_id = _required_text(case.get("case_author_id"), f"{case_id}.case_author_id")
    for reviewer in reviewers:
        if not isinstance(reviewer, dict):
            raise CorpusValidationError(f"{case_id}: reviewer entries must be objects")
        reviewer_id = _required_text(reviewer.get("reviewer_id"), f"{case_id}.reviewer_id")
        if reviewer_id in reviewer_ids:
            raise CorpusValidationError(f"{case_id}: reviewer IDs must be distinct")
        reviewer_ids.add(reviewer_id)
        if reviewer_id == case_author_id or reviewer_id in implementation_author_ids:
            raise CorpusValidationError(f"{case_id}: case or implementation authors cannot independently review this case")
        _required_text(reviewer.get("qualification_category"), f"{case_id}.reviewer.qualification_category")
        _required_text(reviewer.get("reviewed_at"), f"{case_id}.reviewer.reviewed_at")
        _required_text(reviewer.get("review_scope"), f"{case_id}.reviewer.review_scope")
        _required_text(reviewer.get("rationale"), f"{case_id}.reviewer.rationale")
        _required_text(reviewer.get("attestation_reference"), f"{case_id}.reviewer.attestation_reference")
        if reviewer.get("source_material_reviewed") is not True:
            raise CorpusValidationError(f"{case_id}: reviewers must attest that source material was reviewed")
        if reviewer.get("decision") != "APPROVED":
            raise CorpusValidationError(f"{case_id}: every qualifying reviewer must approve the case")
        if reviewer.get("independence_attested") is not True:
            raise CorpusValidationError(f"{case_id}: reviewer independence attestation is required")
        if reviewer.get("implementation_independence_attested") is not True:
            raise CorpusValidationError(f"{case_id}: independence from implementation authors must be attested")
        if reviewer.get("conflict_of_interest_checked") is not True:
            raise CorpusValidationError(f"{case_id}: reviewer conflict-of-interest check is required")
        if reviewer.get("expected_outcome_sha256") != expected_sha256:
            raise CorpusValidationError(f"{case_id}: reviewers did not approve the current expected outcome")
        if not _is_sha256(reviewer.get("attestation_sha256")):
            raise CorpusValidationError(f"{case_id}: reviewer attestation SHA-256 is required")


def validate_corpus(manifest: dict[str, Any], artifact_root: str | Path) -> dict[str, Any]:
    """Validate corpus eligibility and category coverage without interpreting cases."""
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise CorpusValidationError(f"Corpus schema must be {SCHEMA}")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CorpusValidationError("Corpus must contain at least one family case")
    root = Path(artifact_root).resolve()
    implementation_authors = manifest.get("implementation_author_ids", [])
    if not isinstance(implementation_authors, list) or any(not isinstance(item, str) or not item.strip() for item in implementation_authors):
        raise CorpusValidationError("implementation_author_ids must be a list of non-empty opaque IDs")
    implementation_author_ids = set(implementation_authors)
    case_ids: set[str] = set()
    coverage: dict[str, set[str]] = {
        category: set() for category in REQUIRED_CATEGORIES
    }
    case_summaries = []
    for case in cases:
        if not isinstance(case, dict):
            raise CorpusValidationError("Every corpus case must be an object")
        case_id = _required_text(case.get("case_id"), "case.case_id")
        if case_id in case_ids:
            raise CorpusValidationError(f"Duplicate case ID: {case_id}")
        case_ids.add(case_id)
        if case.get("qualification_status") != "QUALIFIED":
            raise CorpusValidationError(f"{case_id}: case is not QUALIFIED")
        categories = case.get("categories")
        if not isinstance(categories, list) or not categories:
            raise CorpusValidationError(f"{case_id}: categories must be a non-empty list")
        unknown_categories = sorted(set(categories) - REQUIRED_CATEGORIES)
        if unknown_categories:
            raise CorpusValidationError(
                f"{case_id}: unsupported categories: {', '.join(unknown_categories)}"
            )
        test_role = _required_text(case.get("test_role"), f"{case_id}.test_role")
        if test_role not in ALLOWED_TEST_ROLES:
            raise CorpusValidationError(f"{case_id}: unsupported test_role")
        _validate_source(case, case_id)
        _validate_artifacts(case, case_id, root)
        _validate_evidence(case, case_id)
        expected_sha256 = _validate_expected(case, case_id)
        _validate_reviewers(case, case_id, expected_sha256, implementation_author_ids)
        for category in categories:
            coverage[category].add(test_role)
        case_summaries.append({
            "case_id": case_id,
            "categories": sorted(categories),
            "test_role": test_role,
            "expected_outcome_sha256": expected_sha256,
            "reviewer_count": len(case["reviewers"]),
        })
    missing_coverage = {
        category: sorted(ALLOWED_TEST_ROLES - roles)
        for category, roles in coverage.items()
        if ALLOWED_TEST_ROLES - roles
    }
    return {
        "schema": SCHEMA,
        "status": "QUALIFIED" if not missing_coverage else "BLOCKED_INCOMPLETE_COVERAGE",
        "case_count": len(case_summaries),
        "qualified_case_count": len(case_summaries),
        "category_coverage": {
            category: sorted(roles) for category, roles in sorted(coverage.items())
        },
        "missing_coverage": missing_coverage,
        "cases": case_summaries,
        "clinical_conclusions_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the C1.3 family known-answer corpus.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--artifact-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        report = validate_corpus(manifest, args.artifact_root)
    except (OSError, json.JSONDecodeError, CorpusValidationError) as exc:
        report = {
            "schema": SCHEMA,
            "status": "BLOCKED_INVALID_CORPUS",
            "error": str(exc),
            "clinical_conclusions_performed": False,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
