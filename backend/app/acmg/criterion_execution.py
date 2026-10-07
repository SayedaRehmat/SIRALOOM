"""Criterion-level execution contracts for governed ACMG specifications.

This module defines the execution boundary between a ClinGen/CSpec rule and
SIRALOOM's evidence evaluators. It deliberately contains no biological scoring
or modified/point/Bayesian mathematics. Those belong to validated criterion
executors and combination engines.

The contract makes it possible to distinguish:
- a criterion being in scope,
- a criterion being explicitly Not Applicable,
- a criterion being assessed but not met,
- a criterion producing a proposed assessment,
- a criterion requiring human review because SIRALOOM cannot execute the
  governing rule.

This is an execution contract, not a classification engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from backend.app.acmg.engine import CriterionAssessment
from backend.app.acmg.source_assessment import SourceCriterionAssessment

EXECUTABLE = "EXECUTABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
NOT_MET = "NOT_MET"
PROPOSED = "PROPOSED"
REQUIRES_REVIEW = "REQUIRES_REVIEW"


@dataclass(frozen=True)
class CriterionExecutionContext:
    """Inputs available to a criterion executor.

    Evidence is referenced by durable IDs rather than copied into the contract.
    The executor may use normalized variant/context data and governed evidence
    records, but it must report exactly which evidence IDs it consumed.
    """

    variant_id: str
    analysis_id: str
    criterion: str
    specification_id: str
    specification_version: str
    rule: dict[str, Any]
    evidence: tuple[dict[str, Any], ...] = ()
    variant_context: dict[str, Any] = field(default_factory=dict)
    case_context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CriterionExecutionDecision:
    """Durable, reviewable result of attempting one criterion rule."""

    criterion: str
    effective_criterion: str | None
    status: str
    applicable: bool
    strength: str | None
    direction: str | None
    specification_id: str
    specification_version: str
    executor_id: str | None
    executor_version: str | None
    evidence_ids: tuple[str, ...] = ()
    rationale: str = ""
    review_reason: str | None = None
    modification_type: str | None = None
    dependencies: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_criterion_assessment(self) -> CriterionAssessment | None:
        """Convert only an executable proposed result into the baseline shape.

        A criterion execution decision must not be silently downgraded into an
        ACMGEngine assessment when it is review-required, not applicable, or
        otherwise non-executable.
        """
        if self.status != PROPOSED or not self.strength or not self.direction:
            return None
        return CriterionAssessment(
            criterion=self.effective_criterion or self.criterion,
            strength=self.strength,
            direction=self.direction,
            status=PROPOSED,
            evidence_ids=self.evidence_ids,
            reason=self.rationale,
            metadata={
                **self.metadata,
                "criterion_execution": {
                    "criterion": self.criterion,
                    "effective_criterion": self.effective_criterion,
                    "specification_id": self.specification_id,
                    "specification_version": self.specification_version,
                    "executor_id": self.executor_id,
                    "executor_version": self.executor_version,
                    "modification_type": self.modification_type,
                    "dependencies": list(self.dependencies),
                    "provenance": self.provenance,
                },
            },
        )

    @classmethod
    def from_source_assessment(
        cls,
        assessment: SourceCriterionAssessment,
        *,
        executor_id: str | None = "CLINGEN_SOURCE_ASSERTION",
        executor_version: str | None = None,
        evidence_ids: tuple[str, ...] | None = None,
    ) -> "CriterionExecutionDecision":
        """Adapt the existing source-assessment result into this contract.

        This preserves the source assessment as the authoritative observation
        and does not invent an evaluator for rules that SIRALOOM cannot execute.
        """
        rule = assessment.metadata.get("specification_rule", {})
        modification_type = None
        if isinstance(rule, dict):
            modification_type = (
                rule.get("modification_type")
                or rule.get("modificationType")
            )
        review_reason = None
        if assessment.status == REQUIRES_REVIEW:
            review_reason = assessment.metadata.get("review_reason") or assessment.rationale
        return cls(
            criterion=assessment.criterion,
            effective_criterion=assessment.effective_criterion,
            status=assessment.status,
            applicable=assessment.applicable,
            strength=assessment.strength,
            direction=assessment.direction,
            specification_id=assessment.specification_id,
            specification_version=assessment.specification_version,
            executor_id=executor_id,
            executor_version=executor_version,
            evidence_ids=evidence_ids if evidence_ids is not None else assessment.source_assertion_ids,
            rationale=assessment.rationale,
            review_reason=review_reason,
            modification_type=str(modification_type) if modification_type else None,
            dependencies=tuple(
                str(item)
                for item in (
                    rule.get("dependencies", [])
                    if isinstance(rule, dict)
                    else []
                )
            ),
            provenance={
                "source_assertion_ids": list(assessment.source_assertion_ids),
            },
            metadata=dict(assessment.metadata),
        )


class CriterionExecutor(Protocol):
    """Provider contract for one governed criterion execution strategy."""

    executor_id: str
    executor_version: str

    def supports(self, context: CriterionExecutionContext) -> bool:
        """Return whether this executor can scientifically execute this rule."""

    def execute(
        self, context: CriterionExecutionContext
    ) -> CriterionExecutionDecision:
        """Evaluate the criterion and return a reviewable decision."""


class CriterionExecutorRegistry:
    """Exact-match registry for validated criterion executors.

    A missing executor is a normal capability state. It never falls back to a
    generic ACMG rule or another executor with superficially similar semantics.
    """

    def __init__(self, executors: Sequence[CriterionExecutor] = ()) -> None:
        self._executors: dict[str, CriterionExecutor] = {}
        for executor in executors:
            self.register(executor)

    def register(self, executor: CriterionExecutor) -> None:
        key = executor.executor_id.strip()
        if not key:
            raise ValueError("Criterion executor ID cannot be empty")
        if key in self._executors:
            raise ValueError(f"Duplicate criterion executor: {key}")
        self._executors[key] = executor

    def select(
        self, context: CriterionExecutionContext
    ) -> CriterionExecutor | None:
        """Select the first explicitly supporting registered executor."""
        for executor in self._executors.values():
            if executor.supports(context):
                return executor
        return None

    def execute(
        self, context: CriterionExecutionContext
    ) -> CriterionExecutionDecision:
        executor = self.select(context)
        if executor is None:
            return CriterionExecutionDecision(
                criterion=context.criterion,
                effective_criterion=None,
                status=REQUIRES_REVIEW,
                applicable=True,
                strength=None,
                direction=None,
                specification_id=context.specification_id,
                specification_version=context.specification_version,
                executor_id=None,
                executor_version=None,
                rationale=(
                    "No validated criterion executor is registered for the "
                    "active specification rule."
                ),
                review_reason="CRITERION_EXECUTOR_NOT_AVAILABLE",
                provenance={
                    "specification_id": context.specification_id,
                    "specification_version": context.specification_version,
                },
                metadata={"rule": context.rule},
            )
        return executor.execute(context)


__all__ = [
    "CriterionExecutionContext",
    "CriterionExecutionDecision",
    "CriterionExecutor",
    "CriterionExecutorRegistry",
    "EXECUTABLE",
    "NOT_APPLICABLE",
    "NOT_MET",
    "PROPOSED",
    "REQUIRES_REVIEW",
]
