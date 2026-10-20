from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1.case_access import (
    CaseAccessGrantInput,
    revoke_case_access,
    set_case_access,
)
from backend.app.auth.authorization import (
    case_access_predicate,
    require_case_permission,
)
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Case,
    CaseAccessGrant,
    Organization,
    OrganizationMembership,
    User,
)


@pytest.fixture
def case_access_db(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'case-access.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        org = Organization(id=uuid4(), name="Lab A")
        other_org = Organization(id=uuid4(), name="Lab B")
        db.add_all([org, other_org])
        db.flush()

        users = {}
        for key, role, organization in [
            ("admin", "organization_admin", org),
            ("writer", "bioinformatician", org),
            ("reviewer", "reviewer", org),
            ("reader", "read_only", org),
            ("unassigned", "read_only", org),
            ("foreign", "organization_admin", other_org),
        ]:
            user = User(
                id=uuid4(), organization_id=organization.id,
                external_subject=f"subject-{key}", email=f"{key}@example.test",
                display_name=key, role=role, status="ACTIVE",
            )
            users[key] = user
            db.add(user)
            db.add(OrganizationMembership(
                id=uuid4(), organization_id=organization.id, user_id=user.id,
                role=role, status="ACTIVE",
            ))
        db.flush()

        case = Case(
            id=uuid4(), organization_id=org.id, case_identifier="CASE-1",
            status="DRAFT", clinical_context={}, language="en",
            created_by=users["admin"].id,
        )
        foreign_case = Case(
            id=uuid4(), organization_id=other_org.id, case_identifier="CASE-2",
            status="DRAFT", clinical_context={}, language="en",
            created_by=users["foreign"].id,
        )
        db.add_all([case, foreign_case])
        db.add_all([
            CaseAccessGrant(
                id=uuid4(), case_id=case.id, user_id=users["writer"].id,
                can_read=True, can_write=True, can_review=False,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=case.id, user_id=users["reviewer"].id,
                can_read=True, can_write=False, can_review=True,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=case.id, user_id=users["reader"].id,
                can_read=True, can_write=False, can_review=False,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=foreign_case.id, user_id=users["foreign"].id,
                can_read=True, can_write=True, can_review=True,
            ),
        ])
        db.commit()
        yield db, org, other_org, users, case, foreign_case
    engine.dispose()


def _principal(user, organization_id, role=None):
    return Principal(
        user_id=user.id,
        organization_id=organization_id,
        role=role or user.role,
        subject=user.external_subject,
        email=user.email,
    )


def test_case_permissions_require_assignment_and_role(case_access_db):
    db, org, other_org, users, case, foreign_case = case_access_db

    require_case_permission(case, _principal(users["writer"], org.id), db, "write")
    require_case_permission(case, _principal(users["reviewer"], org.id), db, "review")
    require_case_permission(case, _principal(users["reader"], org.id), db, "read")

    with pytest.raises(HTTPException) as denied:
        require_case_permission(case, _principal(users["unassigned"], org.id), db, "read")
    assert denied.value.status_code == 404

    with pytest.raises(HTTPException) as denied:
        require_case_permission(case, _principal(users["reviewer"], org.id), db, "write")
    assert denied.value.status_code == 404

    # A grant cannot elevate the organization's role.
    writer = db.scalar(
        select(CaseAccessGrant).where(
            CaseAccessGrant.case_id == case.id,
            CaseAccessGrant.user_id == users["writer"].id,
        )
    )
    writer.can_review = True
    db.commit()
    with pytest.raises(HTTPException) as denied:
        require_case_permission(case, _principal(users["writer"], org.id), db, "review")
    assert denied.value.status_code == 403

    # Tenant isolation remains authoritative even for an administrator.
    with pytest.raises(HTTPException) as denied:
        require_case_permission(foreign_case, _principal(users["admin"], org.id), db, "read")
    assert denied.value.status_code == 404


def test_case_list_predicate_returns_only_assigned_cases(case_access_db):
    db, org, _other_org, users, case, _foreign_case = case_access_db
    statement = select(Case).where(
        case_access_predicate(_principal(users["reader"], org.id), "read")
    )
    assert db.scalars(statement).all() == [case]

    admin_statement = select(Case).where(
        case_access_predicate(_principal(users["admin"], org.id), "read")
    )
    assert db.scalars(admin_statement).all() == [case]

    # A stale pre-demotion token must not preserve an administrator bypass in
    # list queries; the SQL predicate reads the current active membership.
    stale_admin = _principal(users["unassigned"], org.id, role="organization_admin")
    assert db.scalars(
        select(Case).where(case_access_predicate(stale_admin, "read"))
    ).all() == []


def test_case_access_admin_grants_updates_and_revokes_with_audit(case_access_db):
    db, org, _other_org, users, case, _foreign_case = case_access_db
    admin = _principal(users["admin"], org.id)
    target = users["unassigned"]
    target.role = "bioinformatician"
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org.id,
            OrganizationMembership.user_id == target.id,
        )
    )
    membership.role = "bioinformatician"
    db.commit()

    result = set_case_access(
        case.id,
        target.id,
        CaseAccessGrantInput(can_read=True, can_write=True, can_review=False),
        db,
        admin,
    )
    assert result["can_read"] is True
    assert result["can_write"] is True
    require_case_permission(case, _principal(target, org.id), db, "write")

    revoke_case_access(case.id, target.id, db, admin)
    with pytest.raises(HTTPException) as denied:
        require_case_permission(case, _principal(target, org.id), db, "read")
    assert denied.value.status_code == 404

    from backend.app.infrastructure.db.models import AuditEvent

    event_types = set(db.scalars(select(AuditEvent.event_type)).all())
    assert {"CASE_ACCESS_GRANT_CHANGED", "CASE_ACCESS_GRANT_REVOKED"}.issubset(event_types)


@pytest.mark.parametrize(
    ("role", "payload"),
    [
        ("read_only", CaseAccessGrantInput(can_read=True, can_write=True, can_review=False)),
        ("bioinformatician", CaseAccessGrantInput(can_read=True, can_write=False, can_review=True)),
    ],
)
def test_case_assignment_rejects_grants_outside_member_role(case_access_db, role, payload):
    db, org, _other_org, users, case, _foreign_case = case_access_db
    target = users["unassigned"]
    target.role = role
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == org.id,
        OrganizationMembership.user_id == target.id,
    ))
    membership.role = role
    db.commit()

    with pytest.raises(HTTPException) as denied:
        set_case_access(case.id, target.id, payload, db, _principal(users["admin"], org.id))

    assert denied.value.status_code == 403
    assert db.scalar(select(CaseAccessGrant).where(
        CaseAccessGrant.case_id == case.id,
        CaseAccessGrant.user_id == target.id,
    )) is None


@pytest.mark.parametrize(
    "payload",
    [
        {"can_read": False, "can_write": True, "can_review": False},
        {"can_read": False, "can_write": False, "can_review": True},
        {"can_read": False, "can_write": False, "can_review": False},
    ],
)
def test_case_access_input_rejects_empty_or_non_read_capabilities(payload):
    with pytest.raises(ValueError):
        CaseAccessGrantInput(**payload)
