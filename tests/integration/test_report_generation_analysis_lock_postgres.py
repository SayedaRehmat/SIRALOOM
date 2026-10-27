"""PostgreSQL proof that report drafting serializes with analysis decisions."""

import os
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.v1 import reports
from backend.app.auth.principal import Principal
from backend.app.domain.schemas import ReportCreate
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Organization,
    Report,
    User,
)


@pytest.mark.integration
def test_report_draft_waits_for_analysis_decision_lock(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    from sqlalchemy import create_engine

    class NoopAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    class DatabaseArtifactStore:
        def put_file(self, *, db, case_id, analysis_id, filename, artifact_type, media_type,
                     genome_build, metadata, validation_status, artifact_id, **_kwargs):
            artifact = Artifact(
                id=artifact_id,
                case_id=case_id,
                analysis_id=analysis_id,
                artifact_type=artifact_type,
                filename=filename,
                media_type=media_type,
                size_bytes=3,
                sha256="c" * 64,
                storage_uri=f"file:///report-lock/{artifact_id}.pdf",
                genome_build=genome_build,
                validation_status=validation_status,
                metadata_json=metadata,
            )
            db.add(artifact)
            db.flush()
            return artifact

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"report-generation-lock-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Report generation lock", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Case(id=case_id, organization_id=organization_id, case_identifier=str(case_id), status="OPEN", clinical_context={}, language="en", created_by=user_id))
        db.flush()
        db.add(Analysis(id=analysis_id, case_id=case_id, analysis_type="VARIANT_INTERPRETATION", workflow_id="report-generation-lock-integration", workflow_version="test", status="SUCCEEDED", reference_build="GRCh38", configuration={}, created_by=user_id))
        db.commit()

    analysis_stub = SimpleNamespace(id=analysis_id, case_id=case_id)
    eligibility_entered = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_results = []
    writer_errors = []

    def eligible(*_args, **_kwargs):
        eligibility_entered.set()
        return True, []

    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis_stub)
    monkeypatch.setattr(reports, "require_role", lambda *_args: None)
    monkeypatch.setattr(reports, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(reports, "final_report_eligibility", eligible)
    monkeypatch.setattr(reports, "build_report_content", lambda *_args, **_kwargs: {"report_schema_version": "1.1.0"})
    monkeypatch.setattr(reports, "render_pdf", lambda _content: b"pdf")
    monkeypatch.setattr(reports, "artifact_store_for_organization", lambda *_args, **_kwargs: DatabaseArtifactStore())
    monkeypatch.setattr(reports, "AuditService", NoopAudit)
    monkeypatch.setattr(reports, "commit_with_artifact_compensation", lambda db, _store, _artifact: db.commit())

    def create_draft():
        writer_started.set()
        try:
            with Session(engine) as db:
                result = reports.create_report(
                    analysis_id=analysis_id,
                    payload=ReportCreate(),
                    db=db,
                    principal=Principal(
                        user_id=user_id,
                        organization_id=organization_id,
                        role="lab_director",
                        subject=str(user_id),
                    ),
                )
                writer_results.append(result)
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    writer = threading.Thread(target=create_draft)
    try:
        with Session(engine) as decision_writer:
            decision_writer.get(Analysis, analysis_id, with_for_update=True)
            writer.start()
            assert writer_started.wait(timeout=5)
            time.sleep(0.5)
            assert not eligibility_entered.is_set(), "draft generation read analysis decisions before acquiring their lock"
            assert not writer_finished.is_set(), "report generation completed while the analysis row was locked"
            decision_writer.commit()
        writer.join(timeout=10)
        assert not writer.is_alive()
        assert not writer_errors
        assert eligibility_entered.is_set()
        assert writer_results and writer_results[0]["status"] == "DRAFT"
        with Session(engine) as db:
            report = db.scalar(select(Report).where(Report.analysis_id == analysis_id))
            assert report is not None
            assert report.artifact_id is not None
    finally:
        if writer.ident is not None:
            writer.join(timeout=2)
        with Session(engine) as db:
            db.query(Report).filter(Report.analysis_id == analysis_id).delete()
            db.query(Artifact).filter(Artifact.analysis_id == analysis_id).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
