from backend.app.api.v1.auth import OrganizationOnboarding, create_first_organization
from backend.app.config import settings


def test_production_organization_self_signup_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "organization_self_signup_enabled", False)

    try:
        create_first_organization(OrganizationOnboarding(organization_name="Test Laboratory"), authorization=None, db=None)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
        assert "self-signup is disabled" in str(getattr(exc, "detail", "")).lower()
    else:
        raise AssertionError("Organization self-signup must be explicitly enabled")


def test_organization_self_signup_policy_is_explicitly_configurable(monkeypatch):
    monkeypatch.setattr(settings, "organization_self_signup_enabled", True)
    assert settings.organization_self_signup_enabled is True

    monkeypatch.setattr(settings, "organization_self_signup_enabled", False)
    assert settings.organization_self_signup_enabled is False
