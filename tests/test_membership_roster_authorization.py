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
