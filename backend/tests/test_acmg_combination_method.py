from types import SimpleNamespace

from backend.app.acmg.combination_method import (
    BAYESIAN,
    MODIFIED_ACMG,
    POINT_BASED,
    STANDARD_ACMG,
    detect_combination_method,
)


def spec(*, criteria=None, raw_payload=None):
    return SimpleNamespace(
        criteria=criteria or {},
        raw_payload=raw_payload or {},
    )


def test_standard_combining_rules_route_to_baseline_engine():
    decision = detect_combination_method(
        spec(
            raw_payload={
                "type": "Richards et.al., 2015 - Combining rules",
                "rules": "Standard ACMG/AMP combinations",
            }
        )
    )
    assert decision.method == STANDARD_ACMG
    assert decision.executable is True


def test_explicit_modified_combining_rules_require_review():
    decision = detect_combination_method(
        spec(
            raw_payload={
                "combiningMethod": "Modified ACMG/AMP",
                "rules": "Modified combining rules",
            }
        )
    )
    assert decision.method == MODIFIED_ACMG
    assert decision.executable is False
    assert "validated executor" in decision.reason


def test_point_based_specification_requires_review():
    decision = detect_combination_method(
        spec(
            raw_payload={
                "classificationMethod": "Point-based variant classification",
                "attachment": "Use a points-based policy for combining criteria",
            }
        )
    )
    assert decision.method == POINT_BASED
    assert decision.executable is False


def test_disregard_rules_use_points_attachment_is_point_based():
    decision = detect_combination_method(
        spec(
            raw_payload={
                "rules": (
                    "Disregard the Rules for Combining Criteria and use "
                    "the points-based attachment."
                )
            }
        )
    )
    assert decision.method == POINT_BASED
    assert decision.executable is False


def test_bayesian_specification_requires_review():
    decision = detect_combination_method(
        spec(raw_payload={"classificationMethod": "Bayesian-informed variant classification"})
    )
    assert decision.method == BAYESIAN
    assert decision.executable is False


def test_modified_combination_prose_is_not_silently_treated_as_baseline():
    decision = detect_combination_method(
        spec(
            raw_payload={
                "rules": (
                    "Rules for Combining Criteria: standard combinations plus "
                    "one very strong + one supporting = Likely Pathogenic."
                )
            }
        )
    )
    assert decision.method == MODIFIED_ACMG
    assert decision.executable is False


def test_unknown_explicit_combination_method_requires_review():
    decision = detect_combination_method(
        spec(raw_payload={"combiningMethod": "Proprietary scoring framework"})
    )
    assert decision.method == "UNSUPPORTED"
    assert decision.executable is False
    assert decision.metadata["detection_basis"] == "UNKNOWN_EXPLICIT_COMBINATION_METHOD"
