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
    db = MembershipMutationSession([actor, target])

    def lock_tenant(session, tenant_id):
        assert session is db
        assert tenant_id == organization_id
        session.events.append("tenant-lock")

    monkeypatch.setattr(auth_api, "_lock_organization_membership_mutations", lock_tenant)

    result = auth_api.update_organization_membership(
        membership_id=str(membership_id),
        payload=auth_api.MembershipUpdate(),
        principal=_principal(user_id, organization_id),
        db=db,
    )

    assert db.events == ["tenant-lock", "membership-read", "membership-read", "commit"]
    assert "organization_memberships.organization_id" in str(db.statements[0])
    target_sql = str(db.statements[1])
    assert "organization_memberships.organization_id" in target_sql
    assert "FOR UPDATE" in str(
        db.statements[1].compile(compile_kwargs={"literal_binds": True})
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
