from backend.app.acmg.assessment_service import _merge_criterion_assessments
from backend.app.acmg.engine import CriterionAssessment


def assessment(criterion="PS3", strength="SUPPORTING", direction="PATHOGENIC", evidence_ids=("e1",), metadata=None):
    return CriterionAssessment(
        criterion=criterion,
        strength=strength,
        direction=direction,
        evidence_ids=evidence_ids,
        metadata=metadata or {},
    )


def test_compatible_source_and_local_proposals_are_deduplicated():
    merged, error = _merge_criterion_assessments(
        [assessment(evidence_ids=("local-evidence",))],
        [assessment(evidence_ids=("source-evidence",), metadata={"assessment_origin": "CLINGEN_SOURCE_ASSERTION"})],
    )

    assert error is None
    assert len(merged) == 1
    assert merged[0].criterion == "PS3"
    assert merged[0].strength == "SUPPORTING"
    assert merged[0].evidence_ids == ("local-evidence", "source-evidence")
    assert merged[0].metadata["merge"] == "DEDUPLICATED_COMPATIBLE_PROPOSALS"


def test_conflicting_strengths_require_review_instead_of_being_silently_resolved():
    merged, error = _merge_criterion_assessments(
        [assessment(strength="STRONG", evidence_ids=("local-evidence",))],
        [assessment(strength="SUPPORTING", evidence_ids=("source-evidence",))],
    )

    assert len(merged) == 1
    assert error is not None
    assert "PS3" in error
    assert "STRONG" in error
    assert "SUPPORTING" in error


def test_conflicting_directions_require_review():
    merged, error = _merge_criterion_assessments(
        [assessment(criterion="PS3", direction="PATHOGENIC")],
        [assessment(criterion="PS3", direction="BENIGN")],
    )

    assert len(merged) == 1
    assert error is not None
    assert "PS3" in error


def test_distinct_criteria_are_preserved():
    merged, error = _merge_criterion_assessments(
        [assessment("PS3")],
        [assessment("PM2", strength="MODERATE")],
    )

    assert error is None
    assert {item.criterion for item in merged} == {"PS3", "PM2"}
