from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from backend.app.auth import principal


def _bearer_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/session",
            "headers": [(b"authorization", b"Bearer verified-test-token")],
            "query_string": b"",
        }
    )


class PrincipalSession:
    def __init__(self, user, membership):
        self.rows = iter((user, membership))

    def scalar(self, statement):
        row = next(self.rows)
        if not hasattr(row, "external_subject") and getattr(row, "status", None) != "ACTIVE":
            return None
        return row


def test_principal_uses_active_membership_role_not_stale_user_role(monkeypatch):
    user_id = uuid4()
    organization_id = uuid4()
    user = type("UserRow", (), {
        "id": user_id,
        "organization_id": organization_id,
        "external_subject": "firebase-subject-1",
        "role": "organization_admin",
        "email": "member@example.test",
        "status": "ACTIVE",
    })()
    membership = type("MembershipRow", (), {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "read_only",
        "status": "ACTIVE",
    })()
    monkeypatch.setattr(
        principal,
        "_verify_firebase_token",
        lambda token: {"uid": "firebase-subject-1", "email": "member@example.test", "email_verified": True},
    )

    resolved = principal.get_current_principal(
        _bearer_request(),
        db=PrincipalSession(user, membership),
    )

    assert resolved.user_id == user_id
    assert resolved.organization_id == organization_id
    assert resolved.role == "read_only"


@pytest.mark.parametrize("membership_status", ["SUSPENDED", "REVOKED"])
def test_principal_rejects_suspended_or_revoked_membership(monkeypatch, membership_status):
    user_id = uuid4()
    organization_id = uuid4()
    user = type("UserRow", (), {
        "id": user_id,
        "organization_id": organization_id,
        "external_subject": "firebase-subject-2",
        "role": "organization_admin",
        "email": "member@example.test",
        "status": "ACTIVE",
    })()
    membership = type("MembershipRow", (), {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "organization_admin",
        "status": membership_status,
    })()
    monkeypatch.setattr(
        principal,
        "_verify_firebase_token",
        lambda token: {"uid": "firebase-subject-2", "email": "member@example.test", "email_verified": True},
    )

    with pytest.raises(HTTPException) as error:
        principal.get_current_principal(
            _bearer_request(),
            db=PrincipalSession(user, membership),
        )

    assert error.value.status_code == 403
    assert error.value.detail == "No active SIRALOOM organization membership"


def test_principal_rejects_unknown_role_in_active_membership(monkeypatch):
    user_id = uuid4()
    organization_id = uuid4()
    user = type("UserRow", (), {
        "id": user_id,
        "organization_id": organization_id,
        "external_subject": "firebase-subject-3",
        "role": "organization_admin",
        "email": "member@example.test",
        "status": "ACTIVE",
    })()
    membership = type("MembershipRow", (), {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "superuser",
        "status": "ACTIVE",
    })()
    monkeypatch.setattr(
        principal,
        "_verify_firebase_token",
        lambda token: {"uid": "firebase-subject-3", "email": "member@example.test", "email_verified": True},
    )

    with pytest.raises(HTTPException) as error:
        principal.get_current_principal(
            _bearer_request(),
            db=PrincipalSession(user, membership),
        )

    assert error.value.status_code == 403


def test_principal_rejects_unverified_firebase_email_before_database_access(monkeypatch):
    monkeypatch.setattr(
        principal,
        "_verify_firebase_token",
        lambda token: {"uid": "firebase-subject-unverified", "email_verified": False},
    )

    class UntouchedDB:
        def scalar(self, statement):
            raise AssertionError("Unverified identity must be rejected before user lookup")

    with pytest.raises(HTTPException) as error:
        principal.get_current_principal(_bearer_request(), db=UntouchedDB())

    assert error.value.status_code == 403
    assert error.value.detail == "A verified Firebase email is required"


def test_principal_rejects_inactive_local_user_with_active_membership(monkeypatch):
    user_id = uuid4()
    organization_id = uuid4()
    user = type("UserRow", (), {
        "id": user_id,
        "organization_id": organization_id,
        "external_subject": "firebase-subject-inactive",
        "role": "organization_admin",
        "email": "member@example.test",
        "status": "INACTIVE",
    })()
    membership = type("MembershipRow", (), {
        "user_id": user_id,
        "organization_id": organization_id,
        "role": "organization_admin",
        "status": "ACTIVE",
    })()
    monkeypatch.setattr(
        principal,
        "_verify_firebase_token",
        lambda token: {"uid": "firebase-subject-inactive", "email_verified": True},
    )

    with pytest.raises(HTTPException) as error:
        principal.get_current_principal(
            _bearer_request(),
            db=PrincipalSession(user, membership),
        )

    assert error.value.status_code == 403
    assert error.value.detail == "This SIRALOOM account is inactive"
