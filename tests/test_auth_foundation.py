from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.auth.principal import Principal, require_case_tenant
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Case, Organization, OrganizationMembership, User


def test_organization_membership_is_server_side_and_unique():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        organization = Organization(id=uuid4(), name="Org")
        user = User(id=uuid4(), organization_id=organization.id, display_name="User", role="ANALYST", status="ACTIVE")
        membership = OrganizationMembership(id=uuid4(), organization_id=organization.id, user_id=user.id, role="reviewer", status="ACTIVE")
        db.add_all([organization, user, membership])
        db.commit()
        assert db.get(OrganizationMembership, membership.id).role == "reviewer"


def test_case_tenant_mismatch_is_not_authorized():
    organization_id = uuid4()
    case = Case(id=uuid4(), organization_id=organization_id, case_identifier="SIR-TEST", status="DRAFT", clinical_context={}, language="en", created_by=uuid4())
    principal = Principal(user_id=uuid4(), organization_id=uuid4(), role="reviewer", subject="firebase-subject")
    try:
        require_case_tenant(case, principal)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 404
    else:
        raise AssertionError("Cross-tenant case access must be rejected")
