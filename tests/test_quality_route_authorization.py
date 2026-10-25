from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from datetime import datetime, timezone

from backend.app.infrastructure.db.models import Artifact, TechnicalQCObservation
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
    def __init__(self, observations, artifacts=None):
        self.observations = observations
        self.artifacts = artifacts or {}
        self.added = []
        self.refresh_calls = []

    def refresh(self, row, *, with_for_update=False):
        self.refresh_calls.append((row, with_for_update))

    def scalars(self, _query):
        return _Scalars(self.observations)

    def get(self, model, identifier):
        if model is Artifact:
            return self.artifacts.get(identifier)
        return None

    def add(self, row):
        self.added.append(row)

    def flush(self):
        for row in self.added:
            if getattr(row, "created_at", None) is None:
                row.created_at = datetime.now(timezone.utc)

    def commit(self):
        pass


def test_qc_mutations_use_the_analysis_lock_shared_by_report_signout():
    from backend.app.api.v1.quality import _lock_analysis_for_qc_write

    analysis = SimpleNamespace(id=uuid4())
    db = _DB([])

    _lock_analysis_for_qc_write(db, analysis)

    assert db.refresh_calls == [(analysis, True)]


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


def test_qc_assessment_persists_exact_observation_snapshot(monkeypatch):
    from backend.app.api.v1 import quality

    analysis_id = uuid4()
    user_id = uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4(), assay_id=None)
    principal = Principal(user_id=user_id, organization_id=uuid4(), role="lab_director", subject="test")
    artifact_id = uuid4()
    observation = TechnicalQCObservation(
        id=uuid4(), analysis_id=analysis_id, metric_name="mean_depth",
        metric_value=40, status="AVAILABLE", source="LAB_QC", source_version="run-7",
        metadata_json={"record": "QC-7"}, created_at=datetime.now(timezone.utc),
        artifact_id=artifact_id,
    )
    artifact = SimpleNamespace(
        id=artifact_id, case_id=analysis.case_id, analysis_id=None,
        artifact_type="VCF", validation_status="VALIDATED", sha256="b" * 64,
    )
    db = _DB([observation], {artifact_id: artifact})
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(quality, "AuditService", lambda _db: SimpleNamespace(record=lambda **_kwargs: None))

    result = quality.assess_quality(
        analysis_id,
        quality.QCAssessmentInput(metrics={"mean_depth": 40}),
        db,
        principal,
    )

    assessment = db.added[0]
    assert result["status"] == "NOT_ASSESSED"  # No assay policy was supplied.
    assert assessment.observation_snapshot == [{
        "observation_id": str(observation.id),
        "metric_name": "mean_depth",
        "metric_value": 40,
        "metric_unit": None,
        "status": "AVAILABLE",
        "source": "LAB_QC",
        "source_version": "run-7",
        "metadata": {"record": "QC-7"},
        "created_at": observation.created_at.isoformat(),
        "artifact": {
            "artifact_id": str(artifact_id),
            "artifact_type": "VCF",
            "sha256": "b" * 64,
        },
    }]
    assert db.refresh_calls == [(analysis, True)]


def test_qc_observation_write_persists_same_case_source_artifact(monkeypatch):
    from backend.app.api.v1 import quality

    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4(), assay_id=None)
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        id=artifact_id, case_id=analysis.case_id, analysis_id=None,
        artifact_type="VCF", validation_status="VALID", sha256="a" * 64,
    )
    db = _DB([], {artifact_id: artifact})
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="bioinformatician", subject="test")
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(quality, "AuditService", lambda _db: SimpleNamespace(record=lambda **_kwargs: None))

    result = quality.record_qc_observation(
        analysis.id,
        quality.QCObservationInput(
            metric_name="mean_depth", metric_value=40, artifact_id=artifact_id,
        ),
        db,
        principal,
    )

    assert result["artifact_id"] == str(artifact_id)
    assert db.added[0].artifact_id == artifact_id
    assert db.refresh_calls == [(analysis, True)]


@pytest.mark.parametrize(
    ("artifact_type", "validation_status"),
    [("REPORT_PDF", "VALID"), ("VCF", "INVALID"), ("VCF", "PENDING")],
)
def test_qc_observation_rejects_non_vcf_or_unvalidated_source_artifact(
    monkeypatch, artifact_type, validation_status
):
    from backend.app.api.v1 import quality

    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4(), assay_id=None)
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        id=artifact_id, case_id=analysis.case_id, analysis_id=None,
        artifact_type=artifact_type, validation_status=validation_status,
        sha256="a" * 64,
    )
    db = _DB([], {artifact_id: artifact})
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="bioinformatician", subject="test")
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)

    with pytest.raises(HTTPException, match="validated VCF") as exc:
        quality.record_qc_observation(
            analysis.id,
            quality.QCObservationInput(metric_name="mean_depth", metric_value=40, artifact_id=artifact_id),
            db,
            principal,
        )

    assert exc.value.status_code == 409
    assert db.added == []


def test_qc_observation_write_rejects_artifact_from_another_case(monkeypatch):
    from backend.app.api.v1 import quality

    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4(), assay_id=None)
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="bioinformatician", subject="test")
    artifact_id = uuid4()
    db = _DB([])
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)

    with pytest.raises(HTTPException, match="artifact reference does not match"):
        quality.record_qc_observation(
            analysis.id,
            quality.QCObservationInput(metric_name="mean_depth", metric_value=40, artifact_id=artifact_id),
            db,
            principal,
        )

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

