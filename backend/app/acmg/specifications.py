"""Registry for versioned ACMG/ClinGen criterion specifications.

No generic clinical threshold is hard-coded here. Specifications are data-driven
and must be explicitly selected for a gene/disease context before automated use.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CriterionSpecification:
    specification_id: str
    version: str
    provider: str
    framework: str
    criteria: dict[str, dict[str, Any]]
    scope: dict[str, Any]


BASELINE_SPEC = CriterionSpecification(
    specification_id="SIRALOOM_ACMG_BASELINE_SAFETY_PROFILE",
    version="1.0.0",
    provider="SIRALOOM",
    framework="ACMG/AMP",
    criteria={},
    scope={"purpose": "schema_and_safety_only", "clinical_use": False},
)


def require_configured_specification(spec: CriterionSpecification, criterion: str) -> dict[str, Any]:
    if criterion not in spec.criteria:
        raise ValueError(
            f"No criterion-specific specification is configured for {criterion}; "
            "generic clinical automation is intentionally disabled."
        )
    return spec.criteria[criterion]
