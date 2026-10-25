from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from datetime import datetime, timezone

from backend.app.infrastructure.db.models import TechnicalQCObservation
from backend.app.auth.principal import Principal


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


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class _DB:
    def __init__(self, observations):
        self.observations = observations
        self.added = []

    def scalars(self, _query):
        return _Scalars(self.observations)

    def get(self, *_args):
        return None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        pass


def test_qc_assessment_rejects_values_not_backed_by_persisted_observations(monkeypatch):
    from backend.app.api.v1 import quality

    analysis_id = uuid4()
    user_id = uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4(), assay_id=None)
    principal = Principal(user_id=user_id, organization_id=uuid4(), role="lab_director", subject="test")
    observation = TechnicalQCObservation(
        id=uuid4(), analysis_id=analysis_id, metric_name="mean_depth",
        metric_value=10, status="AVAILABLE", source="UPSTREAM",
        created_at=datetime.now(timezone.utc),
    )
    db = _DB([observation])
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)

    with pytest.raises(HTTPException) as error:
        quality.assess_quality(
            analysis_id,
            quality.QCAssessmentInput(metrics={"mean_depth": 100}),
            db,
            principal,
        )

    assert error.value.status_code == 409
    assert not db.added


@pytest.mark.parametrize(
    ("configuration", "status", "expected"),
    [
        ({"rules": [{"metric": "depth", "direction": "INVALID", "threshold": 20}]}, "ACTIVE", "direction"),
        ({"rules": []}, "ACTIVE", "at least one valid QC rule"),
        ({"rules": [{"metric": "depth", "direction": "MIN", "threshold": 20}]}, "RETIRED", "status"),
    ],
)
def test_assay_creation_rejects_invalid_or_unusable_qc_profiles(monkeypatch, configuration, status, expected):
    from backend.app.api.v1 import quality

    db = _DB([])
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="lab_director", subject="test")
    monkeypatch.setattr(quality, "require_role", lambda *_args: None)

    with pytest.raises(HTTPException, match=expected):
        quality.create_assay(
            quality.AssayInput(
                name="Assay", version="1", assay_type="WGS",
                configuration=configuration, status=status,
            ),
            db,
            principal,
        )

    assert not db.added


def test_assay_creation_persists_only_valid_active_qc_profile(monkeypatch):
    from backend.app.api.v1 import quality

    db = _DB([])
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="lab_director", subject="test")
    monkeypatch.setattr(quality, "require_role", lambda *_args: None)
    monkeypatch.setattr(quality, "AuditService", lambda _db: SimpleNamespace(record=lambda **_kwargs: None))

    result = quality.create_assay(
        quality.AssayInput(
            name="Assay", version="1", assay_type="WGS",
            configuration={"rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 20}]},
        ),
        db,
        principal,
    )

    assert result["configuration"]["rules"][0]["metric"] == "mean_depth"
    assert len(db.added) == 1

