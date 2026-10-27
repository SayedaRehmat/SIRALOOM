"""PostgreSQL verification of report source snapshot reconstruction."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.report_integrity import (
    REPORT_CONTENT_INTEGRITY_VERSION,
    report_content_sha256,
)
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Organization,
    Report,
    User,
)
from backend.app.reporting.finalization import ReportFinalizationError, _verify_report_snapshot
from backend.app.reporting.service import build_report_content


def _seed_postgres_draft(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact_id, report_id = uuid4(), uuid4()
    with Session(engine) as db:
        organization = Organization(
            id=organization_id,
            name=f"report-source-{organization_id}",
            external_identifier=str(organization_id),
        )
        user = User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Report source snapshot",
            role="lab_director",
            status="ACTIVE",
        )
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=str(case_id),
            status="OPEN",
            clinical_context={"indication": "Initial indication"},
            language="en",
            created_by=user_id,
        )
        analysis = Analysis(
            id=analysis_id,
            case_id=case_id,
            analysis_type="VARIANT_INTERPRETATION",
            workflow_id="report-source-snapshot-integration",
            workflow_version="test",
            status="SUCCEEDED",
            reference_build="GRCh38",
            configuration={},
            created_by=user_id,
        )
        artifact = Artifact(
            id=artifact_id,
            case_id=case_id,
            analysis_id=analysis_id,
            artifact_type="REPORT_PDF",
            filename="report-source-draft.pdf",
            media_type="application/pdf",
            size_bytes=1,
            sha256="a" * 64,
            storage_uri=f"file:///report-source/{artifact_id}.pdf",
            genome_build="GRCh38",
            validation_status="VALID",
            metadata_json={},
        )
        # These models use foreign keys without ORM relationships, so SQLAlchemy
        # cannot infer their insert ordering from object dependencies.
        db.add(organization)
        db.flush()
        db.add(user)
        db.flush()
        db.add(case)
        db.flush()
        db.add(analysis)
        db.flush()
        db.add(artifact)
        db.flush()
        content = build_report_content(db, analysis, "en", report_type="ANALYTICAL")
        content["report_version"] = 1
        artifact.metadata_json = {
            "report_id": str(report_id),
            "report_version": 1,
            "report_state": "DRAFT",
            "report_content_integrity": REPORT_CONTENT_INTEGRITY_VERSION,
            "report_content_sha256": report_content_sha256(content),
        }
        report = Report(
            id=report_id,
            case_id=case_id,
            analysis_id=analysis_id,
            report_version=1,
            language="en",
            report_type="ANALYTICAL",
            status="DRAFT",
            artifact_id=artifact_id,
            content_json=content,
        )
        db.add(report)
        db.commit()
    return engine, organization_id, user_id, case_id, analysis_id, artifact_id, report_id


def _cleanup_postgres_draft(engine, organization_id, user_id, case_id, analysis_id, artifact_id, report_id):
    with Session(engine) as db:
        report = db.get(Report, report_id)
        if report is not None:
            db.delete(report)
        artifact = db.get(Artifact, artifact_id)
        if artifact is not None:
            db.delete(artifact)
        analysis = db.get(Analysis, analysis_id)
        if analysis is not None:
            db.delete(analysis)
        case = db.get(Case, case_id)
        if case is not None:
            db.delete(case)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
        organization = db.get(Organization, organization_id)
        if organization is not None:
            db.delete(organization)
        db.commit()
    engine.dispose()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")
    return url


@pytest.mark.integration
def test_report_source_snapshot_reconstructs_unchanged_draft_in_postgres():
    engine, org_id, user_id, case_id, analysis_id, artifact_id, report_id = _seed_postgres_draft(_database_url())
    try:
        with Session(engine) as db:
            report = db.get(Report, report_id)
            _verify_report_snapshot(db, report)
    finally:
        _cleanup_postgres_draft(engine, org_id, user_id, case_id, analysis_id, artifact_id, report_id)


@pytest.mark.integration
def test_report_source_snapshot_rejects_changed_case_data_in_postgres():
    engine, org_id, user_id, case_id, analysis_id, artifact_id, report_id = _seed_postgres_draft(_database_url())
    try:
        with Session(engine) as db:
            case = db.get(Case, case_id)
            case.clinical_context = {"indication": "Changed after draft"}
            db.commit()
        with Session(engine) as db:
            report = db.get(Report, report_id)
            with pytest.raises(ReportFinalizationError, match="source data changed after report draft generation"):
                _verify_report_snapshot(db, report)
    finally:
        _cleanup_postgres_draft(engine, org_id, user_id, case_id, analysis_id, artifact_id, report_id)
