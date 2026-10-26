from enum import StrEnum
from typing import Any


class EvidenceStrength(StrEnum):
    VERY_STRONG = "VERY_STRONG"
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    SUPPORTING = "SUPPORTING"

ACMG_CRITERIA = {
    "PATHOGENIC": ["PVS1", "PS1", "PS2", "PS3", "PS4", "PM1", "PM2", "PM3", "PM4", "PM5", "PM6", "PP1", "PP2", "PP3", "PP4"],
    "BENIGN": ["BA1", "BS1", "BS2", "BS3", "BS4", "BP1", "BP2", "BP3", "BP4", "BP5", "BP7"],
}

def proposed_classification(criteria: list[dict[str, Any]]) -> str:
    raise RuntimeError(
        "The legacy domain classifier is disabled because it lacks validated, "
        "criterion-level evidence and review state. Use the versioned ACMG "
        "assessment service with persisted evidence and an approved specification."
    )
