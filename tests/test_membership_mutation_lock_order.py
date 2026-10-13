from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import auth as auth_api
from backend.app.auth.principal import Principal


class MembershipMutationSession:
    def __init__(self, membership):
        self.membership = membership
        self.events = []
        self.statement = None

    def scalar(self, statement):
        self.events.append("membership-read")
        self.statement = statement
        return self.membership

    def commit(self):
        self.events.append("commit")


def test_membership_mutation_locks_tenant_before_reading_authoritative_target(monkeypatch):
    organization_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    target = SimpleNamespace(
        id=membership_id,
        organization_id=organization_id,
        user_id=uuid4(),
        role="reviewer",
        status="ACTIVE",
    )
    db = MembershipMutationSession(target)

    def lock_tenant(session, tenant_id):
        assert session is db
        assert tenant_id == organization_id
        session.events.append("tenant-lock")

    monkeypatch.setattr(auth_api, "_lock_organization_membership_mutations", lock_tenant)

    result = auth_api.update_organization_membership(
        membership_id=str(membership_id),
        payload=auth_api.MembershipUpdate(),
        principal=Principal(
            user_id=user_id,
            organization_id=organization_id,
            role="organization_admin",
            subject="verified-subject",
        ),
        db=db,
    )

    assert db.events == ["tenant-lock", "membership-read", "commit"]
    assert result == {
        "membership_id": str(membership_id),
        "role": "reviewer",
        "status": "ACTIVE",
    }
    sql = str(db.statement)
    assert "organization_memberships.organization_id" in sql
    assert "FOR UPDATE" in str(db.statement.compile(compile_kwargs={"literal_binds": True})).upper()


def test_membership_mutation_rejects_target_outside_tenant(monkeypatch):
    organization_id = uuid4()
    membership_id = uuid4()
    db = MembershipMutationSession(None)
    monkeypatch.setattr(
        auth_api,
        "_lock_organization_membership_mutations",
        lambda session, tenant_id: session.events.append("tenant-lock"),
    )

    from fastapi import HTTPException
    import pytest

    with pytest.raises(HTTPException) as error:
        auth_api.update_organization_membership(
            membership_id=str(membership_id),
            payload=auth_api.MembershipUpdate(),
            principal=Principal(
                user_id=uuid4(),
                organization_id=organization_id,
                role="organization_admin",
                subject="verified-subject",
            ),
            db=db,
        )

    assert error.value.status_code == 404
    assert db.events == ["tenant-lock", "membership-read"]
