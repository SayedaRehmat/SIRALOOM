from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import quality
from backend.app.auth.authorization import require_analysis_artifact
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Analysis, Artifact, Assay, Case, QCAssessment, TechnicalQCObservation


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
            if model is QCAssessment:
                return _Rows([])
            assert model is Artifact
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


def test_quality_artifact_choices_exclude_artifacts_from_other_analyses(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organization_id = uuid4()
        case = Case(
            id=uuid4(), organization_id=organization_id, case_identifier="QC-CASE",
            status="ACTIVE", language="en", clinical_context={}, created_by=uuid4(),
        )
        analysis = Analysis(
            id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION",
            workflow_id="variant-v1", workflow_version="1", status="REQUIRES_REVIEW",
            reference_build="GRCh38", configuration={},
        )
        sibling_analysis = Analysis(
            id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION",
            workflow_id="variant-v1", workflow_version="1", status="SUCCEEDED",
            reference_build="GRCh38", configuration={},
        )
        source = Artifact(
            id=uuid4(), case_id=case.id, analysis_id=None, artifact_type="VCF",
            filename="source.vcf", media_type="text/vcf", size_bytes=10,
            sha256="a" * 64, storage_uri="file:///source.vcf", validation_status="VALIDATED",
        )
        current = Artifact(
            id=uuid4(), case_id=case.id, analysis_id=analysis.id, artifact_type="NORMALIZED_VCF",
            filename="normalized.vcf.gz", media_type="application/gzip", size_bytes=10,
            sha256="b" * 64, storage_uri="file:///normalized.vcf.gz", validation_status="VALID",
        )
        sibling = Artifact(
            id=uuid4(), case_id=case.id, analysis_id=sibling_analysis.id, artifact_type="VCF",
            filename="other-analysis.vcf", media_type="text/vcf", size_bytes=10,
            sha256="c" * 64, storage_uri="file:///other.vcf", validation_status="VALIDATED",
        )
        assay = Assay(
            id=uuid4(), organization_id=organization_id, name="Exome", version="1",
            assay_type="WES", configuration={"rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 20}]},
            status="ACTIVE",
        )
        analysis.assay_id = assay.id
        stale_assessment = QCAssessment(
            id=uuid4(), analysis_id=analysis.id, assay_id=assay.id, status="PASS",
            profile_name=assay.name, profile_version=assay.version, metrics_json={"mean_depth": 40},
            evaluated_rules=[{"metric": "mean_depth", "direction": "MIN", "threshold": 20, "value": 40, "status": "PASS"}],
            gate_status="PASS", reviewed_by=str(uuid4()), reviewed_at=datetime.now(timezone.utc),
        )
        db.add_all([case, analysis, sibling_analysis, source, current, sibling, assay, stale_assessment])
        db.flush()
        principal = Principal(
            user_id=uuid4(), organization_id=organization_id,
            role="lab_director", subject="qc-artifact-options",
        )
        monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)
        monkeypatch.setattr(quality, "require_role", lambda *_args: None)

        result = quality.get_quality(analysis.id, db, principal)

        assert {row["artifact_id"] for row in result["available_artifacts"]} == {
            str(source.id), str(current.id),
        }
        displayed_assessment = result["assessments"][0]
        assert displayed_assessment["is_current"] is False
        assert displayed_assessment["clinical_gate_status"] == "REASSESSMENT_REQUIRED"
