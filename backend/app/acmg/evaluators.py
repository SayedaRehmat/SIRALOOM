"""Criterion-specific ACMG/AMP evidence evaluators.

This module intentionally uses explicit, versioned configuration. It does not
invent gene/disease-specific thresholds or convert arbitrary predictor scores into
clinical criteria without a calibrated rule profile.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluatorResult:
    criterion: str
    applicable: bool
    strength: str | None
    direction: str
    status: str
    reason: str
    evidence_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] | None = None


class EvaluatorConfigurationError(ValueError):
    pass


def _finite_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluate_pm2(
    observations: list[dict[str, Any]],
    *,
    profile: dict[str, Any],
) -> EvaluatorResult:
    """Evaluate PM2 only from an explicit rarity specification.

    The evaluator requires a configured maximum AF and minimum AN. It treats
    missing population data as indeterminate and never interprets missing data
    as zero frequency.
    """
    cfg = profile.get("PM2") or {}
    max_af = _finite_float(cfg.get("max_allele_frequency"))
    min_an = _int(cfg.get("minimum_allele_number"))
    required_level = cfg.get("population_level")
    required_codes = set(cfg.get("population_codes") or [])
    strength = cfg.get("strength", "MODERATE")
    if max_af is None or min_an is None or min_an <= 0:
        raise EvaluatorConfigurationError("PM2 requires max_allele_frequency and positive minimum_allele_number")

    eligible: list[dict[str, Any]] = []
    unavailable = False
    for obs in observations:
        availability = obs.get("availability", "AVAILABLE")
        if availability != "AVAILABLE":
            unavailable = True
            continue
        if required_level and obs.get("population_level") != required_level:
            continue
        if required_codes and obs.get("population_code") not in required_codes:
            continue
        af = _finite_float(obs.get("allele_frequency"))
        an = _int(obs.get("allele_number"))
        ac = _int(obs.get("allele_count"))
        if af is None or an is None:
            continue
        eligible.append({**obs, "af": af, "an": an, "ac": ac})

    if not eligible:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "REQUIRES_REVIEW",
            "No eligible population observation with AF and AN was available under the configured PM2 specification.",
            metadata={"unavailable_population_data": unavailable},
        )

    qualifying = [o for o in eligible if o["an"] >= min_an and o["af"] <= max_af]
    if not qualifying:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "NOT_MET",
            "No configured population observation satisfies the PM2 rarity threshold.",
            metadata={"threshold_af": max_af, "minimum_an": min_an},
        )

    # If an observation is common above the configured threshold, PM2 is not met.
    disqualifying = [o for o in eligible if o["an"] >= min_an and o["af"] > max_af]
    if disqualifying:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "NOT_MET",
            "At least one eligible population observation exceeds the configured PM2 rarity threshold.",
            metadata={"threshold_af": max_af, "minimum_an": min_an, "disqualifying": disqualifying},
        )

    evidence_ids = tuple(str(o["observation_id"]) for o in qualifying if o.get("observation_id"))
    return EvaluatorResult(
        "PM2", True, strength, "PATHOGENIC", "PROPOSED",
        "Eligible population observations satisfy the configured PM2 rarity threshold.",
        evidence_ids=evidence_ids,
        metadata={"threshold_af": max_af, "minimum_an": min_an, "observations": qualifying},
    )


def evaluate_ba1_bs1(
    observations: list[dict[str, Any]],
    *,
    criterion: str,
    profile: dict[str, Any],
) -> EvaluatorResult:
    """Evaluate BA1/BS1 only when an explicit, approved threshold is configured."""
    if criterion not in {"BA1", "BS1"}:
        raise ValueError("criterion must be BA1 or BS1")
    cfg = profile.get(criterion) or {}
    threshold = _finite_float(cfg.get("minimum_allele_frequency"))
    min_an = _int(cfg.get("minimum_allele_number"))
    if threshold is None or min_an is None or min_an <= 0:
        raise EvaluatorConfigurationError(f"{criterion} requires minimum_allele_frequency and positive minimum_allele_number")
    population_codes = set(cfg.get("population_codes") or [])
    level = cfg.get("population_level")

    candidates = []
    for obs in observations:
        if obs.get("availability", "AVAILABLE") != "AVAILABLE":
            continue
        if level and obs.get("population_level") != level:
            continue
        if population_codes and obs.get("population_code") not in population_codes:
            continue
        af = _finite_float(obs.get("allele_frequency"))
        an = _int(obs.get("allele_number"))
        if af is not None and an is not None and an >= min_an and af >= threshold:
            candidates.append({**obs, "af": af, "an": an})

    if not candidates:
        return EvaluatorResult(
            criterion, False, None, "BENIGN", "NOT_MET",
            f"No eligible population observation satisfies the configured {criterion} frequency threshold.",
            metadata={"threshold_af": threshold, "minimum_an": min_an},
        )

    evidence_ids = tuple(str(o["observation_id"]) for o in candidates if o.get("observation_id"))
    strength = "STANDALONE" if criterion == "BA1" else cfg.get("strength", "STRONG")
    return EvaluatorResult(
        criterion, True, strength, "BENIGN", "PROPOSED",
        f"Eligible population observation(s) satisfy the configured {criterion} frequency threshold.",
        evidence_ids=evidence_ids,
        metadata={"threshold_af": threshold, "minimum_an": min_an, "observations": candidates},
    )


def evaluate_pp3_bp4(
    predictor_observations: dict[str, Any],
    *,
    criterion: str,
    profile: dict[str, Any],
) -> EvaluatorResult:
    """Evaluate PP3/BP4 from calibrated predictor evidence only.

    The profile must declare the predictor, score interval and resulting strength.
    A generic score cutoff is deliberately not supplied by SIRALOOM.
    """
    if criterion not in {"PP3", "BP4"}:
        raise ValueError("criterion must be PP3 or BP4")
    cfg = profile.get(criterion) or {}
    predictor = cfg.get("predictor")
    minimum = _finite_float(cfg.get("minimum_score"))
    maximum = _finite_float(cfg.get("maximum_score"))
    strength = cfg.get("strength", "SUPPORTING")
    if not predictor or (minimum is None and maximum is None):
        raise EvaluatorConfigurationError(
            f"{criterion} requires an explicitly calibrated predictor and score interval"
        )
    score = _finite_float(predictor_observations.get(predictor))
    if score is None:
        return EvaluatorResult(
            criterion, False, None, "PATHOGENIC" if criterion == "PP3" else "BENIGN", "NOT_MET",
            f"Required calibrated predictor '{predictor}' is unavailable.",
        )
    if minimum is not None and score < minimum:
        met = False
    elif maximum is not None and score > maximum:
        met = False
    else:
        met = True
    direction = "PATHOGENIC" if criterion == "PP3" else "BENIGN"
    return EvaluatorResult(
        criterion, met, strength if met else None, direction,
        "PROPOSED" if met else "NOT_MET",
        f"{criterion} evaluation used calibrated predictor {predictor} with score {score}.",
        metadata={"predictor": predictor, "score": score, "minimum_score": minimum, "maximum_score": maximum},
    )


def evaluate_pvs1(
    variant: dict[str, Any],
    *,
    profile: dict[str, Any],
) -> EvaluatorResult:
    """Conservative PVS1 gate based on explicit gene/transcript evidence.

    This is not a full PVS1 decision tree. It requires the profile to assert
    that loss-of-function is an established mechanism and the variant consequence
    to be an explicitly supported LoF class. Further location/transcript/exon
    refinements remain profile-specific and must be supplied by a gene/disease
    specification before stronger automation is enabled.
    """
    cfg = profile.get("PVS1") or {}
    lof_mechanism = cfg.get("lof_mechanism_established") is True
    allowed = set(cfg.get("allowed_consequences") or [])
    consequence = variant.get("consequence")
    if not lof_mechanism:
        raise EvaluatorConfigurationError("PVS1 requires explicit assertion that LoF is an established disease mechanism")
    if not allowed:
        raise EvaluatorConfigurationError("PVS1 requires an explicit allowed_consequences list")
    if consequence not in allowed:
        return EvaluatorResult(
            "PVS1", False, None, "PATHOGENIC", "NOT_MET",
            f"Variant consequence '{consequence}' is not in the configured PVS1 supported consequence set.",
            metadata={"allowed_consequences": sorted(allowed)},
        )
    strength = cfg.get("strength", "VERY_STRONG")
    if strength not in {"SUPPORTING", "MODERATE", "STRONG", "VERY_STRONG"}:
        raise EvaluatorConfigurationError("PVS1 strength must be a valid ACMG evidence strength")
    return EvaluatorResult(
        "PVS1", True, strength, "PATHOGENIC", "PROPOSED",
        "Variant is an explicitly configured LoF consequence in a gene/disease context where LoF is an established mechanism. Additional gene/transcript-specific PVS1 requirements must be satisfied by the active specification.",
        metadata={"consequence": consequence, "lof_mechanism_established": True, "allowed_consequences": sorted(allowed)},
    )
