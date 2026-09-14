"""Versioned ACMG/AMP baseline combination rules.

This module deliberately does NOT infer biological evidence from raw annotations.
Criterion assignment must come from evidence-specific, explicitly configured rules
(e.g. ClinGen/VCEP/gene-disease specifications). This module only validates
criterion codes/strengths and applies the published 2015 ACMG/AMP combination
logic as a baseline proposal layer.
"""
from dataclasses import dataclass
from enum import StrEnum

class CriterionDirection(StrEnum):
    PATHOGENIC = "PATHOGENIC"
    BENIGN = "BENIGN"

PATHOGENIC_CRITERIA = {
    "PVS1", "PS1", "PS2", "PS3", "PS4",
    "PM1", "PM2", "PM3", "PM4", "PM5", "PM6",
    "PP1", "PP2", "PP3", "PP4", "PP5",
}
BENIGN_CRITERIA = {
    "BA1", "BS1", "BS2", "BS3", "BS4",
    "BP1", "BP2", "BP3", "BP4", "BP5", "BP6", "BP7",
}
ALL_CRITERIA = PATHOGENIC_CRITERIA | BENIGN_CRITERIA

STRENGTH_TO_POINTS = {
    "SUPPORTING": 1,
    "MODERATE": 2,
    "STRONG": 4,
    "VERY_STRONG": 8,
}
SPECIAL_STRENGTHS = {"BA1": "STANDALONE"}

@dataclass(frozen=True)
class RuleProfile:
    profile_id: str
    version: str
    framework: str = "ACMG/AMP"
    framework_version: str = "2015"
    allow_benign_override: bool = True

ACMG2015BaselineProfile = RuleProfile(
    profile_id="ACMG_AMP_2015_BASELINE_COMBINATION",
    version="1.0.0",
)

def validate_criterion_code(code: str) -> None:
    if code not in ALL_CRITERIA:
        raise ValueError(f"Unsupported ACMG/AMP criterion code: {code}")

def validate_strength(code: str, strength: str) -> None:
    validate_criterion_code(code)
    if code in SPECIAL_STRENGTHS:
        if strength != SPECIAL_STRENGTHS[code]:
            raise ValueError(f"{code} must use strength {SPECIAL_STRENGTHS[code]}")
        return
    if strength not in STRENGTH_TO_POINTS:
        raise ValueError(f"Unsupported evidence strength: {strength}")

def validate_direction(code: str, direction: str) -> None:
    validate_criterion_code(code)
    expected = CriterionDirection.PATHOGENIC if code in PATHOGENIC_CRITERIA else CriterionDirection.BENIGN
    if direction != expected:
        raise ValueError(f"{code} must have direction {expected}")
