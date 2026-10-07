"""Specification-aware assessment of imported ClinGen source assertions.

This layer does not classify variants. It reconciles a source-level ACMG/ClinGen
assertion with the active, validated CSpec rule and produces a reviewable
criterion assessment proposal. Final ACMG combination remains a separate step.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.app.acmg.rules import BENIGN_CRITERIA, PATHOGENIC_CRITERIA
from backend.app.infrastructure.db.models import ACMGSourceAssertion, ClinGenSpecification

VALID_STRENGTHS = ("SUPPORTING", "MODERATE", "STRONG", "VERY_STRONG")
STANDALONE = "STANDALONE"
_STRENGTH_ORDER = {name: index for index, name in enumerate(VALID_STRENGTHS)}
_STRENGTH_ALIASES = {
    "SUPPORTING": "SUPPORTING",
    "SUPPORT": "SUPPORTING",
    "MODERATE": "MODERATE",
    "STRONG": "STRONG",
    "VERY STRONG": "VERY_STRONG",
    "VERY_STRONG": "VERY_STRONG",
    "VERY-STRONG": "VERY_STRONG",
    "STANDALONE": "STANDALONE",
    "STAND ALONE": "STANDALONE",
}


@dataclass(frozen=True)
class SourceCriterionAssessment:
    criterion: str
    effective_criterion: str | None
    applicable: bool
    strength: str | None
    direction: str
    status: str
    source_assertion_ids: tuple[str, ...]
    specification_id: str
    specification_version: str
    rationale: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceCriterionAssessmentError(ValueError):
    pass


def assess_source_assertion(
    assertion: ACMGSourceAssertion,
    specification: ClinGenSpecification,
) -> SourceCriterionAssessment:
    """Reconcile one source assertion against one validated CSpec rule.

    Presence of a criterion in a specification means the rule is in scope; it
    does not by itself prove variant-level applicability. Explicit CSpec
    Not Applicable/configuration signals therefore override the source
    assertion. When the specification does not expose enough structured
    strength information, a MET source assertion remains REQUIRES_REVIEW.
    """
    criterion = assertion.criterion.strip().upper()
    if criterion not in PATHOGENIC_CRITERIA | BENIGN_CRITERIA:
        raise SourceCriterionAssessmentError(f"Unsupported ACMG criterion: {criterion}")

    rule = _criterion_rule(specification.criteria or {}, criterion)
    if rule is None:
        return _assessment(
            assertion,
            specification,
            applicable=False,
            strength=None,
            status="REQUIRES_REVIEW",
            rationale="The active ClinGen specification does not contain a structured rule for this criterion.",
            metadata={"applicability_basis": "NO_STRUCTURED_SPECIFICATION_RULE"},
        )

    if _explicit_not_applicable(rule):
        return _assessment(
            assertion,
            specification,
            applicable=False,
            strength=None,
            status="NOT_APPLICABLE",
            rationale="The active ClinGen specification explicitly marks this criterion Not Applicable.",
            metadata={"applicability_basis": "EXPLICIT_SPECIFICATION_NOT_APPLICABLE", "specification_rule": rule},
        )

    allowed_strengths = _extract_strengths(rule)
    source_strength = _normalize_strength(assertion.strength)

    if assertion.status == "NOT_MET":
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=None,
            status="NOT_MET",
            rationale="The source assertion did not meet the criterion; the active specification permits the criterion but does not convert NOT_MET into evidence.",
            metadata={
                "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
                "source_strength": source_strength,
                "allowed_strengths": list(allowed_strengths),
                "specification_rule": rule,
            },
        )

    if assertion.status != "MET":
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=None,
            status="REQUIRES_REVIEW",
            rationale="The source assertion has an unsupported status and cannot be converted into a criterion assessment.",
            metadata={"source_status": assertion.status, "specification_rule": rule},
        )

    if source_strength is None:
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=None,
            status="REQUIRES_REVIEW",
            rationale="The source assertion is MET but has no recognized evidence strength.",
            metadata={
                "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
                "allowed_strengths": list(allowed_strengths),
                "specification_rule": rule,
            },
        )

    if not allowed_strengths:
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=None,
            status="REQUIRES_REVIEW",
            rationale="The source assertion is MET, but the active specification does not expose a structured allowed strength.",
            metadata={
                "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
                "source_strength": source_strength,
                "specification_rule": rule,
            },
        )

    if source_strength in allowed_strengths:
        effective = _effective_code(criterion, source_strength, allowed_strengths, rule)
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=source_strength,
            status="PROPOSED",
            rationale="The source criterion is MET and its strength is explicitly permitted by the active ClinGen specification.",
            effective_criterion=effective,
            metadata={
                "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
                "strength_basis": "SOURCE_STRENGTH_ALLOWED_BY_SPECIFICATION",
                "allowed_strengths": list(allowed_strengths),
                "specification_rule": rule,
            },
        )

    if len(allowed_strengths) == 1:
        adjusted = allowed_strengths[0]
        effective = _effective_code(criterion, adjusted, allowed_strengths, rule)
        return _assessment(
            assertion,
            specification,
            applicable=True,
            strength=adjusted,
            status="PROPOSED",
            rationale=f"The source asserted {source_strength}, but the active ClinGen specification restricts this criterion to {adjusted}; the proposed strength is therefore specification-governed.",
            effective_criterion=effective,
            metadata={
                "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
                "strength_basis": "SPECIFICATION_OVERRIDE",
                "source_strength": source_strength,
                "allowed_strengths": list(allowed_strengths),
                "specification_rule": rule,
            },
        )

    return _assessment(
        assertion,
        specification,
        applicable=True,
        strength=None,
        status="REQUIRES_REVIEW",
        rationale="The source strength is not among the multiple strengths exposed by the active specification; automatic selection would be ambiguous.",
        metadata={
            "applicability_basis": "STRUCTURED_SPECIFICATION_RULE",
            "strength_basis": "AMBIGUOUS_SPECIFICATION_OPTIONS",
            "source_strength": source_strength,
            "allowed_strengths": list(allowed_strengths),
            "specification_rule": rule,
        },
    )


def assess_source_assertions(
    assertions: Iterable[ACMGSourceAssertion],
    specification: ClinGenSpecification,
) -> tuple[SourceCriterionAssessment, ...]:
    """Assess all source assertions without producing a final classification."""
    return tuple(assess_source_assertion(item, specification) for item in assertions)


def _assessment(
    assertion: ACMGSourceAssertion,
    specification: ClinGenSpecification,
    *,
    applicable: bool,
    strength: str | None,
    status: str,
    rationale: str,
    metadata: dict[str, Any],
    effective_criterion: str | None = None,
) -> SourceCriterionAssessment:
    direction = "PATHOGENIC" if assertion.criterion in PATHOGENIC_CRITERIA else "BENIGN"
    return SourceCriterionAssessment(
        criterion=assertion.criterion,
        effective_criterion=effective_criterion,
        applicable=applicable,
        strength=strength,
        direction=direction,
        status=status,
        source_assertion_ids=(str(assertion.id),),
        specification_id=specification.specification_id,
        specification_version=specification.version,
        rationale=rationale,
        metadata=metadata,
    )


def _criterion_rule(criteria: dict[str, Any], criterion: str) -> dict[str, Any] | None:
    value = criteria.get(criterion)
    if isinstance(value, dict):
        return value
    return None


def _explicit_not_applicable(rule: dict[str, Any]) -> bool:
    for key in ("not_applicable", "notApplicable"):
        if rule.get(key) is True:
            return True
    for key in ("applicable", "isApplicable"):
        if rule.get(key) is False:
            return True
    for key in ("status", "state", "applicability"):
        value = rule.get(key)
        if isinstance(value, str) and value.strip().casefold().replace("_", " ") in {
            "not applicable",
            "notapplicable",
        }:
            return True
    return False


def _extract_strengths(rule: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str):
            normalized = _normalize_strength(value)
            if normalized and normalized != STANDALONE and normalized not in found:
                found.append(normalized)
            elif normalized == STANDALONE and normalized not in found:
                found.append(normalized)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                add(item)

    for key in ("strength", "defaultStrength", "default_strength", "strengths", "allowed_strengths", "allowedStrengths"):
        if key in rule:
            value = rule[key]
            if isinstance(value, dict):
                for nested_key in ("label", "name", "strength", "code", "value"):
                    if nested_key in value:
                        add(value[nested_key])
            else:
                add(value)

    # A structured criterion may expose modified code labels such as PM2_Supporting.
    for key in ("criterion", "criterionCode", "code", "modifiedCriterion", "modified_criterion"):
        value = rule.get(key)
        if isinstance(value, str) and "_" in value:
            suffix = value.rsplit("_", 1)[1]
            add(suffix)

    return tuple(found)


def _normalize_strength(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper().replace("-", "_")
    text = " ".join(text.split())
    return _STRENGTH_ALIASES.get(text) or (
        text if text in VALID_STRENGTHS or text == STANDALONE else None
    )


def _effective_code(criterion: str, strength: str, allowed: tuple[str, ...], rule: dict[str, Any]) -> str | None:
    # A renamed ACMG code is appropriate only when the active CSpec rule
    # explicitly declares a strength modification. A plain structured
    # strength field is the rule's allowed strength, not evidence that the
    # code itself was renamed.
    modification_type = str(
        rule.get("modification_type")
        or rule.get("modificationType")
        or ""
    ).strip().casefold().replace("-", "_").replace(" ", "_")
    if modification_type != "strength":
        return criterion
    baseline = {
        "PVS1": "VERY_STRONG",
        "BA1": "STANDALONE",
        "PS1": "STRONG", "PS2": "STRONG", "PS3": "STRONG", "PS4": "STRONG",
        "PM1": "MODERATE", "PM2": "MODERATE", "PM3": "MODERATE", "PM4": "MODERATE", "PM5": "MODERATE", "PM6": "MODERATE",
        "PP1": "SUPPORTING", "PP2": "SUPPORTING", "PP3": "SUPPORTING", "PP4": "SUPPORTING", "PP5": "SUPPORTING",
        "BS1": "STRONG", "BS2": "STRONG", "BS3": "STRONG", "BS4": "STRONG",
        "BP1": "SUPPORTING", "BP2": "SUPPORTING", "BP3": "SUPPORTING", "BP4": "SUPPORTING", "BP5": "SUPPORTING", "BP6": "SUPPORTING", "BP7": "SUPPORTING",
    }.get(criterion)
    if strength == baseline:
        return criterion
    if strength == STANDALONE:
        return criterion
    return f"{criterion}_{strength.title()}"


__all__ = [
    "SourceCriterionAssessment",
    "SourceCriterionAssessmentError",
    "assess_source_assertion",
    "assess_source_assertions",
]
