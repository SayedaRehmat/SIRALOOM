import os
import threading
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1.auth import MembershipUpdate, update_organization_membership
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Organization, OrganizationMembership, User


@pytest.mark.integration
def test_postgres_concurrent_last_admin_revocation_revalidates_actor_membership():
    """Two administrators cannot concurrently revoke one another using stale authority."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id = uuid4()
    admin_a_id, admin_b_id = uuid4(), uuid4()
    membership_a_id, membership_b_id = uuid4(), uuid4()

    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id,
                name=f"membership-race-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add_all([
                User(
                    id=admin_a_id, organization_id=organization_id,
                    external_subject=str(admin_a_id), email=f"{admin_a_id}@example.test",
                    display_name="Admin A", role="organization_admin", status="ACTIVE",
                ),
                User(
                    id=admin_b_id, organization_id=organization_id,
                    external_subject=str(admin_b_id), email=f"{admin_b_id}@example.test",
                    display_name="Admin B", role="organization_admin", status="ACTIVE",
                ),
            ])
            db.commit()

        with Session(engine) as db:
            db.add_all([
                OrganizationMembership(
                    id=membership_a_id, organization_id=organization_id,
                    user_id=admin_a_id, role="organization_admin", status="ACTIVE",
                ),
                OrganizationMembership(
                    id=membership_b_id, organization_id=organization_id,
                    user_id=admin_b_id, role="organization_admin", status="ACTIVE",
                ),
            ])
            db.commit()

        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def revoke(actor_id, target_membership_id):
            try:
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    result = update_organization_membership(
                        membership_id=str(target_membership_id),
                        payload=MembershipUpdate(status="REVOKED"),
                        principal=Principal(
                            user_id=actor_id,
                            organization_id=organization_id,
                            role="organization_admin",
                            subject=str(actor_id),
                        ),
                        db=db,
                    )
                    outcomes.append(("success", result["status"]))
            except HTTPException as exc:
                outcomes.append(("http", exc.status_code))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=revoke, args=(admin_a_id, membership_b_id)),
            threading.Thread(target=revoke, args=(admin_b_id, membership_a_id)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert len(outcomes) == 2
        assert sorted(outcomes, key=str) == sorted(
            [("success", "REVOKED"), ("http", 403)], key=str
        )
        with Session(engine) as db:
            active_admins = db.query(OrganizationMembership).filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == "organization_admin",
                OrganizationMembership.status == "ACTIVE",
            ).count()
            assert active_admins == 1
    finally:
        with Session(engine) as db:
            db.query(OrganizationMembership).filter(
                OrganizationMembership.organization_id == organization_id
            ).delete()
            db.query(User).filter(User.organization_id == organization_id).delete()
            db.query(Organization).filter(Organization.id == organization_id).delete()
            db.commit()
        engine.dispose()
