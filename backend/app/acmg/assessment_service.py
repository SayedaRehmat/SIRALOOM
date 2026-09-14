"""Specification-aware ACMG assessment orchestration.

This module is deliberately conservative:
- A ClinGen specification must be explicitly validated for automation.
- Only criteria with structured configuration supported by a registered evaluator
  are executed automatically.
- Unsupported, ambiguous, unconfigured, or alternative-combination specifications
  do not produce a final clinical classification.
- Automated results are persisted as PROPOSED and remain reviewable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from backend.app.acmg.engine import ACMGEngine, ClassificationResult, CriterionAssessment
from backend.app.acmg.evaluators import (
    EvaluatorConfigurationError,
    EvaluatorResult,
    evaluate_ba1_bs1,
    evaluate_pm2,
    evaluate_pp3_bp4,
    evaluate_pvs1,
)
from backend.app.acmg.specification_selection import ClinGenSpecificationSelector
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    Classification,
    ClinGenSpecification,
    Evidence,
    PopulationObservation,
    Resource,
    Variant,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

SUPPORTED_AUTOMATED_CRITERIA = {"PM2", "BA1", "BS1", "PP3", "BP4", "PVS1"}
ALTERNATIVE_COMBINATION_KEYS = {
    "combining_method",
    "combiningMethod",
    "point_based",
    "pointBased",
    "points",
}


@dataclass(frozen=True)
class SpecificationBinding:
    status: str
    specification_db_id: UUID | None
    specification_id: str | None
    specification_version: str | None
    reason: str


@dataclass(frozen=True)
class AutomatedAssessmentResult:
    status: str
    binding: SpecificationBinding
    evaluator_results: tuple[EvaluatorResult, ...]
    classification: ClassificationResult | None


class SpecificationBindingError(ValueError):
    pass


class ACMGSpecificationAssessmentService:
    """Resolve a validated ClinGen specification and evaluate supported criteria."""

    def __init__(self, selector: ClinGenSpecificationSelector | None = None):
        self.selector = selector or ClinGenSpecificationSelector()

    def bind(self, db: Session, *, gene: str, disease: str | None = None) -> tuple[SpecificationBinding, ClinGenSpecification | None]:
        selection = self.selector.select(db, gene=gene, disease=disease)
        if selection.status != "SELECTED" or selection.selected is None:
            return (
                SpecificationBinding(
                    status=selection.status,
                    specification_db_id=None,
                    specification_id=selection.selected.specification_id if selection.selected else None,
                    specification_version=selection.selected.version if selection.selected else None,
                    reason=selection.reason,
                ),
                None,
            )
        row = db.get(ClinGenSpecification, UUID(selection.selected.id))
        if row is None:
            raise SpecificationBindingError("Selected ClinGen specification disappeared before assessment")
        if not row.validated_for_automation or row.validation_status != "APPROVED_FOR_AUTOMATION":
            raise SpecificationBindingError("Selected specification is not approved for automation")
        return (
            SpecificationBinding(
                status="SELECTED",
                specification_db_id=row.id,
                specification_id=row.specification_id,
                specification_version=row.version,
                reason=selection.reason,
            ),
            row,
        )

    def assess_variant(
        self,
        db: Session,
        *,
        analysis: Analysis,
        variant: Variant,
        annotation: Annotation,
        population_rows: list[PopulationObservation],
        resource_rows: dict[UUID, Resource],
        gene: str,
        disease: str | None = None,
    ) -> AutomatedAssessmentResult:
        binding, row = self.bind(db, gene=gene, disease=disease)
        if binding.status != "SELECTED" or row is None:
            return AutomatedAssessmentResult(binding.status, binding, tuple(), None)

        profile = dict(row.criteria or {})
        if _has_alternative_combination(profile):
            return AutomatedAssessmentResult(
                "REQUIRES_REVIEW",
                binding,
                tuple(),
                None,
            )

        normalized = (annotation.payload or {}).get("normalized") or {}
        variant_context = _variant_context(normalized)
        predictor_context = (normalized.get("computational") or {}) | (normalized.get("splice") or {})
        observations = [
            _population_dict(obs, resource_rows.get(obs.resource_id))
            for obs in population_rows
        ]

        evaluator_results: list[EvaluatorResult] = []
        for criterion in sorted(set(profile) & SUPPORTED_AUTOMATED_CRITERIA):
            cfg = profile.get(criterion)
            if not isinstance(cfg, dict):
                continue
            try:
                if criterion == "PM2":
                    result = evaluate_pm2(observations, profile=profile)
                elif criterion in {"BA1", "BS1"}:
                    result = evaluate_ba1_bs1(observations, criterion=criterion, profile=profile)
                elif criterion in {"PP3", "BP4"}:
                    result = evaluate_pp3_bp4(predictor_context, criterion=criterion, profile=profile)
                elif criterion == "PVS1":
                    result = evaluate_pvs1(variant_context, profile=profile)
                else:  # pragma: no cover - guarded by registry
                    continue
            except EvaluatorConfigurationError:
                # A specification that declares a criterion without enough structured
                # configuration cannot be safely automated.
                continue
            evaluator_results.append(result)

        proposed_assessments = [
            CriterionAssessment(
                criterion=r.criterion,
                strength=r.strength or "SUPPORTING" if r.criterion != "BA1" else "STANDALONE",
                direction=r.direction,
                status=r.status,
                evidence_ids=r.evidence_ids,
                reason=r.reason,
                metadata=r.metadata or {},
            )
            for r in evaluator_results
            if r.applicable and r.strength is not None and r.status == "PROPOSED"
        ]

        if not proposed_assessments:
            return AutomatedAssessmentResult("REQUIRES_REVIEW", binding, tuple(evaluator_results), None)

        classification = ACMGEngine().classify(proposed_assessments)
        return AutomatedAssessmentResult("PROPOSED", binding, tuple(evaluator_results), classification)

    def persist(
        self,
        db: Session,
        *,
        analysis: Analysis,
        variant: Variant,
        result: AutomatedAssessmentResult,
    ) -> None:
        if result.binding.status != "SELECTED":
            return
        classification = result.classification
        for evaluated in result.evaluator_results:
            existing = db.scalar(
                select(ACMGAssessment).where(
                    ACMGAssessment.variant_id == variant.id,
                    ACMGAssessment.analysis_id == analysis.id,
                    ACMGAssessment.criterion == evaluated.criterion,
                )
            )
            row = existing or ACMGAssessment(
                id=uuid4(),
                variant_id=variant.id,
                analysis_id=analysis.id,
                framework_name="ACMG/AMP",
                framework_version="2015",
                specification_provider="ClinGen",
                specification_id=result.binding.specification_id,
                specification_version=result.binding.specification_version,
                criterion=evaluated.criterion,
                state=evaluated.status,
            )
            row.specification_provider = "ClinGen"
            row.specification_id = result.binding.specification_id
            row.specification_version = result.binding.specification_version
            row.automated_assessment = {
                "applicable": evaluated.applicable,
                "strength": evaluated.strength,
                "direction": evaluated.direction,
                "status": evaluated.status,
                "evidence_ids": list(evaluated.evidence_ids),
                "reason": evaluated.reason,
                "metadata": evaluated.metadata or {},
            }
            row.state = evaluated.status
            db.add(row)

        if classification is not None:
            criterion_ids: list[str] = []
            for assessed in classification.criteria:
                row = db.scalar(
                    select(ACMGAssessment).where(
                        ACMGAssessment.variant_id == variant.id,
                        ACMGAssessment.analysis_id == analysis.id,
                        ACMGAssessment.criterion == assessed.criterion,
                    )
                )
                if row:
                    criterion_ids.append(str(row.id))
            existing = db.scalar(
                select(Classification).where(
                    Classification.variant_id == variant.id,
                    Classification.analysis_id == analysis.id,
                    Classification.framework_name == classification.framework,
                    Classification.framework_version == classification.framework_version,
                    Classification.specification_id == result.binding.specification_id,
                    Classification.specification_version == result.binding.specification_version,
                    Classification.result == classification.classification,
                    Classification.state == classification.state,
                ).order_by(Classification.version.desc())
            )
            if existing is None or existing.criterion_ids != criterion_ids:
                db.add(
                    Classification(
                        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
                        framework_name=classification.framework, framework_version=classification.framework_version,
                        specification_provider="ClinGen", specification_id=result.binding.specification_id,
                        specification_version=result.binding.specification_version, result=classification.classification,
                        criterion_ids=criterion_ids, state=classification.state, review_status="PENDING",
                    )
                )
        db.flush()


def _has_alternative_combination(profile: dict[str, Any]) -> bool:
    for key in ALTERNATIVE_COMBINATION_KEYS:
        if key not in profile:
            continue
        value = profile.get(key)
        if value in (None, "", False, "STANDARD_ACMG_AMP_2015", "BASELINE_ACMG_AMP_2015"):
            continue
        return True
    return False


def _variant_context(normalized: dict[str, Any]) -> dict[str, Any]:
    effect = normalized.get("effect")
    consequence = effect
    if consequence is None:
        terms = normalized.get("hgvs_consequences") or []
        if isinstance(terms, list) and terms:
            first = terms[0]
            if isinstance(first, dict):
                consequence = first.get("consequence") or first.get("term") or first.get("effect")
            elif isinstance(first, str):
                consequence = first
    return {"consequence": consequence}


def _population_dict(obs: PopulationObservation, resource: Resource | None) -> dict[str, Any]:
    return {
        "observation_id": str(obs.id),
        "population_level": obs.population_level,
        "population_code": obs.population_code,
        "population_label": obs.population_label,
        "allele_count": obs.allele_count,
        "allele_number": obs.allele_number,
        "allele_frequency": obs.allele_frequency,
        "homozygote_count": obs.homozygote_count,
        "availability": obs.availability,
        "quality_status": obs.quality_status,
        "resource_name": resource.name if resource else None,
        "resource_version": resource.version if resource else None,
    }
