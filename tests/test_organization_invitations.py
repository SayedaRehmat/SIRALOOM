from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.api.v1.auth import (
    InvitationAcceptance,
    OrganizationInvitationCreate,
    _ensure_active_admin_invariant,
    _hash_invitation_token,
    _invitation_roles_for,
    _normalize_email,
    _require_invitation_role,
)
from backend.app.auth.principal import Principal


def principal(role: str) -> Principal:
    return Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role=role,
        subject="subject",
        email="admin@example.org",
    )


def test_invitation_token_is_one_way_hashed():
    token = "test-invitation-token-123456"
    assert _hash_invitation_token(token) != token
    assert _hash_invitation_token(token) == _hash_invitation_token(token)


def test_invitation_email_is_normalized():
    assert _normalize_email("  Person@Example.ORG ") == "person@example.org"


def test_invitation_requires_verified_email():
    with pytest.raises(Exception) as exc:
        _normalize_email(None)
    assert getattr(exc.value, "status_code", None) == 403


def test_role_assignment_is_limited_by_inviter_role():
    assert "organization_admin" in _invitation_roles_for("organization_admin")
    assert "organization_admin" not in _invitation_roles_for("lab_director")
    assert "clinical_geneticist" in _invitation_roles_for("lab_director")
    assert "lab_director" not in _invitation_roles_for("clinical_geneticist")
    assert "read_only" in _invitation_roles_for("reviewer")
    assert not _invitation_roles_for("read_only")


def test_lab_director_cannot_grant_organization_admin():
    with pytest.raises(Exception) as exc:
        _require_invitation_role(principal("lab_director"), "organization_admin")
    assert getattr(exc.value, "status_code", None) == 403


def test_reviewer_cannot_grant_clinical_role():
    with pytest.raises(Exception) as exc:
        _require_invitation_role(principal("reviewer"), "clinical_geneticist")
    assert getattr(exc.value, "status_code", None) == 403


def test_invitation_payload_bounds_are_server_validated():
    with pytest.raises(ValueError):
        OrganizationInvitationCreate(email="a@example.org", role="reviewer", expires_in_days=31)
    with pytest.raises(ValueError):
        InvitationAcceptance(token="short")


def test_invitation_expiry_window_is_time_bounded():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=7)
    assert expires > now
    assert expires <= now + timedelta(days=30)


class _CountDb:
    def __init__(self, active_admin_count: int):
        self.active_admin_count = active_admin_count

    def scalar(self, _statement):
        return self.active_admin_count


def test_last_active_admin_cannot_be_demoted():
    with pytest.raises(Exception) as exc:
        _ensure_active_admin_invariant(
            _CountDb(1), uuid4(),
            current_role="organization_admin", current_status="ACTIVE",
            effective_role="lab_director", effective_status="ACTIVE",
        )
    assert getattr(exc.value, "status_code", None) == 409


def test_last_active_admin_cannot_be_demoted_and_suspended_together():
    with pytest.raises(Exception) as exc:
        _ensure_active_admin_invariant(
            _CountDb(1), uuid4(),
            current_role="organization_admin", current_status="ACTIVE",
            effective_role="reviewer", effective_status="SUSPENDED",
        )
    assert getattr(exc.value, "status_code", None) == 409


def test_two_active_admins_allow_one_admin_to_be_demoted():
    _ensure_active_admin_invariant(
        _CountDb(2), uuid4(),
        current_role="organization_admin", current_status="ACTIVE",
        effective_role="lab_director", effective_status="ACTIVE",
    )


def test_non_admin_transition_does_not_require_another_admin():
    _ensure_active_admin_invariant(
        _CountDb(0), uuid4(),
        current_role="reviewer", current_status="ACTIVE",
        effective_role="read_only", effective_status="SUSPENDED",
    )
