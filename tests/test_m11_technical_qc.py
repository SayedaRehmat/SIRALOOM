import math

import pytest

from backend.app.quality import assess_metrics, evaluate_metric, normalize_rules, overall_qc_status, QCRule


def test_m11_minimum_and_maximum_rules():
    assert evaluate_metric(30, QCRule("mean_depth", "MIN", threshold=30)) == "PASS"
    assert evaluate_metric(29.9, QCRule("mean_depth", "MIN", threshold=30)) == "FAIL"
    assert evaluate_metric(2.0, QCRule("contamination", "MAX", threshold=2.0)) == "PASS"
    assert evaluate_metric(2.1, QCRule("contamination", "MAX", threshold=2.0)) == "FAIL"


def test_m11_range_rule_and_missing_metric_are_explicit():
    config = {"rules": [{"metric": "callable_fraction", "direction": "RANGE", "minimum": 0.95, "maximum": 1.0}]}
    result = assess_metrics({"callable_fraction": 0.97}, config)
    assert result["status"] == "PASS"
    missing = assess_metrics({}, config)
    assert missing["status"] == "NOT_ASSESSED"
    assert missing["metrics"][0]["status"] == "NOT_ASSESSED"


def test_m11_warn_does_not_become_fail():
    config = {"rules": [{"metric": "duplicate_rate", "direction": "MAX", "threshold": 0.20, "severity": "WARN"}]}
    result = assess_metrics({"duplicate_rate": 0.25}, config)
    assert result["status"] == "WARN"


def test_m11_multiple_metrics_fail_gate_is_deterministic():
    config = {"rules": [
        {"metric": "mean_depth", "direction": "MIN", "threshold": 30},
        {"metric": "coverage_20x", "direction": "MIN", "threshold": 0.95},
    ]}
    result = assess_metrics({"mean_depth": 45, "coverage_20x": 0.91}, config)
    assert result["status"] == "FAIL"
    assert [m["status"] for m in result["metrics"]] == ["PASS", "FAIL"]


def test_m11_rule_validation_is_strict():
    try:
        normalize_rules({"rules": [{"metric": "x", "direction": "BOGUS"}]})
    except ValueError as exc:
        assert "Unsupported QC rule direction" in str(exc)
    else:
        raise AssertionError("Invalid QC direction was accepted")
    assert overall_qc_status([]) == "NOT_ASSESSED"


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, 10**1000])
def test_m11_non_finite_or_boolean_qc_metric_is_rejected(value):
    with pytest.raises(ValueError, match="finite number"):
        assess_metrics({"mean_depth": value}, {
            "rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 30}],
        })


@pytest.mark.parametrize(
    "rule",
    [
        {"metric": "mean_depth", "direction": "MIN"},
        {"metric": "mean_depth", "direction": "MIN", "threshold": math.inf},
        {"metric": "fraction", "direction": "RANGE", "minimum": 1.1, "maximum": 0.9},
        {"metric": "fraction", "direction": "RANGE", "minimum": 0, "maximum": math.nan},
        {"metric": "", "direction": "MIN", "threshold": 0},
    ],
)
def test_m11_invalid_qc_rule_bounds_are_rejected(rule):
    with pytest.raises(ValueError):
        normalize_rules({"rules": [rule]})
