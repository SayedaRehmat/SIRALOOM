"""PostgreSQL proof that identical resource approval requests are idempotent."""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import request_resource_approval
from backend.app.infrastructure.db.models import (
    Organization,
    Resource,
    ResourceApproval,
    ResourceQualification,
    User,
)


@pytest.mark.integration
def test_concurrent_duplicate_adoption_requests_return_one_durable_approval():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id = uuid4(), uuid4()
    resource_id, qualification_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"request-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Adoption request concurrency", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Resource(id=resource_id, organization_id=None, name="RequestRaceDB", provider="FixtureProvider", resource_type="EVIDENCE", version="1", genome_build="GRCh38", access_method="OBJECT_STORAGE", checksum="a" * 64, location="blob://request-race/1", status="QUALIFIED", population_definition=None, metadata_json={}))
        db.add(ResourceQualification(id=qualification_id, resource_id=resource_id, qualification_version="q1", status="QUALIFIED", checks_json={"passed": True}, qualified_by=user_id))
        db.commit()

    barrier = threading.Barrier(2)
    approval_ids, errors = [], []

    def request():
        try:
            # Start both API-equivalent calls together. The service locks the
            # resource before creating a pending row, so a flush hook would
            # deadlock here: the first transaction owns the lock while waiting
            # for the second transaction, which cannot reach flush.
            barrier.wait(timeout=10)
            with Session(engine) as db:
                approval = request_resource_approval(
                    db,
                    resource_id=resource_id,
                    organization_id=organization_id,
                    qualification_version="q1",
                )
                db.commit()
                approval_ids.append(approval.id)
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=request) for _ in range(2)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert len(approval_ids) == 2
        assert approval_ids[0] == approval_ids[1]
        with Session(engine) as db:
            assert db.scalar(select(func.count(ResourceApproval.id)).where(
                ResourceApproval.resource_id == resource_id,
                ResourceApproval.organization_id == organization_id,
            )) == 1
    finally:
        with Session(engine) as db:
            db.query(ResourceApproval).filter(ResourceApproval.resource_id == resource_id).delete()
            db.query(ResourceQualification).filter(ResourceQualification.id == qualification_id).delete()
            db.query(Resource).filter(Resource.id == resource_id).delete()
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
