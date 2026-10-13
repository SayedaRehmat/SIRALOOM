from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1 import auth as auth_api
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Organization, OrganizationMembership, User
from backend.app.infrastructure.db.organization_invitations import OrganizationInvitation


@pytest.mark.integration
def test_postgres_invitation_acceptance_and_revocation_are_mutually_exclusive(monkeypatch):
    database_url = __import__("os").environ.get("DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
        pytest.skip("PostgreSQL integration test requires DATABASE_URL")

    claims = {
        "uid": "invitation-race-invitee",
        "email": "invitee@example.test",
        "email_verified": True,
        "name": "Invitation Race Invitee",
    }
    monkeypatch.setattr(auth_api, "_verify_firebase_token", lambda _token: claims)

    engine = create_engine(database_url, pool_pre_ping=True)
    organization_id, admin_id, membership_id, invitation_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    token = "fixture-invitation-token-12345"
    try:
        with Session(engine) as db:
            db.add(Organization(
                id=organization_id, name=f"invitation-race-{organization_id}",
                external_identifier=str(organization_id),
            ))
            db.commit()

        with Session(engine) as db:
            db.add(User(
                id=admin_id, organization_id=organization_id,
                external_subject=str(admin_id), email=f"{admin_id}@example.test",
                display_name="Invitation Administrator",
                role="organization_admin", status="ACTIVE",
            ))
            db.commit()

        with Session(engine) as db:
            db.add(OrganizationMembership(
                id=membership_id, organization_id=organization_id,
                user_id=admin_id, role="organization_admin", status="ACTIVE",
            ))
            db.add(OrganizationInvitation(
                id=invitation_id, organization_id=organization_id,
                email="invitee@example.test", role="reviewer",
                token_hash=auth_api._hash_invitation_token(token),
                status="PENDING", invited_by=admin_id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            ))
            db.commit()

        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def accept():
            try:
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    result = auth_api.accept_organization_invitation(
                        auth_api.InvitationAcceptance(token=token),
                        authorization="Bearer fixture-token",
                        db=db,
                    )
                    outcomes.append(("accepted", result["status"]))
            except HTTPException as exc:
                outcomes.append(("accept-rejected", exc.status_code))
            except Exception as exc:
                errors.append(exc)

        def revoke():
            try:
                with Session(engine) as db:
                    barrier.wait(timeout=10)
                    result = auth_api.revoke_organization_invitation(
                        invitation_id=str(invitation_id),
                        principal=Principal(
                            user_id=admin_id, organization_id=organization_id,
                            role="organization_admin", subject=str(admin_id),
                        ),
                        db=db,
                    )
                    outcomes.append(("revoked", result["status"]))
            except HTTPException as exc:
                outcomes.append(("revoke-rejected", exc.status_code))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=accept), threading.Thread(target=revoke)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert not errors
        assert len(outcomes) == 2
        successes = [item for item in outcomes if item[0] in {"accepted", "revoked"}]
        rejections = [item for item in outcomes if item[0] in {"accept-rejected", "revoke-rejected"}]
        assert len(successes) == 1
        assert len(rejections) == 1
        assert rejections[0][1] == 409

        with Session(engine) as db:
            invitation = db.get(OrganizationInvitation, invitation_id)
            assert invitation is not None
            assert invitation.status in {"ACCEPTED", "REVOKED"}
            if invitation.status == "REVOKED":
                assert invitation.revoked_at is not None
            else:
                assert invitation.accepted_at is not None
    finally:
        with Session(engine) as db:
            db.query(OrganizationInvitation).filter(
                OrganizationInvitation.id == invitation_id
            ).delete()
            db.query(OrganizationMembership).filter(
                OrganizationMembership.organization_id == organization_id
            ).delete()
            db.query(User).filter(
                User.organization_id == organization_id
            ).delete()
            db.query(Organization).filter(
                Organization.id == organization_id
            ).delete()
            db.commit()
        engine.dispose()
