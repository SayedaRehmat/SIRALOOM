from uuid import uuid4

from fastapi import HTTPException, Request
import pytest

from backend.app.auth import principal


def _request_without_authorization() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/cases",
            "headers": [],
            "query_string": b"",
        }
    )


@pytest.mark.parametrize("environment", ["staging", "preview", "production"])
def test_shared_environments_reject_implicit_development_identity(monkeypatch, environment):
    monkeypatch.setattr(principal.settings, "app_env", environment)
    monkeypatch.setattr(principal.settings, "firebase_auth_required", False)

    with pytest.raises(HTTPException) as error:
        principal.get_current_principal(_request_without_authorization(), db=None)

    assert error.value.status_code == 401
    assert error.value.detail == "Bearer authentication is required"


def test_development_environment_keeps_explicit_local_identity_path(monkeypatch):
    expected = principal.Principal(
        user_id=uuid4(),
        organization_id=__import__("uuid").uuid4(),
        role="bioinformatician",
        subject="local-development-user",
    )
    monkeypatch.setattr(principal.settings, "app_env", "development")
    monkeypatch.setattr(principal.settings, "firebase_auth_required", False)
    monkeypatch.setattr(principal, "_development_principal", lambda db: expected)

    actual = principal.get_current_principal(_request_without_authorization(), db=None)

    assert actual == expected
