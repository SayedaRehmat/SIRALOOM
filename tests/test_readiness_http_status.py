from fastapi import Response

from backend.app.api.v1 import health


def test_readiness_returns_503_when_a_required_dependency_is_unavailable(monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: ("error", "OperationalError"))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))

    response = Response()
    body = health.ready(response)

    assert body["status"] == "not_ready"
    assert response.status_code == 503
    assert body["checks"]["database"]["error"] == "OperationalError"


def test_readiness_does_not_expose_raw_dependency_error(monkeypatch):
    monkeypatch.setattr(health, "_check_database", lambda: ("error", "OperationalError"))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))

    response = Response()
    body = health.ready(response)

    assert response.status_code == 503
    assert "password" not in str(body).lower()
    assert "host=private" not in str(body).lower()
