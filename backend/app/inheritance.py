"""Conservative pedigree observation handling.

The current application records genotypes and family phenotype observations, but
does not implement a disease/mechanism-aware segregation model. In particular,
it must not infer de novo status, penetrance, phase, or pathogenicity from these
observations alone.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


VALID_MODELS = {"AD", "AR", "X_LINKED", "MITOCHONDRIAL", "DE_NOVO", "UNKNOWN"}


@dataclass(frozen=True)
class FamilyObservation:
    member_id: str
    sex: str | None
    affected_status: str
    genotype: str | None
    zygosity: str | None


def normalize_model(model: str) -> str:
    value = model.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "AUTOSOMAL_DOMINANT": "AD",
        "AUTOSOMAL_RECESSIVE": "AR",
        "XL": "X_LINKED",
        "MITO": "MITOCHONDRIAL",
        "MT": "MITOCHONDRIAL",
        "DE_NOVO": "DE_NOVO",
    }
    value = aliases.get(value, value)
    if value not in VALID_MODELS:
        raise ValueError(f"Unsupported inheritance model: {model}")
    return value


def _has_observation_data(observation: FamilyObservation) -> bool:
    affected = str(observation.affected_status or "").strip().upper()
    genotype = str(observation.genotype or "").strip().upper()
    zygosity = str(observation.zygosity or "").strip().upper()
    missing = {"", ".", "./.", ".|.", "UNKNOWN", "NA", "N/A"}
    phenotype_known = affected in {"AFFECTED", "UNAFFECTED"}
    genotype_known = genotype not in missing or zygosity not in missing
    return phenotype_known and genotype_known


def assess_model(model: str, observations: list[FamilyObservation]) -> dict:
    """Return data sufficiency only; do not infer inheritance compatibility.

    A compatibility decision needs disease-specific mechanism, penetrance and
    relationship/phase information, and de novo assessment additionally needs
    parental observations and the applicable confirmation policy. Those inputs
    are not yet part of this function's contract.
    """
    normalized_model = normalize_model(model)
    available = [observation for observation in observations if _has_observation_data(observation)]
    if not available:
        return {
            "model": normalized_model,
            "status": "INSUFFICIENT_DATA",
            "observations_available": 0,
            "rationale": "No interpretable genotype and family phenotype observations are available.",
        }
    return {
        "model": normalized_model,
        "status": "REQUIRES_REVIEW",
        "observations_available": len(available),
        "rationale": (
            "Family observations are recorded, but automated compatibility is not implemented. "
            "Review the disease-specific mechanism, penetrance, pedigree relationships, phase, "
            "and required parental or segregation evidence."
        ),
    }


def assessment_projection(*, status: str, rationale: str, score: int | None) -> tuple[str, str]:
    """Do not expose persisted conclusions from the retired M10 heuristic."""
    if score is not None or status in {"CONSISTENT", "CONTRADICTED"}:
        return (
            "REQUIRES_REVIEW",
            "Retired unvalidated heuristic conclusion. Review the recorded family observations.",
        )
    if str(rationale or "").startswith("Retired unvalidated heuristic conclusion"):
        return "REQUIRES_REVIEW", rationale
    return status, rationale


def evidence_projection(*, source_name: str | None, source_version: str | None,
                        statement: str, payload: dict | None) -> tuple[str, dict]:
    """Preserve old evidence records while preventing retired scores from display."""
    result_payload = dict(payload or {})
    if source_name == "SIRALOOM Inheritance Engine" and source_version == "M10":
        result_payload.pop("score", None)
        result_payload["status"] = "REQUIRES_REVIEW"
        result_payload["legacy_result_retired"] = True
        statement = (
            "Legacy heuristic result retired; review the recorded family observations "
            "without treating the prior model status as an inheritance conclusion."
        )
    return statement, result_payload


def fingerprint(observations: list[FamilyObservation]) -> str:
    payload = [observation.__dict__ for observation in sorted(observations, key=lambda x: x.member_id)]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
