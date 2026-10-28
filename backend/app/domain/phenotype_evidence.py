from __future__ import annotations

from typing import Any


def phenotype_evidence_display_payload(
    evidence_type: str | None, payload: dict[str, Any] | None
) -> dict[str, Any]:
    """Return a presentation-safe copy of phenotype evidence.

    Historical evidence remains immutable and fingerprinted as stored. Older
    releases emitted an unvalidated overlap fraction; it must not be presented
    as a similarity or clinical score in current API/report/export views.
    """
    result = dict(payload or {})
    if str(evidence_type or "").upper() not in {"GENE_DISEASE", "PHENOTYPE"}:
        return result
    match = result.get("phenotype_match")
    if not isinstance(match, dict):
        return result
    match = dict(match)
    legacy_score = any(
        key in match for key in ("score", "exact_overlap_score", "score_semantics")
    ) or str(match.get("status", "")).upper() == "SCORED"
    for key in ("score", "exact_overlap_score", "score_semantics"):
        match.pop(key, None)
    if str(match.get("status", "")).upper() == "SCORED":
        match["status"] = "CONTEXT_ONLY"
    if legacy_score:
        match["clinical_prioritization_validated"] = False
        match["interpretive_use"] = "HUMAN_REVIEW_CONTEXT_ONLY"
    result["phenotype_match"] = match
    return result
