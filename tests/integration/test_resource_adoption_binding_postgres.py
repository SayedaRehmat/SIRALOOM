"""PostgreSQL proof that same-tenant resource adoption decisions serialize."""

import os
import threading
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.domain.resources import decide_resource_approval
from backend.app.infrastructure.db.models import (
    Organization,
    OrganizationResourceBinding,
    Resource,
    ResourceApproval,
    ResourceApprovalAction,
    ResourceQualification,
    User,
)


@pytest.mark.integration
def test_concurrent_release_adoptions_preserve_binding_version_history():
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, user_id = uuid4(), uuid4()
    baseline_id, baseline_qualification_id, baseline_approval_id = uuid4(), uuid4(), uuid4()
    candidate_ids = [uuid4(), uuid4()]
    qualification_ids = [uuid4(), uuid4()]
    approval_ids = [uuid4(), uuid4()]
    identity_key = "ConcurrentDB|FixtureProvider|EVIDENCE|GRCh38"

    with Session(engine) as db:
        db.add(Organization(id=organization_id, name=f"adopt-{organization_id}", external_identifier=str(organization_id)))
        db.flush()
        db.add(User(id=user_id, organization_id=organization_id, external_subject=str(user_id), email=f"{user_id}@example.test", display_name="Adoption concurrency", role="lab_director", status="ACTIVE"))
        db.flush()
        db.add(Resource(id=baseline_id, organization_id=None, name="ConcurrentDB", provider="FixtureProvider", resource_type="EVIDENCE", version="1", genome_build="GRCh38", access_method="OBJECT_STORAGE", checksum="1" * 64, location="blob://concurrent/1", status="QUALIFIED", population_definition=None, metadata_json={}))
        db.flush()
        db.add(ResourceQualification(id=baseline_qualification_id, resource_id=baseline_id, qualification_version="q1", status="QUALIFIED", checks_json={"passed": True}, qualified_by=user_id))
        db.flush()
        db.add(ResourceApproval(id=baseline_approval_id, resource_id=baseline_id, organization_id=organization_id, qualification_id=baseline_qualification_id, status="PENDING", version=1))
        db.commit()

    with Session(engine) as db:
        decide_resource_approval(db, approval_id=baseline_approval_id, organization_id=organization_id, actor_id=user_id, decision="APPROVED", expected_version=1, reason="Initial approved release")
        db.commit()

    with Session(engine) as db:
        for index, version in enumerate(("2", "3")):
            db.add(Resource(id=candidate_ids[index], organization_id=None, name="ConcurrentDB", provider="FixtureProvider", resource_type="EVIDENCE", version=version, genome_build="GRCh38", access_method="OBJECT_STORAGE", checksum=str(index + 2) * 64, location=f"blob://concurrent/{version}", status="QUALIFIED", population_definition=None, metadata_json={}))
            db.flush()
            db.add(ResourceQualification(id=qualification_ids[index], resource_id=candidate_ids[index], qualification_version="q1", status="QUALIFIED", checks_json={"passed": True}, qualified_by=user_id))
            db.flush()
            db.add(ResourceApproval(id=approval_ids[index], resource_id=candidate_ids[index], organization_id=organization_id, qualification_id=qualification_ids[index], status="PENDING", version=1))
        db.commit()

    barrier = threading.Barrier(2)
    adopted, errors = [], []

    def decide(approval_id, candidate_id):
        try:
            with Session(engine) as db:
                barrier.wait(timeout=10)
                result = decide_resource_approval(
                    db,
                    approval_id=approval_id,
                    organization_id=organization_id,
                    actor_id=user_id,
                    decision="APPROVED",
                    expected_version=1,
                    reason=f"Adopt release {candidate_id}",
                )
                db.commit()
                adopted.append(result.id)
        except Exception as exc:  # surfaced in the main test thread  # noqa: BLE001
            errors.append(exc)

    threads = [
        threading.Thread(target=decide, args=(approval_ids[i], candidate_ids[i]))
        for i in range(2)
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)
        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert len(adopted) == 2
        with Session(engine) as db:
            binding = db.scalar(select(OrganizationResourceBinding).where(
                OrganizationResourceBinding.organization_id == organization_id,
                OrganizationResourceBinding.identity_key == identity_key,
            ))
            assert binding is not None
            assert binding.version == 3
            assert binding.previous_resource_id in {baseline_id, *candidate_ids}
            assert binding.resource_id in set(candidate_ids)
            assert db.scalar(select(func.count(ResourceApprovalAction.id)).where(
                ResourceApprovalAction.organization_id == organization_id,
                ResourceApprovalAction.after_status == "APPROVED",
            )) == 3
    finally:
        with Session(engine) as db:
            db.query(ResourceApprovalAction).filter(ResourceApprovalAction.organization_id == organization_id).delete()
            db.query(OrganizationResourceBinding).filter(OrganizationResourceBinding.organization_id == organization_id).delete()
            db.query(ResourceApproval).filter(ResourceApproval.organization_id == organization_id).delete()
            db.query(ResourceQualification).filter(ResourceQualification.resource_id.in_([baseline_id, *candidate_ids])).delete(synchronize_session=False)
            db.query(Resource).filter(Resource.id.in_([baseline_id, *candidate_ids])).delete(synchronize_session=False)
            db.query(User).filter(User.id == user_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
