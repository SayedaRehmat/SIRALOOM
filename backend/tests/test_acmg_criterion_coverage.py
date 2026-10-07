from backend.app.acmg.assessment_service import _unresolved_specification_criteria
from backend.app.acmg.evaluators import EvaluatorResult
from backend.app.acmg.source_assessment import SourceCriterionAssessment


def test_unassessed_configured_criterion_requires_review():
    evaluator = EvaluatorResult(
        criterion="PM2",
        applicable=True,
        strength="SUPPORTING",
        direction="PATHOGENIC",
        status="PROPOSED",
        reason="rarity",
        evidence_ids=("e1",),
        metadata={},
    )

    unresolved = _unresolved_specification_criteria(
        profile={"PM2": {}, "PS3": {}},
        evaluator_results=[evaluator],
        source_results=(),
    )

    assert unresolved == ("PS3",)


def test_source_assessment_counts_as_criterion_coverage():
    source = SourceCriterionAssessment(
        criterion="PS3",
        effective_criterion="PS3",
        applicable=False,
        strength=None,
        direction="NEUTRAL",
        status="NOT_APPLICABLE",
        source_assertion_ids=(),
        specification_id="GN000",
        specification_version="1.0",
        rationale="Not applicable",
        metadata={},
    )

    unresolved = _unresolved_specification_criteria(
        profile={"PM2": {}, "PS3": {}},
        evaluator_results=[],
        source_results=(source,),
    )

    assert unresolved == ("PM2",)


def test_non_criterion_profile_keys_are_not_treated_as_missing_evidence():
    unresolved = _unresolved_specification_criteria(
        profile={"rules": "standard", "metadata": {}, "PM2": {}},
        evaluator_results=[],
        source_results=(),
    )

    assert unresolved == ("PM2",)
