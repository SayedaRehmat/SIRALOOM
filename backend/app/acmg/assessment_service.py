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

    def bind(
        self,
        db: Session,
        *,
        gene: str,
        disease: str | None = None,
        specification_resource: Resource | None = None,
    ) -> tuple[SpecificationBinding, ClinGenSpecification | None]:
        specification_id = None
        specification_version = None
        if specification_resource is not None:
            if specification_resource.resource_type != "ACMG_RULE_SPECIFICATION":
                raise SpecificationBindingError(
                    "Selected ACMG runtime resource is not an ACMG_RULE_SPECIFICATION."
                )
            if specification_resource.provider.strip().upper() != "CLINGEN":
                raise SpecificationBindingError(
                    f"Selected ACMG runtime provider {specification_resource.provider!r} is not ClinGen."
                )
            metadata = dict(specification_resource.metadata_json or {})
            specification_id = str(metadata.get("specification_id") or "").strip()
            specification_version = str(metadata.get("specification_version") or "").strip()
            if not specification_id or not specification_version:
                raise SpecificationBindingError(
                    "Qualified ClinGen resource must declare specification_id and specification_version in metadata."
                )

        selection = self.selector.select(
            db,
            gene=gene,
            disease=disease,
            specification_id=specification_id,
            specification_version=specification_version,
        )
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
        specification_resource: Resource | None = None,
    ) -> AutomatedAssessmentResult:
        binding, row = self.bind(
            db,
            gene=gene,
            disease=disease,
            specification_resource=specification_resource,
        )
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

        # Evaluators may identify upstream observations, but ACMG criteria must
        # reference persisted Evidence records. Never place PopulationObservation
        # identifiers directly into CriterionAssessment.evidence_ids.
        bound_results: list[EvaluatorResult] = []
        for evaluated in evaluator_results:
            if evaluated.status != "PROPOSED" or not evaluated.applicable:
                bound_results.append(evaluated)
                continue
            if not evaluated.evidence_ids:
                bound_results.append(EvaluatorResult(
                    evaluated.criterion,
                    evaluated.applicable,
                    None,
                    evaluated.direction,
                    "REQUIRES_REVIEW",
                    "The evaluator produced a proposed criterion without persisted Evidence identifiers; human review is required.",
                    evidence_ids=(),
                    metadata={**(evaluated.metadata or {}), "evidence_binding": "MISSING"},
                ))
                continue
            evidence_ids, unresolved = _resolve_evidence_ids(
                db,
                analysis_id=analysis.id,
                variant_id=variant.id,
                source_ids=evaluated.evidence_ids,
            )
            if unresolved:
                bound_results.append(EvaluatorResult(
                    evaluated.criterion,
                    evaluated.applicable,
                    None,
                    evaluated.direction,
                    "REQUIRES_REVIEW",
                    "One or more evaluator source identifiers could not be resolved to persisted Evidence records; criterion cannot be proposed.",
                    evidence_ids=tuple(str(x) for x in evidence_ids),
                    metadata={
                        **(evaluated.metadata or {}),
                        "evidence_binding": "UNRESOLVED",
                        "unresolved_source_ids": list(unresolved),
                    },
                ))
                continue
            bound_results.append(EvaluatorResult(
                evaluated.criterion,
                evaluated.applicable,
                evaluated.strength,
                evaluated.direction,
                evaluated.status,
                evaluated.reason,
                evidence_ids=tuple(str(x) for x in evidence_ids),
                metadata={**(evaluated.metadata or {}), "evidence_binding": "RESOLVED"},
            ))

        evaluator_results = bound_results
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
            if r.applicable and r.strength is not None and r.status == "PROPOSED" and r.evidence_ids
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


def _resolve_evidence_ids(
    db: Session,
    *,
    analysis_id: UUID,
    variant_id: UUID,
    source_ids: tuple[str, ...],
) -> tuple[tuple[UUID, ...], tuple[str, ...]]:
    """Resolve evaluator source identifiers to persisted Evidence IDs.

    Population evaluators currently emit PopulationObservation IDs. This helper
    performs the only legal crossing into the ACMG evidence namespace. Evidence
    must belong to the same analysis and variant; cross-analysis/cross-variant
    evidence is never accepted.
    """
    if not source_ids:
        return (), ()
    normalized = {str(x) for x in source_ids}
    rows = db.scalars(
        select(Evidence).where(
            Evidence.analysis_id == analysis_id,
            Evidence.variant_id == variant_id,
        )
    ).all()
    resolved: list[UUID] = []
    unresolved = set(normalized)
    for row in rows:
        # The SQL predicate is the primary boundary. Re-check the ownership
        # fields defensively as well so an alternate DB adapter, test double,
        # or future query change cannot accidentally cross analysis/variant scope.
        if row.analysis_id != analysis_id or row.variant_id != variant_id:
            continue
        observation_ids = {str(x) for x in (row.observation_ids or [])}
        if observation_ids & normalized:
            resolved.append(row.id)
            unresolved -= observation_ids & normalized
    return tuple(dict.fromkeys(resolved)), tuple(sorted(unresolved))


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
