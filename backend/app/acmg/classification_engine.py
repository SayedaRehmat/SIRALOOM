"""Classification engine contracts and governed routing.

Evidence generation and criterion assessment happen before this layer. A
classification engine may only combine already-assessed criteria according to
its own validated framework/specification. Unsupported methods return no engine
so the workflow can retain evidence and route classification to review.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from backend.app.acmg.combination_method import (
    BAYESIAN,
    MODIFIED_ACMG,
    POINT_BASED,
    STANDARD_ACMG,
    CombinationMethodDecision,
    detect_combination_method,
)
from backend.app.acmg.engine import ACMGEngine, ClassificationResult, CriterionAssessment


class ClassificationEngine(Protocol):
    engine_id: str
    framework: str
    framework_version: str

    def classify(
        self, assessments: Sequence[CriterionAssessment]
    ) -> ClassificationResult:
        """Combine explicit criterion assessments into a proposed result."""


class ACMG2015ClassificationEngine:
    """Adapter exposing the existing validated baseline engine."""

    engine_id = "ACMG_AMP_2015"
    framework = "ACMG/AMP"
    framework_version = "2015"

    def __init__(self) -> None:
        self._engine = ACMGEngine()

    def classify(
        self, assessments: Sequence[CriterionAssessment]
    ) -> ClassificationResult:
        return self._engine.classify(list(assessments))


@dataclass(frozen=True)
class ClassificationEngineSelection:
    decision: CombinationMethodDecision
    engine: ClassificationEngine | None
    reason: str


class ClassificationEngineRouter:
    """Route a governed combination method to a validated engine.

    Only ACMG/AMP 2015 is executable today. Alternative ClinGen methods are
    deliberately represented as unavailable engines, not approximated by the
    baseline rules.
    """

    def __init__(
        self,
        *,
        standard_engine: ClassificationEngine | None = None,
    ) -> None:
        self._standard_engine = standard_engine or ACMG2015ClassificationEngine()

    def select(self, specification: object) -> ClassificationEngineSelection:
        decision = detect_combination_method(specification)

        if decision.method == STANDARD_ACMG and decision.executable:
            return ClassificationEngineSelection(
                decision=decision,
                engine=self._standard_engine,
                reason="Validated ACMG/AMP 2015 combination engine is available.",
            )

        return ClassificationEngineSelection(
            decision=decision,
            engine=None,
            reason=(
                "No validated SIRALOOM classification engine is registered for "
                f"combination method {decision.method}; criterion evidence is "
                "retained and classification is routed to human review."
            ),
        )


__all__ = [
    "ACMG2015ClassificationEngine",
    "ClassificationEngine",
    "ClassificationEngineRouter",
    "ClassificationEngineSelection",
]
