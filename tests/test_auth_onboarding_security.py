from backend.app.api.v1.auth import OrganizationOnboarding, _first_organization_bootstrap_is_available, create_first_organization
from backend.app.config import settings


class _Dialect:
    name = "sqlite"


class _Bind:
    dialect = _Dialect()


class _BootstrapDb:
    bind = _Bind()

    def __init__(self, organization_count: int):
        self.organization_count = organization_count

    def scalar(self, _statement):
        return self.organization_count


def test_production_organization_self_signup_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(settings, "organization_self_signup_enabled", False)
    monkeypatch.setattr(settings, "organization_first_bootstrap_enabled", False)

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


def test_first_laboratory_bootstrap_is_available_only_for_an_empty_deployment(monkeypatch):
    monkeypatch.setattr(settings, "organization_first_bootstrap_enabled", True)

    assert _first_organization_bootstrap_is_available(_BootstrapDb(0)) is True
    assert _first_organization_bootstrap_is_available(_BootstrapDb(1)) is False


def test_first_laboratory_bootstrap_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "organization_first_bootstrap_enabled", False)

    assert _first_organization_bootstrap_is_available(_BootstrapDb(0)) is False
