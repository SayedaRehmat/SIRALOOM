from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Real
from typing import Any

VALID_DIRECTIONS = {"MIN", "MAX", "RANGE", "EXACT"}
VALID_STATUSES = {"PASS", "WARN", "FAIL", "NOT_ASSESSED"}


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, Real):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):
        return False

@dataclass(frozen=True)
class QCRule:
    metric: str
    direction: str
    threshold: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    severity: str = "FAIL"


def evaluate_metric(value: float | int | None, rule: QCRule) -> str:
    if value is None:
        return "NOT_ASSESSED"
    if not _is_finite_number(value):
        raise ValueError(f"QC metric {rule.metric!r} must be a finite number")
    direction = rule.direction.upper()
    if direction == "MIN":
        passed = value >= float(rule.threshold)
    elif direction == "MAX":
        passed = value <= float(rule.threshold)
    elif direction == "RANGE":
        passed = rule.minimum <= value <= rule.maximum
    elif direction == "EXACT":
        passed = value == rule.threshold
    else:
        raise ValueError(f"Unsupported QC rule direction: {rule.direction}")
    return "PASS" if passed else rule.severity.upper()


def overall_qc_status(results: list[str]) -> str:
    if not results:
        return "NOT_ASSESSED"
    if "FAIL" in results:
        return "FAIL"
    if "WARN" in results:
        return "WARN"
    if all(x == "PASS" for x in results):
        return "PASS"
    return "NOT_ASSESSED"


def normalize_rules(config: dict[str, Any] | None) -> list[QCRule]:
    rules = [] if not config else config.get("rules", [])
    output: list[QCRule] = []
    for item in rules:
        if not isinstance(item, dict):
            raise ValueError("Each QC rule must be an object")
        direction = str(item.get("direction", "MIN")).upper()
        if direction not in VALID_DIRECTIONS:
            raise ValueError(f"Unsupported QC rule direction: {direction}")
        metric = str(item.get("metric", "")).strip()
        if not metric:
            raise ValueError("QC rule metric must be a non-empty string")
        severity = str(item.get("severity", "FAIL")).upper()
        if severity not in {"WARN", "FAIL"}:
            raise ValueError("QC rule severity must be WARN or FAIL")
        required = ("minimum", "maximum") if direction == "RANGE" else ("threshold",)
        for field in required:
            value = item.get(field)
            if not _is_finite_number(value):
                raise ValueError(f"QC rule {metric!r} requires a finite numeric {field}")
        if direction == "RANGE" and item["minimum"] > item["maximum"]:
            raise ValueError(f"QC rule {metric!r} minimum cannot exceed maximum")
        output.append(QCRule(
            metric=metric, direction=direction,
            threshold=item.get("threshold"), minimum=item.get("minimum"), maximum=item.get("maximum"), severity=severity,
        ))
    return output


def assess_metrics(metrics: dict[str, float | int | None], config: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        raise ValueError("QC metrics must be an object")
    for name, value in metrics.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("QC metric names must be non-empty strings")
        if value is not None and not _is_finite_number(value):
            raise ValueError(f"QC metric {name!r} must be a finite number or null")
    rules = normalize_rules(config)
    evaluated = []
    for rule in rules:
        value = metrics.get(rule.metric)
        status = evaluate_metric(value, rule)
        evaluated.append({"metric": rule.metric, "value": value, "status": status, "direction": rule.direction,
                          "threshold": rule.threshold, "minimum": rule.minimum, "maximum": rule.maximum,
                          "severity": rule.severity})
    status = overall_qc_status([x["status"] for x in evaluated])
    return {"status": status, "metrics": evaluated, "rule_count": len(evaluated)}
