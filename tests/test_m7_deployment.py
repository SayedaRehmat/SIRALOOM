from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api.v1.health import _check_artifact_root
from backend.app.config import Settings
from backend.app.main import app


def test_liveness_probe_is_external_service_independent():
    client = TestClient(app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "SIRALOOM Variant API"}


def test_readiness_reports_dependency_state_without_secrets(monkeypatch, tmp_path):
    from backend.app.api.v1 import health

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
    from backend.app.api.v1 import health

    monkeypatch.setattr(health, "_check_database", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))
    monkeypatch.setattr(health.settings, "app_env", "production")
    monkeypatch.setattr(health.settings, "firebase_auth_required", True)
    monkeypatch.setattr(health.settings, "firebase_project_id", None)

    client = TestClient(app)
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["firebase"]["status"] == "error"


def test_readiness_does_not_expose_dependency_exception_details(monkeypatch):
    from backend.app.api.v1 import health

    secret = "postgresql://lab-admin:super-secret@db.internal:5432/siraloom"

    def fail_database():
        raise RuntimeError(secret)

    monkeypatch.setattr(health, "SessionLocal", fail_database)
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_artifact_root", lambda: ("ok", None))
    monkeypatch.setattr(health.settings, "app_env", "test")
    monkeypatch.setattr(health.settings, "firebase_auth_required", False)
    monkeypatch.setattr(health.settings, "firebase_project_id", None)

    response = TestClient(app).get("/api/v1/ready")
    assert response.status_code == 503
    assert secret not in response.text
    assert "super-secret" not in response.text
    assert response.json()["checks"]["database"] == {
        "status": "error",
        "error": "DATABASE_UNAVAILABLE",
    }


def test_artifact_readiness_probe_writes_and_removes_only_probe(tmp_path, monkeypatch):
    from backend.app.api.v1 import health

    monkeypatch.setattr(health.settings, "artifact_root", str(tmp_path))
    status, error = _check_artifact_root()
    assert status == "ok"
    assert error is None
    assert not list(Path(tmp_path).glob(".siraloom-readiness-*"))


def test_artifact_readiness_does_not_create_missing_target_root(tmp_path):
    missing_root = tmp_path / "unmounted-lab-target"

    status, error = _check_artifact_root(str(missing_root))

    assert status == "error"
    assert error == "ARTIFACT_STORE_UNAVAILABLE"
    assert not missing_root.exists()


def test_artifact_readiness_probe_does_not_overwrite_or_delete_existing_file(tmp_path):
    sentinel = tmp_path / ".siraloom-readiness-probe"
    sentinel.write_bytes(b"operator-owned-file")

    status, error = _check_artifact_root(str(tmp_path))

    assert status == "ok"
    assert error is None
    assert sentinel.read_bytes() == b"operator-owned-file"
    assert list(tmp_path.glob(".siraloom-readiness-*")) == [sentinel]


def test_readiness_blocks_when_configured_local_lab_target_is_missing(monkeypatch, tmp_path):
    import json
    from uuid import uuid4

    from backend.app.api.v1 import health

    missing_root = tmp_path / "unmounted-lab-target"
    monkeypatch.setattr(health, "_check_database", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    monkeypatch.setattr(health.settings, "artifact_root", str(tmp_path))
    monkeypatch.setattr(
        health.settings,
        "artifact_storage_targets_json",
        json.dumps(
            {
                "lab-a": {
                    "backend_type": "LOCAL_FILESYSTEM",
                    "root": str(missing_root),
                    "organization_id": str(uuid4()),
                }
            }
        ),
    )
    monkeypatch.setattr(health.settings, "app_env", "test")
    monkeypatch.setattr(health.settings, "firebase_auth_required", False)
    monkeypatch.setattr(health.settings, "firebase_project_id", None)

    response = TestClient(app).get("/api/v1/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["organization_artifact_targets"] == {
        "status": "error",
        "error": "ORGANIZATION_ARTIFACT_TARGET_UNAVAILABLE",
    }
    assert not missing_root.exists()


def test_cloud_storage_target_is_probed_and_legacy_local_root_is_not_required(
    monkeypatch, tmp_path
):
    import json
    from uuid import uuid4

    from backend.app.api.v1 import health

    monkeypatch.setattr(
        health.settings,
        "artifact_storage_targets_json",
        json.dumps({
            "lab-cloud": {
                "backend_type": "FIREBASE_GCS",
                "bucket": "lab-cloud.appspot.com",
                "organization_id": str(uuid4()),
            }
        }),
    )
    monkeypatch.setattr(health.settings, "firebase_storage_enabled", True)
    monkeypatch.setattr(health.settings, "artifact_root", str(tmp_path / "unused-local-root"))
    monkeypatch.setattr(health.settings, "app_env", "test")
    monkeypatch.setattr(health.settings, "firebase_auth_required", False)
    monkeypatch.setattr(health.settings, "firebase_project_id", None)
    monkeypatch.setattr(health, "_check_database", lambda: ("ok", None))
    monkeypatch.setattr(health, "_check_redis", lambda: ("ok", None))
    health._CLOUD_PROBE_CACHE.clear()
    probed = []
    monkeypatch.setattr(
        health,
        "probe_configured_firebase_storage_target",
        lambda target_id: probed.append(target_id),
    )

    response = TestClient(app).get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["checks"]["artifact_store"]["status"] == "not_required"
    assert response.json()["checks"]["organization_artifact_targets"]["status"] == "ok"
    assert probed == ["lab-cloud"]
    assert not (tmp_path / "unused-local-root").exists()


def test_cloud_storage_readiness_failure_is_generic_and_cached(monkeypatch):
    import json
    from uuid import uuid4

    from backend.app.api.v1 import health

    monkeypatch.setattr(
        health.settings,
        "artifact_storage_targets_json",
        json.dumps({
            "lab-cloud": {
                "backend_type": "FIREBASE_GCS",
                "bucket": "lab-cloud.appspot.com",
                "organization_id": str(uuid4()),
            }
        }),
    )
    health._CLOUD_PROBE_CACHE.clear()
    count = 0

    def fail_probe(_target_id):
        nonlocal count
        count += 1
        raise RuntimeError("private provider details")

    monkeypatch.setattr(health, "probe_configured_firebase_storage_target", fail_probe)

    result = health._check_organization_artifact_targets()
    assert result == ("error", "ORGANIZATION_ARTIFACT_TARGET_UNAVAILABLE")
    assert "private provider details" not in str(result)
    assert health._check_organization_artifact_targets() == result
    assert count == 1


def test_deployment_health_checks_use_readiness_not_liveness():
    repo_root = Path(__file__).resolve().parents[1]
    compose = (repo_root / "docker-compose.production.yml").read_text(encoding="utf-8")
    render = (repo_root / "render.yaml").read_text(encoding="utf-8")

    assert "http://127.0.0.1:8000/api/v1/ready" in compose
    assert "http://127.0.0.1:8000/api/v1/health" not in compose
    assert "healthCheckPath: /api/v1/ready" in render


def test_production_compose_requires_redis_auth_for_all_celery_clients():
    repo_root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load(
        (repo_root / "docker-compose.production.yml").read_text(encoding="utf-8")
    )
    redis = compose["services"]["redis"]
    redis_password = "${REDIS_PASSWORD:?Set REDIS_PASSWORD}"
    authenticated_url = "redis://:${REDIS_PASSWORD:?Set REDIS_PASSWORD}@redis:6379/0"

    assert not redis.get("ports")
    assert redis["environment"]["REDIS_PASSWORD"] == redis_password
    assert redis["command"][-2:] == ["--requirepass", redis_password]
    assert "REDISCLI_AUTH" in redis["healthcheck"]["test"][1]
    for service_name in ("api", "worker", "beat"):
        assert compose["services"][service_name]["environment"]["REDIS_URL"] == authenticated_url


def test_local_storage_target_override_mounts_each_lab_root_into_api_and_worker():
    repo_root = Path(__file__).resolve().parents[1]
    override = yaml.safe_load(
        (repo_root / "deployment/storage-targets-local.compose.example.yml").read_text(
            encoding="utf-8"
        )
    )
    expected = {
        "${SIRALOOM_LAB_A_ARTIFACT_HOST_PATH:?Set the lab A artifact directory}":
            "/data/siraloom/labs/lab-a/artifacts",
        "${SIRALOOM_LAB_B_ARTIFACT_HOST_PATH:?Set the lab B artifact directory}":
            "/data/siraloom/labs/lab-b/artifacts",
    }

    for service_name in ("api", "worker"):
        mounts = override["services"][service_name]["volumes"]
        assert {mount["source"]: mount["target"] for mount in mounts} == expected
        assert all(mount["type"] == "bind" for mount in mounts)
        assert all(mount["bind"]["create_host_path"] is False for mount in mounts)

    assert override["services"]["api"]["volumes"] == override["services"]["worker"]["volumes"]


def test_production_settings_reject_unauthenticated_redis_url():
    with pytest.raises(ValidationError, match="AUTH secret of at least 32 characters"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://user:pass@db/siraloom",
            redis_url="redis://redis:6379/0",
        )


@pytest.mark.parametrize(
    "redis_url",
    [
        "redis://:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6@redis:6379/0",
        "rediss://default:a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6@redis.example:6380/0",
    ],
)
def test_production_settings_accept_authenticated_redis_urls(redis_url):
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="postgresql+psycopg://user:pass@db/siraloom",
        redis_url=redis_url,
    )
    assert settings.redis_url == redis_url


def test_production_settings_reject_weak_redis_auth_secret():
    with pytest.raises(ValidationError, match="AUTH secret of at least 32 characters"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+psycopg://user:pass@db/siraloom",
            redis_url="redis://:CHANGE_ME@redis:6379/0",
        )


def test_development_settings_allow_local_unauthenticated_redis():
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="sqlite://",
        redis_url="redis://localhost:6379/0",
    )
    assert settings.redis_url == "redis://localhost:6379/0"
