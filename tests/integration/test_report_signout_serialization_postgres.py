"""PostgreSQL proof that sign-out serializes against analysis decision changes."""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    AuditEvent,
    Case,
    Organization,
    Report,
    User,
)


@pytest.mark.integration
def test_signout_holds_analysis_lock_through_eligibility_and_snapshot(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    from backend.app.reporting import finalization

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id = uuid4(), uuid4(), uuid4(), uuid4()
    artifact_id, report_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"signout-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Signout concurrency", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Case(id=case_id, organization_id=organization_id, case_identifier=str(case_id), status="OPEN", clinical_context={}, language="en", created_by=user_id))
        db.flush()
        db.add(Analysis(id=analysis_id, case_id=case_id, analysis_type="VARIANT_INTERPRETATION", workflow_id="integration", workflow_version="test", status="SUCCEEDED", reference_build="GRCh38", configuration={}, created_by=user_id, analysis_version=1))
        db.flush()
        db.add(Artifact(id=artifact_id, case_id=case_id, analysis_id=analysis_id, artifact_type="REPORT_PDF", filename="draft.pdf", media_type="application/pdf", size_bytes=1, sha256="a" * 64, storage_uri="file:///draft.pdf", genome_build="GRCh38", validation_status="VALID", metadata_json={}))
        db.flush()
        db.add(Report(id=report_id, case_id=case_id, analysis_id=analysis_id, report_version=1, language="en", report_type="CLINICAL_INTERPRETATION", status="DRAFT", artifact_id=artifact_id, content_json={}))
        db.commit()

    validation_entered = threading.Event()
    allow_signout = threading.Event()
    decision_lock_acquired = threading.Event()
    errors = []

    def paused_eligibility(_db, *, analysis_id):
        assert analysis_id == analysis_id_outer
        validation_entered.set()
        if not allow_signout.wait(timeout=10):
            raise TimeoutError("sign-out validation gate was not released")
        return True, []

    analysis_id_outer = analysis_id
    monkeypatch.setattr(finalization, "final_report_eligibility", paused_eligibility)
    monkeypatch.setattr(finalization, "_verify_report_snapshot", lambda *_args: None)
    monkeypatch.setattr(finalization, "_persist_pdf_artifact", lambda _db, *, report, **_kwargs: _db.get(Artifact, report.artifact_id))

    def sign_out():
        try:
            with Session(engine) as db:
                finalization.finalize_report(db, report_id=report_id, approver_id=user_id, reason="Concurrent sign-out test")
                db.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    def mutate_analysis_decision():
        try:
            with Session(engine) as db:
                db.get(Analysis, analysis_id, with_for_update=True)
                decision_lock_acquired.set()
                db.commit()
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    signout_thread = threading.Thread(target=sign_out)
    writer_thread = threading.Thread(target=mutate_analysis_decision)
    try:
        signout_thread.start()
        assert validation_entered.wait(timeout=5), "sign-out did not reach eligibility validation"
        writer_thread.start()
        # The writer must remain blocked on the Analysis row until sign-out
        # commits its validation and signed report snapshot.
        assert not decision_lock_acquired.wait(timeout=0.75)
        allow_signout.set()
        signout_thread.join(timeout=10)
        writer_thread.join(timeout=10)
        assert not signout_thread.is_alive()
        assert not writer_thread.is_alive()
        assert decision_lock_acquired.is_set()
        assert not errors
        with Session(engine) as db:
            assert db.get(Report, report_id).status == "FINAL"
    finally:
        allow_signout.set()
        signout_thread.join(timeout=2)
        if writer_thread.ident is not None:
            writer_thread.join(timeout=2)
        with Session(engine) as db:
            db.query(AuditEvent).filter(AuditEvent.case_id == case_id).delete()
            db.query(Report).filter(Report.id == report_id).delete()
            db.query(Artifact).filter(Artifact.id == artifact_id).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
