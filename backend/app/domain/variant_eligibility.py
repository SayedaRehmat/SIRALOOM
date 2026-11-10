"""Fail-closed eligibility for the initial SNV and small-indel product scope."""
from __future__ import annotations

from typing import Any


UNSUPPORTED_VALIDATION_COUNTERS = {
    "symbolic_source_record_count": "symbolic structural alleles",
    "breakend_source_record_count": "breakend structural alleles",
    "gvcf_marker_count": "GVCF reference-block markers",
    "telomere_record_count": "telomere sentinel records requiring separate review",
    "unresolved_spanning_deletion_record_count": "unresolved spanning-deletion records",
}

REQUIRED_VALIDATION_FIELDS = (
    "source_record_count",
    "parsed_variant_record_count",
    "symbolic_source_record_count",
    "breakend_source_record_count",
    "gvcf_marker_count",
    "telomere_record_count",
    "unresolved_spanning_deletion_record_count",
)


def evaluate_small_variant_eligibility(validation: dict[str, Any] | None) -> dict[str, Any]:
    """Assess whether an immutable validated VCF fits the current product scope.

    Structural VCF conformance is not workflow eligibility. The parser may
    correctly accept SV/GVCF syntax while the SNV/small-indel workflow must
    explicitly refuse to interpret those records.
    """
    if not isinstance(validation, dict):
        return {
            "scope": "SNV_SMALL_INDEL",
            "status": "NOT_ASSESSED",
            "reason_codes": ["VCF_WORKFLOW_ELIGIBILITY_NOT_ASSESSED"],
            "reasons": ["The VCF validation profile does not contain the required eligibility counters."],
        }

    missing = [field for field in REQUIRED_VALIDATION_FIELDS if field not in validation]
    if missing:
        return {
            "scope": "SNV_SMALL_INDEL",
            "status": "NOT_ASSESSED",
            "reason_codes": ["VCF_WORKFLOW_ELIGIBILITY_NOT_ASSESSED"],
            "reasons": ["Required validation counters are missing: " + ", ".join(missing)],
        }

    invalid = [
        field for field in REQUIRED_VALIDATION_FIELDS
        if isinstance(validation.get(field), bool)
        or not isinstance(validation.get(field), int)
        or validation[field] < 0
    ]
    if invalid:
        return {
            "scope": "SNV_SMALL_INDEL",
            "status": "NOT_ASSESSED",
            "reason_codes": ["VCF_WORKFLOW_ELIGIBILITY_COUNTER_INVALID"],
            "reasons": ["Validation counters are invalid: " + ", ".join(invalid)],
        }

    reasons = []
    reason_codes = []
    for field, description in UNSUPPORTED_VALIDATION_COUNTERS.items():
        count = validation[field]
        if count:
            reason_codes.append("UNSUPPORTED_" + field.upper())
            reasons.append(f"{count} {description} are outside the SNV/small-indel workflow scope.")

    if not validation["parsed_variant_record_count"]:
        reason_codes.append("NO_VARIANT_RECORDS_FOR_SMALL_VARIANT_ANALYSIS")
        reasons.append("The VCF contains no parsed variant records for small-variant interpretation.")

    return {
        "scope": "SNV_SMALL_INDEL",
        "status": "INELIGIBLE" if reason_codes else "ELIGIBLE",
        "reason_codes": reason_codes,
        "reasons": reasons,
    }
