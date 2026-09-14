from enum import StrEnum
from typing import Any

class EvidenceStrength(StrEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    SUPPORTING = "SUPPORTING"

ACMG_CRITERIA = {
    "PATHOGENIC": ["PVS1", "PS1", "PS2", "PS3", "PS4", "PM1", "PM2", "PM3", "PM4", "PM5", "PM6", "PP1", "PP2", "PP3", "PP4", "PP5"],
    "BENIGN": ["BA1", "BS1", "BS2", "BS3", "BS4", "BP1", "BP2", "BP3", "BP4", "BP5", "BP6", "BP7"],
}

def proposed_classification(criteria: list[dict[str, Any]]) -> str:
    # Conservative placeholder decision layer: this function is intentionally NOT a full ACMG rules engine.
    # It only demonstrates state flow until criterion-specific specifications are implemented and validated.
    codes = {c.get("criterion") for c in criteria if c.get("strength")}
    if "PVS1" in codes and ("PM2" in codes or "PP3" in codes):
        return "LIKELY_PATHOGENIC"
    if "BA1" in codes or {"BS1", "BS2"} & codes:
        return "LIKELY_BENIGN"
    return "VUS"
