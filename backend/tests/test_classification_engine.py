from types import SimpleNamespace

from backend.app.acmg.classification_engine import (
    ACMG2015ClassificationEngine,
    ClassificationEngineRouter,
)
from backend.app.acmg.combination_method import (
    BAYESIAN,
    MODIFIED_ACMG,
    POINT_BASED,
    STANDARD_ACMG,
)


def spec(*, criteria=None, raw_payload=None):
    return SimpleNamespace(
        criteria=criteria or {},
        raw_payload=raw_payload or {},
    )


def test_standard_specification_routes_to_acmg_2015_engine():
    selection = ClassificationEngineRouter().select(
        spec(
            raw_payload={
                "type": "Richards et.al., 2015 - Combining rules",
                "rules": "Standard ACMG/AMP combinations",
            }
        )
    )

    assert selection.decision.method == STANDARD_ACMG
    assert selection.decision.executable is True
    assert isinstance(selection.engine, ACMG2015ClassificationEngine)


def test_modified_specification_does_not_fall_back_to_standard_engine():
    selection = ClassificationEngineRouter().select(
        spec(
            raw_payload={
                "combiningMethod": "Modified ACMG/AMP",
                "rules": "Modified combining rules",
            }
        )
    )

    assert selection.decision.method == MODIFIED_ACMG
    assert selection.decision.executable is False
    assert selection.engine is None


def test_point_based_specification_does_not_fall_back_to_standard_engine():
    selection = ClassificationEngineRouter().select(
        spec(
            raw_payload={
                "classificationMethod": "Point-based variant classification",
                "attachment": "Use a points-based policy for combining criteria",
            }
        )
    )

    assert selection.decision.method == POINT_BASED
    assert selection.decision.executable is False
    assert selection.engine is None


def test_bayesian_specification_does_not_fall_back_to_standard_engine():
    selection = ClassificationEngineRouter().select(
        spec(
            raw_payload={
                "classificationMethod": "Bayesian-informed variant classification"
            }
        )
    )

    assert selection.decision.method == BAYESIAN
    assert selection.decision.executable is False
    assert selection.engine is None
