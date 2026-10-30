"""Conservative pedigree observation handling.

The current application records genotypes and family phenotype observations, but
does not implement a disease/mechanism-aware segregation model. In particular,
it must not infer de novo status, penetrance, phase, or pathogenicity from these
observations alone.
"""
from __future__ import annotations

import hashlib
import json
import re
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


_MISSING_GENOTYPES = {"", ".", "./.", ".|.", "UNKNOWN", "NA", "N/A"}
_KNOWN_ZYGOSITY = {
    "HET",
    "HETEROZYGOUS",
    "HOM_REF",
    "HOM_ALT",
    "HOM",
    "HOMOZYGOUS",
    "HEMI",
    "HEMIZYGOUS",
    "COMPOUND_HETEROZYGOUS",
}
# VCF GT uses allele indexes separated by '/' (unphased) or '|' (phased).
# This validates syntax only; it does not establish phase, pathogenicity, or
# disease-specific inheritance compatibility.
_VCF_GT_RE = re.compile(r"^(?:\d+|\.)(?:[/|](?:\d+|\.))*$")


def _genotype_is_interpretable(genotype: str) -> bool | None:
    """Return None for missing GT, False for malformed GT, True for valid called GT."""
    if genotype in _MISSING_GENOTYPES:
        return None
    if not _VCF_GT_RE.fullmatch(genotype):
        return False
    alleles = re.split(r"[/|]", genotype)
    return any(allele != "." for allele in alleles)


def _has_observation_data(observation: FamilyObservation) -> bool:
    affected = str(observation.affected_status or "").strip().upper()
    genotype = str(observation.genotype or "").strip().upper()
    zygosity = str(observation.zygosity or "").strip().upper()
    phenotype_known = affected in {"AFFECTED", "UNAFFECTED"}

    genotype_state = _genotype_is_interpretable(genotype)
    # Do not allow a malformed non-empty GT field to be rescued by a
    # separately supplied zygosity label. Preserve valid explicit zygosity
    # when no GT was supplied, but never treat arbitrary text as a genotype.
    if genotype_state is False:
        return False
    genotype_known = (
        genotype_state is True
        or (genotype_state is None and zygosity in _KNOWN_ZYGOSITY)
    )
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
