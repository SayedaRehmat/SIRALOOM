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
