"""Criterion-specific ACMG/AMP evidence evaluators.

This module intentionally uses explicit, versioned configuration. It does not
invent gene/disease-specific thresholds or convert arbitrary predictor scores into
clinical criteria without a calibrated rule profile.
"""
from __future__ import annotations

import math
import re
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
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]+", value.strip()):
        return int(value)
    return None


def _frequency_values(obs: dict[str, Any]) -> tuple[float, int, int | None] | None:
    """Validate a population observation before any criterion can consume it.

    Return normalized AF/AN/AC when a usable frequency is present. Return
    ``None`` for missing frequency evidence. Malformed values are reported
    separately by ``_invalid_frequency_reason`` so callers can fail closed.
    """
    af = _finite_float(obs.get("allele_frequency"))
    an = _int(obs.get("allele_number"))
    ac = _int(obs.get("allele_count"))
    if af is None or an is None or an <= 0:
        return None
    return af, an, ac


def _invalid_frequency_reason(obs: dict[str, Any]) -> str | None:
    """Identify malformed available population metrics without coercion."""
    raw_af = obs.get("allele_frequency")
    raw_an = obs.get("allele_number")
    raw_ac = obs.get("allele_count")
    af = _finite_float(raw_af)
    an = _int(raw_an)
    ac = _int(raw_ac)

    if raw_af is not None and af is None:
        return "allele_frequency is not a finite number"
    if af is not None and not 0 <= af <= 1:
        return "allele_frequency is outside [0, 1]"
    if raw_an is not None and (an is None or an < 0):
        return "allele_number is not a non-negative integer"
    if raw_ac is not None and (ac is None or ac < 0):
        return "allele_count is not a non-negative integer"
    if af is not None and (an is None or an == 0):
        return "allele_frequency has no positive allele_number denominator"
    if an is not None and ac is not None and ac > an:
        return "allele_count exceeds allele_number"
    return None


def _invalid_observations(observations: list[dict[str, Any]]) -> list[dict[str, str]]:
    invalid: list[dict[str, str]] = []
    for obs in observations:
        if obs.get("availability", "AVAILABLE") != "AVAILABLE":
            continue
        reason = _invalid_frequency_reason(obs)
        if reason:
            invalid.append({"observation_id": str(obs.get("observation_id") or ""), "reason": reason})
    return invalid


def _incomplete_observations(
    observations: list[dict[str, Any]], *, minimum_allele_number: int
) -> list[dict[str, str]]:
    incomplete: list[dict[str, str]] = []
    for obs in observations:
        observation_id = str(obs.get("observation_id") or "")
        availability = obs.get("availability", "AVAILABLE")
        if availability != "AVAILABLE":
            incomplete.append({
                "observation_id": observation_id,
                "reason": f"population observation availability is {availability}",
            })
            continue
        values = _frequency_values(obs)
        if values is None:
            incomplete.append({
                "observation_id": observation_id,
                "reason": "allele frequency or positive allele number is unavailable",
            })
            continue
        _af, allele_number, _ac = values
        if allele_number < minimum_allele_number:
            incomplete.append({
                "observation_id": observation_id,
                "reason": "allele number is below the configured minimum",
            })
    return incomplete


def _validate_frequency_threshold(value: Any, *, field: str) -> float | None:
    threshold = _finite_float(value)
    if threshold is None or not 0 <= threshold <= 1:
        raise EvaluatorConfigurationError(f"{field} must be a finite frequency in [0, 1]")
    return threshold


def _population_code_allowed(code: str | None, configured_codes: set[str]) -> bool:
    if configured_codes:
        return code in configured_codes
    # Keep cohort-specific values visible without implicitly mixing them into
    # criteria that otherwise consume the resource's joint population record.
    return not (code or "").endswith(("_EXOMES", "_GENOMES"))


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
    max_af = _validate_frequency_threshold(
        cfg.get("max_allele_frequency"), field="PM2 max_allele_frequency"
    ) if cfg.get("max_allele_frequency") is not None else None
    min_an = _int(cfg.get("minimum_allele_number"))
    required_level = cfg.get("population_level")
    required_codes = set(cfg.get("population_codes") or [])
    # ClinGen SVI recommends PM2 at Supporting strength unless the selected
    # disease-specific specification explicitly configures a different level.
    strength = cfg.get("strength", "SUPPORTING")
    if max_af is None or min_an is None or min_an <= 0:
        raise EvaluatorConfigurationError("PM2 requires max_allele_frequency and positive minimum_allele_number")
    if strength not in {"SUPPORTING", "MODERATE", "STRONG", "VERY_STRONG"}:
        raise EvaluatorConfigurationError("PM2 strength must be a valid ACMG evidence strength")

    selected = [
        obs for obs in observations
        if (not required_level or obs.get("population_level") == required_level)
        and _population_code_allowed(obs.get("population_code"), required_codes)
    ]
    invalid = _invalid_observations(selected)
    if invalid:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "REQUIRES_REVIEW",
            "Available population observations contain invalid frequency metrics; PM2 cannot be proposed.",
            metadata={"invalid_population_observations": invalid},
        )

    eligible: list[dict[str, Any]] = []
    for obs in selected:
        availability = obs.get("availability", "AVAILABLE")
        if availability != "AVAILABLE":
            continue
        values = _frequency_values(obs)
        if values is None:
            continue
        af, an, ac = values
        eligible.append({**obs, "af": af, "an": an, "ac": ac})

    if not eligible:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "REQUIRES_REVIEW",
            "No eligible population observation with AF and AN was available under the configured PM2 specification.",
            metadata={"unavailable_population_data": bool(selected)},
        )

    qualifying = [o for o in eligible if o["an"] >= min_an and o["af"] <= max_af]
    # If an observation is common above the configured threshold, PM2 is not met.
    disqualifying = [o for o in eligible if o["an"] >= min_an and o["af"] > max_af]
    if disqualifying:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "NOT_MET",
            "At least one eligible population observation exceeds the configured PM2 rarity threshold.",
            metadata={"threshold_af": max_af, "minimum_an": min_an, "disqualifying": disqualifying},
        )

    incomplete = _incomplete_observations(selected, minimum_allele_number=min_an)
    if incomplete:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "REQUIRES_REVIEW",
            "Population evidence is incomplete under the configured PM2 observation requirements.",
            metadata={
                "threshold_af": max_af,
                "minimum_an": min_an,
                "incomplete_population_observations": incomplete,
            },
        )

    if not qualifying:
        return EvaluatorResult(
            "PM2", False, None, "PATHOGENIC", "NOT_MET",
            "No configured population observation satisfies the PM2 rarity threshold.",
            metadata={"threshold_af": max_af, "minimum_an": min_an},
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
    threshold = _validate_frequency_threshold(
        cfg.get("minimum_allele_frequency"), field=f"{criterion} minimum_allele_frequency"
    ) if cfg.get("minimum_allele_frequency") is not None else None
    min_an = _int(cfg.get("minimum_allele_number"))
    if threshold is None or min_an is None or min_an <= 0:
        raise EvaluatorConfigurationError(f"{criterion} requires minimum_allele_frequency and positive minimum_allele_number")
    population_codes = set(cfg.get("population_codes") or [])
    level = cfg.get("population_level")
    selected = [
        obs for obs in observations
        if (not level or obs.get("population_level") == level)
        and _population_code_allowed(obs.get("population_code"), population_codes)
    ]
    invalid = _invalid_observations(selected)
    if invalid:
        return EvaluatorResult(
            criterion, False, None, "BENIGN", "REQUIRES_REVIEW",
            "Available population observations contain invalid frequency metrics; this criterion cannot be proposed.",
            metadata={"invalid_population_observations": invalid},
        )
    candidates = []
    for obs in selected:
        if obs.get("availability", "AVAILABLE") != "AVAILABLE":
            continue
        values = _frequency_values(obs)
        if values is None:
            continue
        af, an, _ac = values
        if an >= min_an and af >= threshold:
            candidates.append({**obs, "af": af, "an": an})

    if not selected:
        return EvaluatorResult(
            criterion, False, None, "BENIGN", "REQUIRES_REVIEW",
            f"No population observations are available to evaluate {criterion}.",
            metadata={"minimum_allele_number": min_an},
        )

    if candidates:
        evidence_ids = tuple(str(o["observation_id"]) for o in candidates if o.get("observation_id"))
        strength = "STANDALONE" if criterion == "BA1" else cfg.get("strength", "STRONG")
        return EvaluatorResult(
            criterion, True, strength, "BENIGN", "PROPOSED",
            f"Eligible population observation(s) satisfy the configured {criterion} frequency threshold.",
            evidence_ids=evidence_ids,
            metadata={"threshold_af": threshold, "minimum_an": min_an, "observations": candidates},
        )

    incomplete = _incomplete_observations(selected, minimum_allele_number=min_an)
    if incomplete:
        return EvaluatorResult(
            criterion, False, None, "BENIGN", "REQUIRES_REVIEW",
            f"Population evidence is incomplete under the configured {criterion} observation requirements.",
            metadata={
                "threshold_af": threshold,
                "minimum_an": min_an,
                "incomplete_population_observations": incomplete,
            },
        )

    return EvaluatorResult(
        criterion, False, None, "BENIGN", "NOT_MET",
        f"No eligible population observation satisfies the configured {criterion} frequency threshold.",
        metadata={"threshold_af": threshold, "minimum_an": min_an},
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
    raw_minimum = cfg.get("minimum_score")
    raw_maximum = cfg.get("maximum_score")
    minimum = _finite_float(raw_minimum)
    maximum = _finite_float(raw_maximum)
    strength = cfg.get("strength", "SUPPORTING")
    if not predictor or (minimum is None and maximum is None):
        raise EvaluatorConfigurationError(
            f"{criterion} requires an explicitly calibrated predictor and score interval"
        )
    if (raw_minimum is not None and minimum is None) or (
        raw_maximum is not None and maximum is None
    ):
        raise EvaluatorConfigurationError(
            f"{criterion} score bounds must be finite numeric values"
        )
    if minimum is not None and maximum is not None and minimum > maximum:
        raise EvaluatorConfigurationError(
            f"{criterion} minimum_score cannot exceed maximum_score"
        )
    if strength not in {"SUPPORTING", "MODERATE", "STRONG", "VERY_STRONG"}:
        raise EvaluatorConfigurationError(
            f"{criterion} strength must be a valid ACMG evidence strength"
        )
    raw_score = predictor_observations.get(predictor)
    score = _finite_float(raw_score)
    if score is None:
        return EvaluatorResult(
            criterion, False, None, "PATHOGENIC" if criterion == "PP3" else "BENIGN", "REQUIRES_REVIEW",
            (
                f"Required calibrated predictor '{predictor}' is unavailable."
                if raw_score is None or raw_score == ""
                else f"Calibrated predictor '{predictor}' returned an invalid score."
            ),
            metadata={
                "predictor": predictor,
                "input_status": "MISSING" if raw_score is None or raw_score == "" else "INVALID",
            },
        )
    if (minimum is not None and score < minimum) or (
        maximum is not None and score > maximum
    ):
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
