from backend.app.acmg.criterion_execution import (
    CriterionExecutionContext,
    CriterionExecutionDecision,
    CriterionExecutorRegistry,
    PROPOSED,
    REQUIRES_REVIEW,
)
from backend.app.acmg.engine import CriterionAssessment


def test_missing_executor_requires_review_without_fallback():
    context = CriterionExecutionContext(
        variant_id="v1",
        analysis_id="a1",
        criterion="PP3",
        specification_id="GN123",
        specification_version="1.0",
        rule={"modification_type": "disease-specific", "strength": "SUPPORTING"},
    )

    result = CriterionExecutorRegistry().execute(context)

    assert result.status == REQUIRES_REVIEW
    assert result.review_reason == "CRITERION_EXECUTOR_NOT_AVAILABLE"
    assert result.strength is None
    assert result.to_criterion_assessment() is None


class _PP3Executor:
    executor_id = "TEST_PP3_EXECUTOR"
    executor_version = "1.0"

    def supports(self, context):
        return context.criterion == "PP3"

    def execute(self, context):
        return CriterionExecutionDecision(
            criterion="PP3",
            effective_criterion="PP3",
            status=PROPOSED,
            applicable=True,
            strength="SUPPORTING",
            direction="PATHOGENIC",
            specification_id=context.specification_id,
            specification_version=context.specification_version,
            executor_id=self.executor_id,
            executor_version=self.executor_version,
            evidence_ids=("e1",),
            rationale="Validated test executor.",
            provenance={"test": True},
        )


def test_validated_executor_produces_baseline_assessment_only_when_proposed():
    context = CriterionExecutionContext(
        variant_id="v1",
        analysis_id="a1",
        criterion="PP3",
        specification_id="GN123",
        specification_version="1.0",
        rule={"strength": "SUPPORTING"},
    )

    result = CriterionExecutorRegistry([_PP3Executor()]).execute(context)
    assessment = result.to_criterion_assessment()

    assert result.status == PROPOSED
    assert assessment is not None
    assert isinstance(assessment, CriterionAssessment)
    assert assessment.criterion == "PP3"
    assert assessment.strength == "SUPPORTING"
    assert assessment.evidence_ids == ("e1",)


def test_review_decision_never_becomes_classification_engine_input():
    decision = CriterionExecutionDecision(
        criterion="PP3",
        effective_criterion="PP3",
        status=REQUIRES_REVIEW,
        applicable=True,
        strength="SUPPORTING",
        direction="PATHOGENIC",
        specification_id="GN123",
        specification_version="1.0",
        executor_id=None,
        executor_version=None,
        rationale="Requires review.",
        review_reason="DEPENDENCY_NOT_SATISFIED",
    )

    assert decision.to_criterion_assessment() is None


def test_source_assessment_adapter_preserves_provenance():
    from backend.app.acmg.source_assessment import SourceCriterionAssessment

    source = SourceCriterionAssessment(
        criterion="PM2",
        effective_criterion="PM2",
        applicable=True,
        strength="MODERATE",
        direction="PATHOGENIC",
        status=PROPOSED,
        source_assertion_ids=("assertion-1",),
        specification_id="GN123",
        specification_version="1.0",
        rationale="Source strength allowed.",
        metadata={
            "specification_rule": {
                "modification_type": "strength",
                "dependencies": ["population_frequency"],
            }
        },
    )

    decision = CriterionExecutionDecision.from_source_assessment(source)
    assert decision.executor_id == "CLINGEN_SOURCE_ASSERTION"
    assert decision.modification_type == "strength"
    assert decision.dependencies == ("population_frequency",)
    assert decision.evidence_ids == ("assertion-1",)
