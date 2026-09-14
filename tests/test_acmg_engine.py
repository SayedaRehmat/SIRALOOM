import pytest

from backend.app.acmg.engine import ACMGEngine, CriterionAssessment
from backend.app.acmg.rules import CriterionDirection


def P(code: str, strength: str, *ids: str):
    return CriterionAssessment(code, strength, CriterionDirection.PATHOGENIC, evidence_ids=tuple(ids), reason="benchmark")


def B(code: str, strength: str, *ids: str):
    return CriterionAssessment(code, strength, CriterionDirection.BENIGN, evidence_ids=tuple(ids), reason="benchmark")


def test_pathogenic_baseline_combinations():
    e = ACMGEngine()
    assert e.classify([P("PVS1", "VERY_STRONG"), P("PS1", "STRONG")]).classification == "PATHOGENIC"
    assert e.classify([P("PVS1", "VERY_STRONG"), P("PM2", "MODERATE"), P("PM3", "MODERATE")]).classification == "PATHOGENIC"
    assert e.classify([P("PVS1", "VERY_STRONG"), P("PM2", "MODERATE"), P("PP3", "SUPPORTING")]).classification == "PATHOGENIC"
    assert e.classify([P("PS1", "STRONG"), P("PS2", "STRONG")]).classification == "PATHOGENIC"


def test_likely_pathogenic_baseline_combinations():
    e = ACMGEngine()
    assert e.classify([P("PVS1", "VERY_STRONG"), P("PM2", "MODERATE")]).classification == "LIKELY_PATHOGENIC"
    assert e.classify([P("PS1", "STRONG"), P("PM2", "MODERATE")]).classification == "LIKELY_PATHOGENIC"
    assert e.classify([P("PM2", "MODERATE"), P("PM3", "MODERATE"), P("PP3", "SUPPORTING")]).classification == "VUS"
    assert e.classify([P("PM1", "MODERATE"), P("PM2", "MODERATE"), P("PM3", "MODERATE")]).classification == "LIKELY_PATHOGENIC"


def test_benign_baseline_combinations():
    e = ACMGEngine()
    # BA1 uses standalone semantics and is not a strength level.
    ba1 = CriterionAssessment("BA1", "STANDALONE", CriterionDirection.BENIGN, reason="benchmark")
    assert e.classify([ba1]).classification == "BENIGN"
    assert e.classify([B("BS1", "STRONG"), B("BS2", "STRONG")]).classification == "BENIGN"
    assert e.classify([B("BS1", "STRONG"), B("BP4", "SUPPORTING")]).classification == "LIKELY_BENIGN"
    assert e.classify([B("BP4", "SUPPORTING"), B("BP7", "SUPPORTING")]).classification == "LIKELY_BENIGN"


def test_conflicts_are_not_silently_resolved():
    e = ACMGEngine()
    result = e.classify([
        P("PVS1", "VERY_STRONG"),
        B("BS1", "STRONG"),
    ])
    assert result.classification == "VUS"
    assert result.state == "REQUIRES_REVIEW"


def test_duplicate_criterion_rejected():
    with pytest.raises(ValueError, match="Duplicate ACMG criterion"):
        ACMGEngine().classify([P("PM2", "MODERATE"), P("PM2", "SUPPORTING")])


def test_provider_or_automatic_annotation_is_not_implicitly_promoted():
    e = ACMGEngine()
    result = e.classify([])
    assert result.classification == "VUS"
    assert result.state == "PROPOSED"


def test_conflicting_pathogenic_and_benign_requires_review():
    result = ACMGEngine().classify([P("PVS1", "VERY_STRONG"), B("BS1", "STRONG")])
    assert result.classification == "VUS"
    assert result.state == "REQUIRES_REVIEW"


def test_ba1_requires_standalone_strength():
    ba1 = CriterionAssessment("BA1", "STANDALONE", CriterionDirection.BENIGN, reason="benchmark")
    assert ACMGEngine().classify([ba1]).classification == "BENIGN"
