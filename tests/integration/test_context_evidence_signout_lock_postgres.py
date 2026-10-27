"""PostgreSQL proof that manual report evidence serializes with sign-out."""

import os
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import evidence_context
from backend.app.api.v1.evidence_context import ContextEvidenceRequest
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import (
    Analysis,
    Annotation,
    Case,
    Evidence,
    Organization,
    User,
    Variant,
)


@pytest.mark.integration
def test_context_evidence_write_waits_for_signout_analysis_lock(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    class NoopAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(evidence_context, "get_accessible_analysis", lambda *_args: analysis_stub)
    monkeypatch.setattr(evidence_context, "require_role", lambda *_args: None)
    monkeypatch.setattr(evidence_context, "get_analysis_variant", lambda *_args: variant_stub)
    monkeypatch.setattr(evidence_context, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(evidence_context, "AuditService", NoopAudit)

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id, analysis_id, variant_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    analysis_stub = SimpleNamespace(id=analysis_id, case_id=case_id)
    variant_stub = SimpleNamespace(id=variant_id)
    annotation_id = uuid4()

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"evidence-lock-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Evidence lock", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Case(id=case_id, organization_id=organization_id, case_identifier=str(case_id), status="OPEN", clinical_context={}, language="en", created_by=user_id))
        db.flush()
        db.add(Analysis(id=analysis_id, case_id=case_id, analysis_type="VARIANT_INTERPRETATION", workflow_id="evidence-lock-integration", workflow_version="test", status="SUCCEEDED", reference_build="GRCh38", configuration={}, created_by=user_id))
        db.flush()
        db.add(Variant(id=variant_id, genome_build="GRCh38", chromosome="1", position=10, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key=f"evidence-lock:{variant_id}", identifiers={}))
        db.flush()
        db.add(Annotation(id=annotation_id, variant_id=variant_id, analysis_id=analysis_id, provider_name="fixture", provider_version="1", request_metadata={}, payload={}))
        db.commit()

    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_errors = []

    def write_evidence():
        writer_started.set()
        try:
            with Session(engine) as db:
                evidence_context.add_context_evidence(
                    analysis_id=analysis_id,
                    variant_id=variant_id,
                    body=ContextEvidenceRequest(
                        evidence_type="LITERATURE",
                        source_name="Fixture source",
                        statement="Candidate context evidence",
                    ),
                    db=db,
                    principal=Principal(
                        user_id=user_id,
                        organization_id=organization_id,
                        role="lab_director",
                        subject=str(user_id),
                    ),
                )
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            writer_errors.append(exc)
        finally:
            writer_finished.set()

    writer = threading.Thread(target=write_evidence)
    try:
        with Session(engine) as signout_db:
            signout_db.get(Analysis, analysis_id, with_for_update=True)
            writer.start()
            assert writer_started.wait(timeout=5)
            time.sleep(0.5)
            assert not writer_finished.is_set(), "context evidence write bypassed the analysis row lock"
            signout_db.commit()
        writer.join(timeout=10)
        assert not writer.is_alive()
        assert not writer_errors
        with Session(engine) as db:
            row = db.scalar(select(Evidence).where(Evidence.analysis_id == analysis_id))
            assert row is not None
            assert row.source_name == "Fixture source"
    finally:
        if writer.ident is not None:
            writer.join(timeout=2)
        with Session(engine) as db:
            db.query(Evidence).filter(Evidence.analysis_id == analysis_id).delete()
            db.query(Annotation).filter(Annotation.id == annotation_id).delete()
            db.query(Variant).filter(Variant.id == variant_id).delete()
            db.query(Analysis).filter(Analysis.id == analysis_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
