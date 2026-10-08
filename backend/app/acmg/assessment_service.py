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

from backend.app.acmg.engine import ClassificationResult, CriterionAssessment
from backend.app.acmg.classification_engine import ClassificationEngineRouter
from backend.app.acmg.combination_method import STANDARD_ACMG
from backend.app.acmg.evaluators import (
    EvaluatorConfigurationError,
    EvaluatorResult,
    evaluate_ba1_bs1,
    evaluate_pm2,
    evaluate_pp3_bp4,
    evaluate_pvs1,
)
from backend.app.acmg.specification_selection import ClinGenSpecificationSelector
from backend.app.acmg.source_assessment import (
    SourceCriterionAssessment,
    assess_source_assertions,
)
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    Annotation,
    ACMGSourceAssertion,
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
    criterion_assessments: tuple[CriterionAssessment, ...] = ()
    source_assessments: tuple[SourceCriterionAssessment, ...] = ()
    combination_method: str = STANDARD_ACMG
    combination_metadata: dict[str, Any] | None = None


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
        # Combination-method detection governs only the final combination stage.
        # Evidence evaluators and source assertions must still run when the
        # selected specification uses a method that SIRALOOM cannot execute yet.
        # This preserves all scientific evidence and routes only the
        # classification-combination decision to human review.
        engine_selection = ClassificationEngineRouter().select(row)
        combination = engine_selection.decision

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
        evaluator_assessments = [
            CriterionAssessment(
                criterion=r.criterion,
                strength=r.strength or ("SUPPORTING" if r.criterion != "BA1" else "STANDALONE"),
                direction=r.direction,
                status=r.status,
                evidence_ids=r.evidence_ids,
                reason=r.reason,
                metadata=r.metadata or {},
            )
            for r in evaluator_results
            if r.applicable and r.strength is not None and r.status == "PROPOSED" and r.evidence_ids
        ]

        source_rows = db.scalars(
            select(ACMGSourceAssertion).where(
                ACMGSourceAssertion.analysis_id == analysis.id,
                ACMGSourceAssertion.variant_id == variant.id,
            ).order_by(ACMGSourceAssertion.criterion.asc(), ACMGSourceAssertion.created_at.asc())
        ).all()
        source_results = assess_source_assertions(source_rows, row) if source_rows else ()

        source_by_id = {str(item.id): item for item in source_rows}
        source_assessments: list[CriterionAssessment] = []
        for source_result in source_results:
            if (
                source_result.status != "PROPOSED"
                or not source_result.applicable
                or source_result.strength is None
            ):
                continue
            source_assessments.append(
                CriterionAssessment(
                    # The existing baseline engine combines canonical ACMG codes.
                    # CSpec strength modifications are retained in metadata and
                    # represented by the governed strength value; they are not
                    # invented as new engine criterion codes.
                    criterion=source_result.criterion,
                    strength=source_result.strength,
                    direction=source_result.direction,
                    status="PROPOSED",
                    evidence_ids=tuple(
                        str(source_by_id[source_id].evidence_id)
                        for source_id in source_result.source_assertion_ids
                        if source_id in source_by_id
                    ),
                    reason=source_result.rationale,
                    metadata={
                        "assessment_origin": "CLINGEN_SOURCE_ASSERTION",
                        "effective_criterion": source_result.effective_criterion,
                        "source_assertion_ids": list(source_result.source_assertion_ids),
                        "specification_id": source_result.specification_id,
                        "specification_version": source_result.specification_version,
                        **(source_result.metadata or {}),
                    },
                )
            )

        merged, merge_error = _merge_criterion_assessments(
            evaluator_assessments,
            source_assessments,
        )
        combination_metadata = {
            **combination.metadata,
            "reason": combination.reason,
            "specification_id": row.specification_id,
            "specification_version": row.version,
        }

        unresolved_criteria = _unresolved_specification_criteria(
            profile=profile,
            evaluator_results=evaluator_results,
            source_results=source_results,
        )
        if unresolved_criteria:
            return AutomatedAssessmentResult(
                "REQUIRES_REVIEW",
                binding,
                tuple(evaluator_results),
                None,
                tuple(merged),
                tuple(source_results),
                combination_method=combination.method,
                combination_metadata={
                    **combination_metadata,
                    "classification_automation": "REQUIRES_REVIEW",
                    "review_reason": "SPECIFICATION_CRITERION_NOT_EXECUTABLE",
                    "unresolved_criteria": list(unresolved_criteria),
                },
            )

        if merge_error:
            return AutomatedAssessmentResult(
                "REQUIRES_REVIEW",
                binding,
                tuple(evaluator_results),
                None,
                tuple(merged),
                tuple(source_results),
                combination_method=combination.method,
                combination_metadata={
                    **combination_metadata,
                    "classification_automation": "REQUIRES_REVIEW",
                    "review_reason": "CONFLICTING_CRITERION_PROPOSALS",
                    "merge_error": merge_error,
                },
            )

        if not merged:
            return AutomatedAssessmentResult(
                "REQUIRES_REVIEW",
                binding,
                tuple(evaluator_results),
                None,
                (),
                tuple(source_results),
                combination_method=combination.method,
                combination_metadata={
                    **combination_metadata,
                    "classification_automation": "REQUIRES_REVIEW",
                    "review_reason": "NO_PROPOSED_CRITERIA",
                },
            )

        # Unsupported/alternative combination methods do not invalidate the
        # evidence or criterion assessments. They only prevent SIRALOOM from
        # making an automated final combination until a validated executor exists.
        if engine_selection.engine is None:
            return AutomatedAssessmentResult(
                "REQUIRES_REVIEW",
                binding,
                tuple(evaluator_results),
                None,
                tuple(merged),
                tuple(source_results),
                combination_method=combination.method,
                combination_metadata={
                    **combination_metadata,
                    "classification_automation": "REQUIRES_REVIEW",
                    "review_reason": "COMBINATION_ENGINE_NOT_AVAILABLE",
                    "engine_selection_reason": engine_selection.reason,
                },
            )

        classification = engine_selection.engine.classify(merged)
        return AutomatedAssessmentResult(
            "PROPOSED",
            binding,
            tuple(evaluator_results),
            classification,
            tuple(merged),
            tuple(source_results),
            combination_method=combination.method,
            combination_metadata={
                **combination_metadata,
                "classification_automation": "PROPOSED",
            },
        )


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

        # Serialize automated ACMG persistence for the analysis. This protects
        # the unique current assessment rows and classification-version allocation
        # when two workers assess the same variant concurrently.
        locked_analysis = db.get(Analysis, analysis.id, with_for_update=True)
        if locked_analysis is None:
            raise ValueError("Analysis not found")
        db.refresh(locked_analysis, with_for_update=True)
        analysis = locked_analysis

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

        # Persist source-derived proposed criteria that were not already represented
        # by an evaluator row. Source assertions remain the provenance authority;
        # this ACMGAssessment is only the reconciled criterion proposal.
        for assessed in result.criterion_assessments:
            if assessed.criterion in {
                item.criterion for item in result.evaluator_results
            }:
                continue
            existing = db.scalar(
                select(ACMGAssessment).where(
                    ACMGAssessment.variant_id == variant.id,
                    ACMGAssessment.analysis_id == analysis.id,
                    ACMGAssessment.criterion == assessed.criterion,
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
                criterion=assessed.criterion,
                state=assessed.status,
            )
            row.automated_assessment = {
                "applicable": True,
                "strength": assessed.strength,
                "direction": assessed.direction,
                "status": assessed.status,
                "evidence_ids": list(assessed.evidence_ids),
                "reason": assessed.reason,
                "metadata": assessed.metadata,
            }
            row.state = assessed.status
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
                latest = db.scalar(
                    select(Classification)
                    .where(
                        Classification.analysis_id == analysis.id,
                        Classification.variant_id == variant.id,
                    )
                    .order_by(Classification.version.desc())
                    .limit(1)
                )
                next_version = (latest.version if latest else 0) + 1
                db.add(
                    Classification(
                        id=uuid4(),
                        variant_id=variant.id,
                        analysis_id=analysis.id,
                        framework_name=classification.framework,
                        framework_version=classification.framework_version,
                        specification_provider="ClinGen",
                        specification_id=result.binding.specification_id,
                        specification_version=result.binding.specification_version,
                        result=classification.classification,
                        criterion_ids=criterion_ids,
                        state=classification.state,
                        review_status="PENDING",
                        version=next_version,
                        supersedes_classification_id=latest.id if latest else None,
                    )
                )
        db.flush()


def _unresolved_specification_criteria(
    *,
    profile: dict[str, Any],
    evaluator_results: list[EvaluatorResult],
    source_results: tuple[SourceCriterionAssessment, ...],
) -> tuple[str, ...]:
    """Identify configured criteria for which SIRALOOM has no assessment.

    A specification may define many ACMG/AMP criteria while SIRALOOM currently
    has automated evaluators for only a subset. A final combination from the
    subset would be unsafe because an unassessed criterion could materially
    change the classification. A criterion is considered accounted for when an
    evaluator or governed ClinGen source assessment produced a result, including
    an explicit non-applicable outcome.
    """
    configured = {
        str(key).upper()
        for key in profile
        if _looks_like_acmg_criterion(key)
    }
    if not configured:
        return ()

    assessed = {str(result.criterion).upper() for result in evaluator_results}
    assessed.update(str(result.criterion).upper() for result in source_results)
    return tuple(sorted(configured - assessed))


def _looks_like_acmg_criterion(value: object) -> bool:
    """Return True for canonical ACMG/AMP-style criterion keys only."""
    if not isinstance(value, str):
        return False
    import re

    return bool(
        re.fullmatch(
            r"(?:PVS1|PS[1-4]|PM[1-6]|PP[1-5]|BA1|BS[1-4]|BP[1-7])(?:_[A-Z]+)?",
            value.upper(),
        )
    )

def _merge_criterion_assessments(
    evaluator_assessments: list[CriterionAssessment],
    source_assessments: list[CriterionAssessment],
) -> tuple[list[CriterionAssessment], str | None]:
    """Merge local evaluator and ClinGen source proposals deterministically.

    A canonical ACMG criterion may occur from both paths. Compatible proposals
    are deduplicated; conflicting strength, direction, or evidence are never
    silently resolved. The caller must route such a conflict to human review.
    """
    merged: dict[str, CriterionAssessment] = {}
    conflicts: list[str] = []

    for assessment in [*evaluator_assessments, *source_assessments]:
        key = assessment.criterion
        existing = merged.get(key)
        if existing is None:
            merged[key] = assessment
            continue

        compatible = (
            existing.strength == assessment.strength
            and existing.direction == assessment.direction
        )
        if not compatible:
            conflicts.append(
                f"{key}: existing={existing.strength}/{existing.direction}, "
                f"incoming={assessment.strength}/{assessment.direction}"
            )
            continue

        merged[key] = CriterionAssessment(
            criterion=key,
            strength=existing.strength,
            direction=existing.direction,
            status="PROPOSED",
            evidence_ids=tuple(dict.fromkeys((*existing.evidence_ids, *assessment.evidence_ids))),
            reason="Compatible criterion proposals were deduplicated across evidence sources.",
            metadata={
                **existing.metadata,
                "merge": "DEDUPLICATED_COMPATIBLE_PROPOSALS",
                "merged_metadata": [existing.metadata, assessment.metadata],
            },
        )

    if conflicts:
        return list(merged.values()), "Conflicting criterion proposals require human review: " + "; ".join(conflicts)
    return list(merged.values()), None


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
