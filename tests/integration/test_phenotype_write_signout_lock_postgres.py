"""PostgreSQL proof that case phenotype writes serialize with report sign-out."""

import os
import threading
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import phenotypes
from backend.app.api.v1.phenotypes import PhenotypeInput
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Case, Organization, PhenotypeObservation, User


@pytest.mark.integration
def test_case_phenotype_write_waits_for_signout_case_lock(monkeypatch):
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    class NoopAudit:
        def __init__(self, _db):
            pass

        def record(self, **_kwargs):
            pass

    monkeypatch.setattr(phenotypes, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(phenotypes, "require_role", lambda *_args: None)
    monkeypatch.setattr(phenotypes, "AuditService", NoopAudit)
    monkeypatch.setattr(phenotypes, "create_case_change_candidates", lambda *_args, **_kwargs: None)

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"phenotype-lock-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Phenotype lock", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Case(id=case_id, organization_id=organization_id, case_identifier=str(case_id), status="OPEN", clinical_context={}, language="en", created_by=user_id))
        db.commit()

    writer_started = threading.Event()
    writer_finished = threading.Event()
    writer_errors = []

    def write_phenotype():
        writer_started.set()
        try:
            with Session(engine) as db:
                phenotypes.add_case_phenotype(
                    case_id=case_id,
                    body=PhenotypeInput(hpo_id="HP:0001250"),
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

    writer = threading.Thread(target=write_phenotype)
    try:
        with Session(engine) as signout_db:
            signout_db.get(Case, case_id, with_for_update=True)
            writer.start()
            assert writer_started.wait(timeout=5)
            time.sleep(0.5)
            assert not writer_finished.is_set(), "phenotype write bypassed the case row lock"
            signout_db.commit()
        writer.join(timeout=10)
        assert not writer.is_alive()
        assert not writer_errors
        with Session(engine) as db:
            observation = db.scalar(
                select(PhenotypeObservation).where(
                    PhenotypeObservation.case_id == case_id,
                    PhenotypeObservation.analysis_id.is_(None),
                )
            )
            assert observation is not None
            assert observation.hpo_id == "HP:0001250"
    finally:
        if writer.ident is not None:
            writer.join(timeout=2)
        with Session(engine) as db:
            db.query(PhenotypeObservation).filter(PhenotypeObservation.case_id == case_id).delete()
            db.query(Case).filter(Case.id == case_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
