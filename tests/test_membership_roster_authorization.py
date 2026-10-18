from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1.membership import list_organization_memberships
from backend.app.auth.principal import Principal


class _Result:
    def all(self):
        return []


class _Database:
    def __init__(self):
        self.queried = False

    def execute(self, _statement):
        self.queried = True
        return _Result()


@pytest.mark.parametrize("role", ["read_only", "lab_scientist", "reviewer", "bioinformatician"])
def test_member_roster_hides_staff_identity_from_non_admin_roles(role):
    db = _Database()
    principal = Principal(
        user_id=uuid4(), organization_id=uuid4(), role=role, subject="verified-user",
    )

    with pytest.raises(HTTPException) as error:
        list_organization_memberships(principal=principal, db=db)

    assert error.value.status_code == 403
    assert not db.queried


@pytest.mark.parametrize("role", ["organization_admin", "lab_director"])
def test_member_roster_remains_available_to_membership_administrators(role):
    db = _Database()
    principal = Principal(
        user_id=uuid4(), organization_id=uuid4(), role=role, subject="verified-user",
    )

    assert list_organization_memberships(principal=principal, db=db) == {
        "organization_id": str(principal.organization_id),
        "members": [],
    }
    assert db.queried


def test_member_roster_hides_memberships_from_an_identity_reprovisioned_elsewhere():
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
    former_org_id = uuid4()
    current_org_id = uuid4()
    user_id = uuid4()
    with Session(engine) as db:
        db.add_all([
            Organization(id=former_org_id, name="Former laboratory", external_identifier=None),
            Organization(id=current_org_id, name="Current laboratory", external_identifier=None),
            User(
                id=user_id,
                organization_id=current_org_id,
                external_subject="reprovisioned-subject",
                email="current-lab-user@example.test",
                display_name="Current Lab User",
                role="reviewer",
                status="ACTIVE",
            ),
            OrganizationMembership(
                id=uuid4(), organization_id=former_org_id, user_id=user_id,
                role="reviewer", status="REVOKED",
            ),
            OrganizationMembership(
                id=uuid4(), organization_id=current_org_id, user_id=user_id,
                role="reviewer", status="ACTIVE",
            ),
        ])
        db.commit()

        former_roster = list_organization_memberships(
            principal=Principal(
                user_id=uuid4(), organization_id=former_org_id,
                role="organization_admin", subject="former-admin",
            ),
            db=db,
        )
        current_roster = list_organization_memberships(
            principal=Principal(
                user_id=uuid4(), organization_id=current_org_id,
                role="organization_admin", subject="current-admin",
            ),
            db=db,
        )

    assert former_roster["members"] == []
    assert current_roster["members"][0]["email"] == "current-lab-user@example.test"
