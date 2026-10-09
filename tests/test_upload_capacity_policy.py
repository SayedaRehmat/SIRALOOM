from uuid import uuid4

from backend.app.application import entitlements


def test_effective_upload_limit_uses_deployment_cap_when_no_entitlement(monkeypatch):
    organization_id = uuid4()
    monkeypatch.setattr(entitlements, "get_entitlement", lambda _db, _org: None)

    assert entitlements.effective_max_upload_bytes(
        object(), organization_id, 2 * 1024 * 1024 * 1024
    ) == 2 * 1024 * 1024 * 1024


def test_effective_upload_limit_respects_lower_trial_cap(monkeypatch):
    organization_id = uuid4()
    monkeypatch.setattr(
        entitlements,
        "get_entitlement",
        lambda _db, _org: type("Entitlement", (), {"max_vcf_size_bytes": 32 * 1024 * 1024})(),
    )

    assert entitlements.effective_max_upload_bytes(
        object(), organization_id, 2 * 1024 * 1024 * 1024
    ) == 32 * 1024 * 1024


def test_effective_upload_limit_never_exceeds_deployment_cap(monkeypatch):
    organization_id = uuid4()
    monkeypatch.setattr(
        entitlements,
        "get_entitlement",
        lambda _db, _org: type("Entitlement", (), {"max_vcf_size_bytes": 4 * 1024 * 1024 * 1024})(),
    )

    assert entitlements.effective_max_upload_bytes(
        object(), organization_id, 1024 * 1024 * 1024
    ) == 1024 * 1024 * 1024
