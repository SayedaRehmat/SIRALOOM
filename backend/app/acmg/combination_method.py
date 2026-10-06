"""Detect and route ClinGen ACMG combination methods conservatively.

This module only decides which combination framework may consume criterion
assessments. It does not calculate points, Bayesian odds, or a final
classification. Unsupported methods therefore fail closed to human review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STANDARD_ACMG = "STANDARD_ACMG_AMP"
MODIFIED_ACMG = "MODIFIED_ACMG_AMP"
POINT_BASED = "POINT_BASED"
BAYESIAN = "BAYESIAN"
UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class CombinationMethodDecision:
    method: str
    executable: bool
    reason: str
    metadata: dict[str, Any]


def detect_combination_method(specification: Any) -> CombinationMethodDecision:
    """Detect the governing combination method from a stored CSpec snapshot.

    Detection is evidence-based and intentionally conservative. Structured
    fields are preferred; raw payload text is used only for explicit method
    signals. Absence of a non-standard signal is treated as standard
    ACMG/AMP, matching CSpec specifications whose combining rules are the
    ordinary Richards et al. framework.
    """
    criteria = getattr(specification, "criteria", None) or {}
    raw_payload = getattr(specification, "raw_payload", None) or {}

    explicit = _collect_explicit_values(criteria, raw_payload)
    combined_text = " ".join(explicit).casefold()
    keyed_methods = _collect_keyed_method_values(criteria, raw_payload)
    if keyed_methods:
        method_text = " ".join(keyed_methods).casefold()
        if not _contains_any(method_text, (
            "acmg/amp",
            "acmg amp",
            "richards",
            "standard",
            "baseline",
            "point",
            "bayes",
            "modified",
            "combining rules",
            "combination rules",
        )):
            return CombinationMethodDecision(
                UNSUPPORTED,
                False,
                "The active ClinGen specification declares a combination method that SIRALOOM does not recognize; human review is required.",
                {
                    "detection_basis": "UNKNOWN_EXPLICIT_COMBINATION_METHOD",
                    "declared_methods": keyed_methods,
                },
            )

    # Strongest signals first. A specification that explicitly says to use a
    # point attachment must never be sent through the ordinary ACMG engine.
    if _contains_any(combined_text, (
        "bayesian",
        "bayes factor",
        "posterior odds",
        "bayes",
    )):
        return CombinationMethodDecision(
            BAYESIAN,
            False,
            "The active ClinGen specification declares Bayesian combination/classification logic; SIRALOOM has no validated Bayesian combination engine yet.",
            {"detection_basis": "EXPLICIT_SPECIFICATION_SIGNAL"},
        )

    if (
        _contains_any(combined_text, (
            "point-based",
            "point based",
            "point counting",
            "point-counting",
            "points-based",
            "points based",
            "use a points-based",
            "use a point-based",
            "point system",
        ))
        or (
            "disregard" in combined_text
            and "rules for combining criteria" in combined_text
            and "point" in combined_text
        )
    ):
        return CombinationMethodDecision(
            POINT_BASED,
            False,
            "The active ClinGen specification uses point-based combination logic; SIRALOOM has no validated specification-specific point engine yet.",
            {"detection_basis": "EXPLICIT_SPECIFICATION_SIGNAL"},
        )

    if _contains_any(combined_text, (
        "modified combining rules",
        "modified rules for combining",
        "edited rules for combining",
        "non-standard combining",
        "nonstandard combining",
        "modified combination",
    )):
        return CombinationMethodDecision(
            MODIFIED_ACMG,
            False,
            "The active ClinGen specification modifies ACMG/AMP combination rules; SIRALOOM does not yet have a validated executor for those modified rules.",
            {"detection_basis": "EXPLICIT_MODIFICATION_SIGNAL"},
        )

    # A specification may encode modified combinations as prose without a
    # formal method field. Do not classify every mention of "plus" as modified;
    # require a combining-rules context and an explicit departure signal.
    if (
        "rules for combining criteria" in combined_text
        and _contains_any(combined_text, (
            "plus (",
            "plus ",
            "additional combination",
            "additional rule",
            "one very strong",
            "one strong benign",
        ))
    ):
        return CombinationMethodDecision(
            MODIFIED_ACMG,
            False,
            "The active ClinGen specification contains explicit combination rules beyond the baseline ACMG/AMP rules; SIRALOOM requires a validated specification-specific executor before automation.",
            {"detection_basis": "COMBINATION_RULE_PROSE"},
        )

    return CombinationMethodDecision(
        STANDARD_ACMG,
        True,
        "No explicit alternative combination method was detected; the specification may use the baseline ACMG/AMP combining framework.",
        {"detection_basis": "DEFAULT_BASELINE_ACMG_AMP"},
    )


def _collect_explicit_values(criteria: dict[str, Any], raw_payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def walk(value: Any, *, key: str | None = None) -> None:
        if isinstance(value, str):
            normalized_key = (key or "").casefold()
            if (
                not key
                or any(token in normalized_key for token in (
                    "combining",
                    "combination",
                    "classification",
                    "method",
                    "rule",
                    "attachment",
                    "point",
                    "bayes",
                    "type",
                ))
            ):
                values.append(value)
            return
        if isinstance(value, (int, float, bool)):
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, key=str(child_key))
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                walk(child, key=key)

    walk(criteria)
    walk(raw_payload)
    return values


def _collect_keyed_method_values(criteria: dict[str, Any], raw_payload: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def walk(value: Any, *, key: str | None = None) -> None:
        if isinstance(value, str):
            normalized_key = (key or "").casefold()
            if "combiningmethod" in normalized_key or "combinationmethod" in normalized_key:
                values.append(value)
            return
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                walk(child_value, key=str(child_key))
            return
        if isinstance(value, (list, tuple, set)):
            for child in value:
                walk(child, key=key)

    walk(criteria)
    walk(raw_payload)
    return values

def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


__all__ = [
    "BAYESIAN",
    "MODIFIED_ACMG",
    "POINT_BASED",
    "STANDARD_ACMG",
    "UNSUPPORTED",
    "CombinationMethodDecision",
    "detect_combination_method",
]
