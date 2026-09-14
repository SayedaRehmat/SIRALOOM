from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.api.v1.health import _check_artifact_root
from backend.app.main import app


def test_liveness_probe_is_external_service_independent():
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "SIRALOOM Variant API"}


def test_readiness_reports_dependency_state_without_secrets(monkeypatch, tmp_path):
    import backend.app.api.v1.health as health

    monkeypatch.setattr(health, "_check_database", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))
    monkeypatch.setattr(health.settings, "app_env", "production")
    monkeypatch.setattr(health.settings, "firebase_auth_required", True)
    monkeypatch.setattr(health.settings, "firebase_project_id", "demo-project")

    client = TestClient(app)
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["checks"]["database"]["status"] == "ok"
    assert payload["checks"]["redis"]["status"] == "ok"
    assert payload["checks"]["firebase"]["configured"] is True
    assert "API_KEY" not in response.text
    assert "PASSWORD" not in response.text


def test_readiness_fails_when_required_firebase_is_unconfigured(monkeypatch):
    import backend.app.api.v1.health as health

    monkeypatch.setattr(health, "_check_database", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))
    monkeypatch.setattr(health.settings, "app_env", "production")
    monkeypatch.setattr(health.settings, "firebase_auth_required", True)
    monkeypatch.setattr(health.settings, "firebase_project_id", None)

    client = TestClient(app)
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["firebase"]["status"] == "error"


def test_artifact_readiness_probe_writes_and_removes_only_probe(tmp_path, monkeypatch):
    import backend.app.api.v1.health as health

    monkeypatch.setattr(health.settings, "artifact_root", str(tmp_path))
    status, error = _check_artifact_root()
    assert status == "ok"
    assert error is None
    assert not (Path(tmp_path) / ".siraloom-readiness-probe").exists()
