"""Deterministic, provenance-preserving family genotype matrix projection.

This module deliberately does not infer reference genotypes, callability, relatedness,
segregation, inheritance compatibility, or clinical pathogenicity.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Sequence
from uuid import UUID


def _canonical_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _call_state(call: dict[str, Any] | None) -> str:
    if call is None:
        # Absence from a variant-only VCF is not a reference genotype.
        return "NO_RECORD"

    projection_status = call.get("projection_status") or call.get("projected_status")
    projection_states = {
        "AVAILABLE": "CALL_PRESENT",
        "NO_CALL": "NO_CALL",
        "PARTIAL_CALL": "PARTIAL_NO_CALL",
        "GENOTYPE_UNAVAILABLE": "GENOTYPE_UNAVAILABLE",
        "CONTAINS_OTHER_ALT": "OTHER_ALT_PRESENT",
        "CONTAINS_OTHER_ALT_AND_MISSING": "OTHER_ALT_AND_MISSING",
        "INVALID_SOURCE_GT": "INVALID_CALL",
        "INVALID_SOURCE_ALT_MAPPING": "INVALID_CALL",
        "SOURCE_NORMALIZED_PLOIDY_MISMATCH": "INVALID_CALL",
    }
    if projection_status in projection_states:
        return projection_states[projection_status]

    genotype = call.get("projected_genotype") or call.get("normalized_genotype") or call.get("genotype")
    if not isinstance(genotype, str) or not genotype:
        return "GENOTYPE_UNAVAILABLE"
    if not re.fullmatch(r"(?:\d+|\.)(?:[/|](?:\d+|\.))*", genotype):
        return "INVALID_CALL"
    alleles = re.split(r"[/|]", genotype)
    try:
        missing_alleles = int(call.get("missing_allele_count") or 0)
    except (TypeError, ValueError):
        return "INVALID_CALL"
    if missing_alleles < 0 or missing_alleles != sum(allele == "." for allele in alleles):
        return "INVALID_CALL"
    if missing_alleles > 0:
        return "NO_CALL" if missing_alleles == len(alleles) else "PARTIAL_NO_CALL"
    return "CALL_PRESENT"


def _quality_metrics(format_values: Any) -> dict[str, Any]:
    if not isinstance(format_values, dict):
        return {}
    # Preserve source values exactly. Lab-specific thresholds are applied by a
    # separately versioned QC policy, never by this projection.
    return {
        key: format_values[key]
        for key in ("DP", "GQ", "AD", "PL", "GL", "FT")
        if key in format_values
    }


def build_family_genotype_matrix(
    *,
    case_id: UUID,
    variant_ids: Sequence[UUID],
    samples: Sequence[dict[str, Any]],
    relationships: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic matrix from validated sample-call snapshots."""
    if not variant_ids:
        raise ValueError("At least one canonical variant ID is required")
    if len(set(variant_ids)) != len(variant_ids):
        raise ValueError("Variant IDs must be unique")
    if not samples:
        raise ValueError("At least one verified sample binding is required")

    ordered_variants = [str(value) for value in variant_ids]
    matrix_samples = []
    for sample in sorted(samples, key=lambda item: (item["member_identifier"], str(item["member_id"]), str(item["specimen_id"]), str(item["analysis_id"]), str(item["binding_id"]))):
        calls = sample["calls"]
        rows = []
        for variant_id in ordered_variants:
            call = calls.get(UUID(variant_id))
            state = _call_state(call)
            call = call or {}
            rows.append({
                "variant_id": variant_id,
                "call_state": state,
                "callability": "NOT_ASSESSED",
                "source_genotype": call.get("source_genotype"),
                "normalized_genotype": call.get("normalized_genotype"),
                "projected_genotype": call.get("projected_genotype"),
                "zygosity": call.get("projected_zygosity") or call.get("normalized_zygosity") or call.get("zygosity", "UNKNOWN"),
                "reference_allele_dosage": call.get("reference_allele_dosage"),
                "selected_alt_dosage": call.get("selected_alt_dosage"),
                "other_alt_dosage": call.get("other_alt_dosage"),
                "missing_allele_count": call.get("missing_allele_count"),
                "phase": call.get("projected_phase") or call.get("normalized_phase") or call.get("phase", "UNSPECIFIED"),
                "phase_set": call.get("phase_set"),
                "quality_metrics": _quality_metrics(call.get("format_values")),
                "format_values": call.get("format_values", {}),
                "source_record_sha256": call.get("source_record_sha256"),
                "source_record_index": call.get("source_record_index"),
                "projection_status": call.get("projection_status", "GENOTYPE_UNAVAILABLE"),
                "projected_zygosity": call.get("projected_zygosity"),
                "projected_phase": call.get("projected_phase"),
                "sample_call_status": call.get("status", "GENOTYPE_UNAVAILABLE"),
            })
        matrix_samples.append({
            "member_id": str(sample["member_id"]),
            "member_identifier": sample["member_identifier"],
            "relationship_to_proband": sample.get("relationship_to_proband"),
            "sex": sample.get("sex") or "UNKNOWN",
            "affected_status": sample.get("affected_status", "UNKNOWN"),
            "specimen_id": str(sample["specimen_id"]),
            "analysis_id": str(sample["analysis_id"]),
            "analysis_version": sample["analysis_version"],
            "source_artifact_id": str(sample["artifact_id"]),
            "source_artifact_sha256": sample["artifact_sha256"],
            "vcf_sample_name": sample["sample_name"],
            "binding_id": str(sample["binding_id"]),
            "binding_fingerprint": sample["binding_fingerprint"],
            "binding_status": "VERIFIED",
            "identity_interpretation": "CHAIN_OF_CUSTODY_AND_SAMPLE_IDENTITY_QC_ACCEPTED; BIOLOGICAL_RELATEDNESS_NOT_ESTABLISHED",
            "identity_evidence": sample["identity_evidence"],
            "normalization_step_status": sample["normalization_step_status"],
            "normalized_partition_count": sample["normalized_partition_count"],
            "ploidy_evidence": sample.get("ploidy_evidence") or {
                "status": "NOT_ASSESSED",
                "reason": "No specimen-scoped ploidy evidence revision was available.",
            },
            "calls": rows,
        })

    relationship_snapshot = sorted(
        [dict(item) for item in relationships],
        key=lambda item: (
            item.get("parent_member_identifier", ""),
            item.get("child_member_identifier", ""),
            item.get("relationship_type", ""),
        ),
    )
    fingerprint_payload = {
        "schema_version": 1,
        "case_id": str(case_id),
        "variant_ids": ordered_variants,
        "samples": matrix_samples,
        "relationships": relationship_snapshot,
    }
    return {
        "schema_version": 1,
        "case_id": str(case_id),
        "variant_ids": ordered_variants,
        "samples": matrix_samples,
        "relationships_as_recorded": relationship_snapshot,
        "interpretation_status": "NOT_PERFORMED",
        "callability_status": "NOT_ASSESSED; REQUIRES_LAB_QC_POLICY",
        "biological_relatedness_status": "NOT_ESTABLISHED",
        "matrix_fingerprint": _canonical_fingerprint(fingerprint_payload),
    }
