"""Source-bound disease-specific inheritance review context.

This contract validates whether the required evidence is present and preserves its
provenance. It intentionally does not infer compatibility, segregation, de novo
status, penetrance, pathogenicity, or a clinical conclusion.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class InheritanceReviewContextError(ValueError):
    """A disease or family evidence object is malformed or internally inconsistent."""


SUPPORTED_DISEASE_MODES = {
    "AUTOSOMAL_DOMINANT",
    "AUTOSOMAL_RECESSIVE",
    "X_LINKED_DOMINANT",
    "X_LINKED_RECESSIVE",
    "Y_LINKED",
    "MITOCHONDRIAL",
    "DE_NOVO",
    "UNKNOWN",
}
_MATRIX_CALL_STATES = {
    "NO_RECORD", "GENOTYPE_UNAVAILABLE", "NO_CALL", "PARTIAL_NO_CALL",
    "CALL_PRESENT", "OTHER_ALT_PRESENT", "OTHER_ALT_AND_MISSING", "INVALID_CALL",
}


def _required(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise InheritanceReviewContextError(f"Required field is missing: {field}")
    return result


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_inheritance_review_context(
    *,
    disease_association: dict[str, Any],
    family_matrix: dict[str, Any],
) -> dict[str, Any]:
    """Build a reviewable evidence manifest; never return compatibility status."""
    if not isinstance(disease_association, dict):
        raise InheritanceReviewContextError("disease_association must be an object")
    if not isinstance(family_matrix, dict):
        raise InheritanceReviewContextError("family_matrix must be an object")

    gene = _required(disease_association.get("gene"), "gene").upper()
    disease_id = _required(disease_association.get("disease_id"), "disease_id")
    resource_id = _required(disease_association.get("resource_id"), "resource_id")
    resource_version = _required(disease_association.get("resource_version"), "resource_version")
    source_record_id = _required(disease_association.get("source_record_id"), "source_record_id")
    mechanism = _required(disease_association.get("molecular_mechanism"), "molecular_mechanism")
    modes = disease_association.get("inheritance_modes")
    if not isinstance(modes, list) or not modes:
        raise InheritanceReviewContextError("inheritance_modes must be a non-empty list")
    normalized_modes = sorted({str(mode).strip().upper().replace("-", "_").replace(" ", "_") for mode in modes})
    unknown_modes = sorted(set(normalized_modes) - SUPPORTED_DISEASE_MODES)
    if unknown_modes:
        raise InheritanceReviewContextError("Unsupported disease inheritance modes: " + ", ".join(unknown_modes))

    penetrance = disease_association.get("penetrance")
    if not isinstance(penetrance, dict):
        raise InheritanceReviewContextError("penetrance must be an explicit object")
    penetrance_status = _required(penetrance.get("status"), "penetrance.status").upper()
    penetrance_source = str(penetrance.get("source") or "").strip()
    if penetrance_status not in {"KNOWN", "REDUCED", "AGE_DEPENDENT", "SEX_DEPENDENT", "UNKNOWN", "NOT_RECORDED"}:
        raise InheritanceReviewContextError("Unsupported penetrance.status")
    if penetrance_status not in {"UNKNOWN", "NOT_RECORDED"} and not penetrance_source:
        raise InheritanceReviewContextError("A source is required for a non-unknown penetrance assertion")

    matrix_fingerprint = _required(family_matrix.get("matrix_fingerprint"), "family_matrix.matrix_fingerprint")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", matrix_fingerprint):
        raise InheritanceReviewContextError("family_matrix.matrix_fingerprint must be SHA-256")
    samples = family_matrix.get("samples")
    relationships = family_matrix.get("relationships_as_recorded")
    if not isinstance(samples, list) or not samples:
        raise InheritanceReviewContextError("family_matrix.samples must be a non-empty list")
    if not isinstance(relationships, list):
        raise InheritanceReviewContextError("family_matrix.relationships_as_recorded must be a list")
    probands = [sample for sample in samples if isinstance(sample, dict) and sample.get("is_proband")]
    if len(probands) != 1:
        raise InheritanceReviewContextError("Exactly one family-matrix proband is required")
    variant_ids = family_matrix.get("variant_ids")
    if not isinstance(variant_ids, list) or not variant_ids:
        raise InheritanceReviewContextError("family_matrix.variant_ids must be non-empty")

    gaps: set[str] = set()
    if family_matrix.get("provenance_completeness_status") != "COMPLETE":
        gaps.add("SOURCE_PROVENANCE_INCOMPLETE")
    if family_matrix.get("qualification_status") != "PROVENANCE_PROJECTION_ONLY_NOT_CLINICALLY_QUALIFIED":
        gaps.add("UNRECOGNIZED_MATRIX_QUALIFICATION_STATE")
    if family_matrix.get("biological_relatedness_status") != "NOT_ESTABLISHED":
        gaps.add("BIOLOGICAL_RELATEDNESS_REQUIRES_INDEPENDENT_REVIEW")
    else:
        gaps.add("BIOLOGICAL_RELATEDNESS_NOT_INDEPENDENTLY_ESTABLISHED")
    if family_matrix.get("callability_status") != "ASSESSED":
        gaps.add("LAB_APPROVED_CALLABILITY_POLICY_NOT_APPLIED")
    if family_matrix.get("ploidy_status") != "QUALIFIED_FOR_LOCUS":
        gaps.add("LOCUS_SPECIFIC_PLOIDY_POLICY_NOT_APPLIED")

    sample_manifest = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise InheritanceReviewContextError("Every family matrix sample must be an object")
        sample_id = _required(sample.get("member_id"), "sample.member_id")
        calls = sample.get("calls")
        if not isinstance(calls, list):
            raise InheritanceReviewContextError("Every family matrix sample requires a calls list")
        normalized_calls = []
        for call in calls:
            if not isinstance(call, dict):
                raise InheritanceReviewContextError("Every family matrix call must be an object")
            state = _required(call.get("call_state"), "call.call_state")
            if state not in _MATRIX_CALL_STATES:
                raise InheritanceReviewContextError(f"Unsupported family genotype call state: {state}")
            if state != "CALL_PRESENT":
                gaps.add("ONE_OR_MORE_FAMILY_GENOTYPES_NOT_CALL_PRESENT")
            if call.get("callability") != "ASSESSED":
                gaps.add("ONE_OR_MORE_FAMILY_CALLS_NOT_CALLABILITY_ASSESSED")
            if call.get("quality_assessment_status") != "PASS":
                gaps.add("ONE_OR_MORE_FAMILY_CALLS_NOT_QUALITY_ASSESSED_PASS")
            normalized_calls.append({
                "variant_id": _required(call.get("variant_id"), "call.variant_id"),
                "call_state": state,
                "genotype": call.get("projected_genotype") or call.get("normalized_genotype"),
                "zygosity": call.get("zygosity"),
                "phase": call.get("phase"),
                "phase_set": call.get("phase_set"),
                "quality_metrics": call.get("quality_metrics") or {},
                "source_record_sha256": call.get("source_record_sha256"),
                "callability": call.get("callability"),
                "quality_assessment_status": call.get("quality_assessment_status"),
            })
        if sample.get("ploidy_evidence_status") != "VERIFIED_RECORDED_LOCUS_POLICY_REQUIRED":
            gaps.add("SPECIMEN_PLOIDY_EVIDENCE_NOT_VERIFIED_FOR_LOCUS_POLICY")
        if sample.get("identity_interpretation") != "CHAIN_OF_CUSTODY_AND_SAMPLE_IDENTITY_QC_ACCEPTED; BIOLOGICAL_RELATEDNESS_NOT_ESTABLISHED":
            gaps.add("SAMPLE_IDENTITY_EVIDENCE_NOT_RECOGNIZED")
        sample_manifest.append({
            "member_id": sample_id,
            "member_identifier": _required(sample.get("member_identifier"), "sample.member_identifier"),
            "is_proband": bool(sample.get("is_proband")),
            "sex": sample.get("sex") or "UNKNOWN",
            "affected_status": sample.get("affected_status") or "UNKNOWN",
            "relationship_to_proband": sample.get("relationship_to_proband"),
            "binding_id": _required(sample.get("binding_id"), "sample.binding_id"),
            "binding_fingerprint": _required(sample.get("binding_fingerprint"), "sample.binding_fingerprint"),
            "analysis_id": _required(sample.get("analysis_id"), "sample.analysis_id"),
            "analysis_version": sample.get("analysis_version"),
            "source_artifact_sha256": sample.get("source_artifact_sha256"),
            "identity_evidence": sample.get("identity_evidence"),
            "normalization_provenance_status": sample.get("normalization_provenance_status"),
            "ploidy_evidence": sample.get("ploidy_evidence"),
            "calls": normalized_calls,
        })

    # Recorded parent-child edges are retained exactly as context. The matrix
    # explicitly labels them as unverified; they cannot establish parentage.
    relationship_manifest = []
    for relationship in relationships:
        if not isinstance(relationship, dict):
            raise InheritanceReviewContextError("Every pedigree relationship must be an object")
        relationship_manifest.append({
            "parent_member_identifier": _required(relationship.get("parent_member_identifier"), "relationship.parent_member_identifier"),
            "child_member_identifier": _required(relationship.get("child_member_identifier"), "relationship.child_member_identifier"),
            "relationship_type": _required(relationship.get("relationship_type"), "relationship.relationship_type"),
            "relationship_status": relationship.get("relationship_status") or "AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED",
            "metadata": relationship.get("metadata") or {},
        })
        if relationship_manifest[-1]["relationship_status"] != "INDEPENDENTLY_VERIFIED":
            gaps.add("PEDIGREE_RELATIONSHIPS_NOT_INDEPENDENTLY_VERIFIED")

    if normalized_modes == ["UNKNOWN"]:
        gaps.add("DISEASE_INHERITANCE_MODE_UNKNOWN")
    if penetrance_status in {"UNKNOWN", "NOT_RECORDED"}:
        gaps.add("DISEASE_PENETRANCE_NOT_ESTABLISHED")

    payload = {
        "schema_version": 1,
        "gene": gene,
        "disease_id": disease_id,
        "molecular_mechanism": mechanism,
        "inheritance_modes": normalized_modes,
        "penetrance": dict(penetrance),
        "association_provenance": {
            "resource_id": resource_id,
            "resource_version": resource_version,
            "source_record_id": source_record_id,
            "resource_sha256": disease_association.get("resource_sha256"),
        },
        "family_matrix_fingerprint": matrix_fingerprint,
        "family_matrix_snapshot_id": family_matrix.get("snapshot_id"),
        "family_samples": sample_manifest,
        "relationships_as_recorded": relationship_manifest,
        "evidence_gaps": sorted(gaps),
        "status": "REQUIRES_HUMAN_REVIEW",
        "compatibility_conclusion": None,
        "segregation_conclusion": None,
        "de_novo_conclusion": None,
        "clinical_interpretation_performed": False,
    }
    return {
        **payload,
        "review_context_fingerprint": _fingerprint(payload),
        "human_review_required": True,
        "clinical_qualification_status": "NOT_QUALIFIED_PENDING_INDEPENDENT_KNOWN_ANSWER_REVIEW",
    }
