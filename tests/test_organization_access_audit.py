import hashlib
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.api.v1 import auth as auth_api
from backend.app.auth.principal import Principal
from backend.app.config import settings
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    AuditEvent,
    Case,
    CaseAccessGrant,
    Organization,
    OrganizationMembership,
    User,
)
from backend.app.infrastructure.db.organization_invitations import OrganizationInvitation


def test_invitation_and_membership_lifecycle_is_audited_in_transaction(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, admin_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add(Organization(id=organization_id, name="Audit Lab", external_identifier=None))
        db.add(User(
            id=admin_id,
            organization_id=organization_id,
            external_subject="admin-subject",
            email="admin@example.test",
            display_name="Lab administrator",
            role="organization_admin",
            status="ACTIVE",
        ))
        db.add(OrganizationMembership(
            id=uuid4(), organization_id=organization_id, user_id=admin_id,
            role="organization_admin", status="ACTIVE",
        ))
        db.commit()

        admin = Principal(
            user_id=admin_id,
            organization_id=organization_id,
            role="organization_admin",
            subject="admin-subject",
        )
        created = auth_api.create_organization_invitation(
            payload=auth_api.OrganizationInvitationCreate(
                email="reviewer@example.test", role="reviewer",
            ),
            principal=admin,
            db=db,
        )
        token = created["invitation_token"]
        invitation = db.get(OrganizationInvitation, UUID(created["invitation_id"]))
        assert invitation is not None
        assert invitation.token_hash == hashlib.sha256(token.encode()).hexdigest()
        assert invitation.token_hash != token
        with pytest.raises(HTTPException) as duplicate:
            auth_api.create_organization_invitation(
                payload=auth_api.OrganizationInvitationCreate(
                    email="reviewer@example.test", role="reviewer",
                ),
                principal=admin,
                db=db,
            )
        assert duplicate.value.status_code == 409

        monkeypatch.setattr(
            auth_api,
            "_authenticate_bearer",
            lambda _authorization: (
                "reviewer-subject",
                {"email": "reviewer@example.test", "email_verified": True},
            ),
        )
        accepted = auth_api.accept_organization_invitation(
            payload=auth_api.InvitationAcceptance(token=token),
            authorization="Bearer verified-test-token",
            db=db,
        )
        updated = auth_api.update_organization_membership(
            membership_id=accepted["membership_id"],
            payload=auth_api.MembershipUpdate(status="SUSPENDED"),
            principal=admin,
            db=db,
        )

        events = {
            event.event_type: event
            for event in db.scalars(select(AuditEvent))
        }
        assert set(events) == {
            "ORGANIZATION_INVITATION_CREATED",
            "ORGANIZATION_INVITATION_ACCEPTED",
            "ORGANIZATION_MEMBERSHIP_UPDATED",
        }
        assert events["ORGANIZATION_INVITATION_CREATED"].actor_id == str(admin_id)
        assert events["ORGANIZATION_INVITATION_CREATED"].after_state["role"] == "reviewer"
        membership = db.get(OrganizationMembership, UUID(accepted["membership_id"]))
        assert membership is not None
        assert events["ORGANIZATION_INVITATION_ACCEPTED"].actor_id == str(membership.user_id)
        assert events["ORGANIZATION_INVITATION_ACCEPTED"].after_state["status"] == "ACCEPTED"
        assert events["ORGANIZATION_MEMBERSHIP_UPDATED"].before_state == {
            "role": "reviewer", "status": "ACTIVE",
        }
        assert events["ORGANIZATION_MEMBERSHIP_UPDATED"].after_state["status"] == "SUSPENDED"
        assert updated["status"] == "SUSPENDED"

    engine.dispose()


def test_self_onboarding_audits_organization_and_owner_provisioning(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        monkeypatch.setattr(settings, "organization_self_signup_enabled", True)
        monkeypatch.setattr(settings, "organization_first_bootstrap_enabled", False)
        monkeypatch.setattr(
            auth_api,
            "_authenticate_bearer",
            lambda _authorization: (
                "owner-subject",
                {"email": "owner@example.test", "email_verified": True},
            ),
        )

        result = auth_api.create_first_organization(
            payload=auth_api.OrganizationOnboarding(organization_name="Onboarded Lab"),
            authorization="Bearer verified-test-token",
            db=db,
        )

        event = db.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "ORGANIZATION_PROVISIONED",
        ))
        assert event is not None
        assert event.subject_type == "ORGANIZATION"
        assert event.subject_id == result["organization_id"]
        assert event.after_state["owner_role"] == "organization_admin"
        assert event.actor_id == event.after_state["owner_user_id"]
        assert db.get(Organization, UUID(result["organization_id"])) is not None

    engine.dispose()


def test_role_demotion_clears_incompatible_case_grants_and_promotion_does_not_restore_them():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, other_organization_id = uuid4(), uuid4()
    admin_id, member_id = uuid4(), uuid4()
    membership_id = uuid4()
    case_id, other_case_id = uuid4(), uuid4()
    with Session(engine) as db:
        db.add_all([
            Organization(id=organization_id, name="Assigned Lab", external_identifier=None),
            Organization(id=other_organization_id, name="Other Lab", external_identifier=None),
            User(
                id=admin_id, organization_id=organization_id,
                external_subject="admin-subject", email="admin@example.test",
                display_name="Administrator", role="organization_admin", status="ACTIVE",
            ),
            User(
                id=member_id, organization_id=organization_id,
                external_subject="reviewer-subject", email="reviewer@example.test",
                display_name="Reviewer", role="reviewer", status="ACTIVE",
            ),
            OrganizationMembership(
                id=uuid4(), organization_id=organization_id, user_id=admin_id,
                role="organization_admin", status="ACTIVE",
            ),
            OrganizationMembership(
                id=membership_id, organization_id=organization_id, user_id=member_id,
                role="reviewer", status="ACTIVE",
            ),
            Case(
                id=case_id, organization_id=organization_id, case_identifier="CASE-1",
                status="DRAFT", clinical_context={}, language="en", created_by=admin_id,
            ),
            Case(
                id=other_case_id, organization_id=other_organization_id,
                case_identifier="CASE-2", status="DRAFT", clinical_context={},
                language="en", created_by=member_id,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=case_id, user_id=member_id, granted_by=admin_id,
                can_read=True, can_write=True, can_review=True,
            ),
            CaseAccessGrant(
                id=uuid4(), case_id=other_case_id, user_id=member_id, granted_by=member_id,
                can_read=True, can_write=True, can_review=True,
            ),
        ])
        db.commit()
        admin = Principal(
            user_id=admin_id, organization_id=organization_id,
            role="organization_admin", subject="admin-subject",
        )

        auth_api.update_organization_membership(
            membership_id=str(membership_id),
            payload=auth_api.MembershipUpdate(role="read_only"),
            principal=admin,
            db=db,
        )

        local_grant = db.scalar(select(CaseAccessGrant).where(CaseAccessGrant.case_id == case_id))
        foreign_grant = db.scalar(select(CaseAccessGrant).where(CaseAccessGrant.case_id == other_case_id))
        assert (local_grant.can_read, local_grant.can_write, local_grant.can_review) == (True, False, False)
        assert (foreign_grant.can_read, foreign_grant.can_write, foreign_grant.can_review) == (True, True, True)
        revocation = db.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "CASE_ACCESS_CAPABILITIES_REVOKED_ROLE_CHANGE",
        ))
        assert revocation is not None
        assert revocation.actor_id == str(admin_id)
        assert revocation.subject_id == str(member_id)
        assert revocation.after_state == {
            "role": "read_only",
            "capabilities_revoked": ["can_review", "can_write"],
            "grant_rows_updated": 1,
        }

        auth_api.update_organization_membership(
            membership_id=str(membership_id),
            payload=auth_api.MembershipUpdate(role="reviewer"),
            principal=admin,
            db=db,
        )
        db.refresh(local_grant)
        assert (local_grant.can_read, local_grant.can_write, local_grant.can_review) == (True, False, False)

    engine.dispose()
