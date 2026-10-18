from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import auth as auth_api
from backend.app.auth.principal import Principal


class MembershipMutationSession:
    def __init__(self, rows):
        self.rows = iter(rows)
        self.events = []
        self.statements = []

    def scalar(self, statement):
        self.events.append("membership-read")
        self.statements.append(statement)
        return next(self.rows)

    def commit(self):
        self.events.append("commit")


def _principal(user_id, organization_id):
    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        role="organization_admin",
        subject="verified-subject",
    )


def _active_admin(user_id, organization_id):
    return SimpleNamespace(
        id=uuid4(), user_id=user_id, organization_id=organization_id,
        role="organization_admin", status="ACTIVE",
    )


def test_membership_mutation_locks_tenant_and_revalidates_actor_before_target(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    actor = _active_admin(user_id, organization_id)
    target = SimpleNamespace(
        id=membership_id, organization_id=organization_id, user_id=uuid4(),
        role="reviewer", status="ACTIVE",
    )
    target_user_id = target.user_id
    target_user = SimpleNamespace(
        id=target_user_id, organization_id=organization_id,
        external_subject="target-user-subject", role="reviewer", status="ACTIVE",
    )
    db = MembershipMutationSession([
        actor, target_user_id, target_user, target_user, target,
    ])

    def lock_tenant(session, tenant_id):
        assert session is db
        assert tenant_id == organization_id
        session.events.append("tenant-lock")

    monkeypatch.setattr(auth_api, "_lock_organization_membership_mutations", lock_tenant)
    monkeypatch.setattr(
        auth_api,
        "_lock_identity_provisioning",
        lambda session, subject: session.events.append(("identity-lock", subject)),
    )

    result = auth_api.update_organization_membership(
        membership_id=str(membership_id),
        payload=auth_api.MembershipUpdate(),
        principal=_principal(user_id, organization_id),
        db=db,
    )

    assert db.events == [
        "tenant-lock", "membership-read", "membership-read", "membership-read",
        ("identity-lock", "target-user-subject"), "membership-read", "membership-read",
        "commit",
    ]
    assert "organization_memberships.organization_id" in str(db.statements[0])
    assert "users.id" in str(db.statements[3])
    assert "FOR UPDATE" in str(
        db.statements[3].compile(compile_kwargs={"literal_binds": True})
    ).upper()
    target_sql = str(db.statements[4])
    assert "organization_memberships.organization_id" in target_sql
    assert "FOR UPDATE" in str(
        db.statements[4].compile(compile_kwargs={"literal_binds": True})
    ).upper()
    assert result == {
        "membership_id": str(membership_id), "role": "reviewer", "status": "ACTIVE",
    }


def test_membership_mutation_rejects_stale_admin_after_membership_revocation(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    db = MembershipMutationSession([None])
    monkeypatch.setattr(
        auth_api, "_lock_organization_membership_mutations",
        lambda session, tenant_id: session.events.append("tenant-lock"),
    )

    with pytest.raises(HTTPException) as error:
        auth_api.update_organization_membership(
            membership_id=str(uuid4()),
            payload=auth_api.MembershipUpdate(),
            principal=_principal(user_id, organization_id),
            db=db,
        )

    assert error.value.status_code == 403
    assert error.value.detail == "An active organization membership is required to manage memberships"
    assert db.events == ["tenant-lock", "membership-read"]


def test_membership_mutation_rejects_target_outside_tenant(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    db = MembershipMutationSession([_active_admin(user_id, organization_id), None])
    monkeypatch.setattr(
        auth_api, "_lock_organization_membership_mutations",
        lambda session, tenant_id: session.events.append("tenant-lock"),
    )

    with pytest.raises(HTTPException) as error:
        auth_api.update_organization_membership(
            membership_id=str(uuid4()),
            payload=auth_api.MembershipUpdate(),
            principal=_principal(user_id, organization_id),
            db=db,
        )

    assert error.value.status_code == 404
    assert db.events == ["tenant-lock", "membership-read", "membership-read"]


def test_membership_mutation_rejects_stale_membership_for_reprovisioned_user(monkeypatch):
    organization_id = uuid4()
    other_organization_id = uuid4()
    actor_id = uuid4()
    stale_user_id = uuid4()
    actor = _active_admin(actor_id, organization_id)
    user_snapshot = SimpleNamespace(
        id=stale_user_id, organization_id=organization_id,
        external_subject="reprovisioned-subject",
        role="organization_admin", status="ACTIVE",
    )
    user_after_identity_lock = SimpleNamespace(
        id=stale_user_id, organization_id=other_organization_id,
        external_subject="reprovisioned-subject",
        role="organization_admin", status="ACTIVE",
    )
    db = MembershipMutationSession([
        actor, stale_user_id, user_snapshot, user_after_identity_lock,
    ])
    monkeypatch.setattr(
        auth_api, "_lock_organization_membership_mutations",
        lambda session, tenant_id: session.events.append("tenant-lock"),
    )
    monkeypatch.setattr(
        auth_api,
        "_lock_identity_provisioning",
        lambda session, subject: session.events.append(("identity-lock", subject)),
    )

    with pytest.raises(HTTPException) as error:
        auth_api.update_organization_membership(
            membership_id=str(uuid4()),
            payload=auth_api.MembershipUpdate(status="SUSPENDED"),
            principal=_principal(actor_id, organization_id),
            db=db,
        )

    assert error.value.status_code == 404
    assert user_after_identity_lock.status == "ACTIVE"
    assert user_after_identity_lock.role == "organization_admin"
    # Reject before locking or changing the old membership row.
    assert len(db.statements) == 4
    assert db.statements[3]._execution_options.get("populate_existing") is True
    assert "FOR UPDATE" in str(
        db.statements[3].compile(compile_kwargs={"literal_binds": True})
    ).upper()


def test_stale_membership_cannot_change_reprovisioned_account_in_sqlite():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.infrastructure.db.base import Base
    from backend.app.infrastructure.db.models import (
        Organization,
        OrganizationMembership,
        User,
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Organization.__table__,
            User.__table__,
            OrganizationMembership.__table__,
        ],
    )
    old_org_id, new_org_id = uuid4(), uuid4()
    former_admin_id, moved_user_id = uuid4(), uuid4()
    old_membership_id = uuid4()
    with Session(engine) as db:
        db.add_all([
            Organization(id=old_org_id, name="Former laboratory", external_identifier=None),
            Organization(id=new_org_id, name="Current laboratory", external_identifier=None),
            User(
                id=former_admin_id, organization_id=old_org_id,
                external_subject="former-admin", email="admin@example.test",
                display_name="Former Admin", role="organization_admin", status="ACTIVE",
            ),
            User(
                id=moved_user_id, organization_id=new_org_id,
                external_subject="moved-user", email="moved@example.test",
                display_name="Moved User", role="reviewer", status="ACTIVE",
            ),
            OrganizationMembership(
                id=uuid4(), organization_id=old_org_id, user_id=former_admin_id,
                role="organization_admin", status="ACTIVE",
            ),
            OrganizationMembership(
                id=old_membership_id, organization_id=old_org_id, user_id=moved_user_id,
                role="reviewer", status="REVOKED",
            ),
            OrganizationMembership(
                id=uuid4(), organization_id=new_org_id, user_id=moved_user_id,
                role="reviewer", status="ACTIVE",
            ),
        ])
        db.commit()

        with pytest.raises(HTTPException) as error:
            auth_api.update_organization_membership(
                membership_id=str(old_membership_id),
                payload=auth_api.MembershipUpdate(status="SUSPENDED"),
                principal=_principal(former_admin_id, old_org_id),
                db=db,
            )

        assert error.value.status_code == 404
        moved_user = db.get(User, moved_user_id)
        old_membership = db.get(OrganizationMembership, old_membership_id)
        assert (moved_user.organization_id, moved_user.role, moved_user.status) == (
            new_org_id, "reviewer", "ACTIVE",
        )
        assert old_membership.status == "REVOKED"


def test_invitation_creation_rejects_stale_admin_after_membership_revocation(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    db = MembershipMutationSession([None])
    monkeypatch.setattr(
        auth_api,
        "_lock_organization_membership_mutations",
        lambda session, tenant_id: session.events.append("tenant-lock"),
    )

    with pytest.raises(HTTPException) as error:
        auth_api.create_organization_invitation(
            payload=auth_api.OrganizationInvitationCreate(
                email="new-member@example.test", role="read_only",
            ),
            principal=_principal(user_id, organization_id),
            db=db,
        )

    assert error.value.status_code == 403
    assert db.events == ["tenant-lock", "membership-read"]
