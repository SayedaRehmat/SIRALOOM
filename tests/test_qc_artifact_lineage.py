from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from backend.app.api.v1 import quality
from backend.app.auth.authorization import require_analysis_artifact
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Artifact, QCAssessment, TechnicalQCObservation


@pytest.mark.parametrize("mismatch", ["missing", "case", "analysis"])
def test_analysis_artifact_reference_rejects_broken_lineage(mismatch):
    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4())
    artifact_id = uuid4()
    artifact = SimpleNamespace(
        id=artifact_id,
        case_id=uuid4() if mismatch == "case" else analysis.case_id,
        analysis_id=uuid4() if mismatch == "analysis" else analysis.id,
    )

    class _Db:
        def get(self, model, requested_id):
            assert model is Artifact
            assert requested_id == artifact_id
            return None if mismatch == "missing" else artifact

    with pytest.raises(HTTPException) as exc:
        require_analysis_artifact(analysis, artifact_id, _Db())

    assert exc.value.status_code == 409
    assert exc.value.detail == "Analysis artifact reference does not match its case and analysis"


def test_quality_read_fails_closed_on_foreign_qc_artifact(monkeypatch):
    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4(), assay_id=None)
    principal = Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="lab_director",
        subject="qc-artifact-test",
    )
    artifact_id = uuid4()
    observation = SimpleNamespace(
        id=uuid4(), analysis_id=analysis.id, artifact_id=artifact_id,
        metric_name="coverage", metric_value=20.0, metric_unit="x",
        status="RECORDED", source="LAB_QC", source_version=None,
        metadata_json={}, created_at=datetime.now(timezone.utc),
    )
    foreign_artifact = SimpleNamespace(
        id=artifact_id, case_id=uuid4(), analysis_id=analysis.id
    )

    class _Rows:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            return iter(self.rows)

    class _Db:
        def scalars(self, statement):
            model = statement.column_descriptions[0]["entity"]
            if model is TechnicalQCObservation:
                return _Rows([observation])
            assert model is QCAssessment
            return _Rows([])

        def get(self, model, requested_id):
            assert model is Artifact
            assert requested_id == artifact_id
            return foreign_artifact

    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(quality, "require_role", lambda *_args: None)

    with pytest.raises(HTTPException) as exc:
        quality.get_quality(analysis.id, _Db(), principal)

    assert exc.value.status_code == 409
    assert "artifact reference" in exc.value.detail
