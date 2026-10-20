from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.mark.parametrize(
    ("endpoint", "args"),
    [
        (
            "create_assay",
            lambda module: (
                module.AssayInput(name="Assay", version="1", assay_type="WGS"),
                object(),
            ),
        ),
        (
            "record_qc_observation",
            lambda module: (
                uuid4(),
                module.QCObservationInput(metric_name="mean_depth", metric_value=40),
                object(),
            ),
        ),
        (
            "assess_quality",
            lambda module: (
                uuid4(),
                module.QCAssessmentInput(metrics={"mean_depth": 40}),
                object(),
            ),
        ),
    ],
)
def test_read_only_member_cannot_mutate_assay_or_quality_records(monkeypatch, endpoint, args):
    from backend.app.api.v1 import quality

    principal = SimpleNamespace(user_id=uuid4(), organization_id=uuid4(), role="read_only")
    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4(), assay_id=None)
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)
    db = args(quality)[-1]

    with pytest.raises(HTTPException) as exc:
        getattr(quality, endpoint)(*args(quality), principal)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_qc_request_models_reject_non_finite_values(value):
    from backend.app.api.v1.quality import QCObservationInput, QCAssessmentInput

    with pytest.raises(ValueError):
        QCObservationInput(metric_name="mean_depth", metric_value=value)
    with pytest.raises(ValueError):
        QCAssessmentInput(metrics={"mean_depth": value})

