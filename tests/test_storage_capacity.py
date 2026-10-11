from pathlib import Path
from collections import namedtuple

from backend.app.config import settings
from backend.app.domain import storage_capacity


Usage = namedtuple("Usage", "total used free")


def test_capacity_preflight_reports_storage_and_configured_upload_limit(monkeypatch, tmp_path):
    artifact_root = tmp_path / "artifacts"
    scratch_root = tmp_path / "scratch"
    resource_root = tmp_path / "resources"
    for path in (artifact_root, scratch_root, resource_root):
        path.mkdir()
    monkeypatch.setattr(settings, "artifact_root", str(artifact_root))
    monkeypatch.setattr(settings, "worker_scratch_root", str(scratch_root))
    monkeypatch.setattr(settings, "resource_cache_root", str(resource_root))
    monkeypatch.setattr(settings, "storage_capacity_preflight_enabled", True)
    monkeypatch.setattr(settings, "max_artifact_upload_bytes", 512 * 1024 * 1024)

    result = storage_capacity.inspect_deployment_capacity()
    assert result["status"] == "READY"
    assert result["capacity_preflight_enabled"] is True
    assert result["max_artifact_upload_bytes"] == 512 * 1024 * 1024
    assert {root["label"] for root in result["roots"]} == {"artifact_store", "worker_scratch", "resource_cache"}
    assert all(root["free_bytes"] is not None for root in result["roots"])
    assert all("_device_id" not in root for root in result["roots"])


def test_analysis_preflight_blocks_when_shared_filesystem_has_insufficient_capacity(monkeypatch, tmp_path):
    artifact_root = tmp_path / "artifacts"
    scratch_root = tmp_path / "scratch"
    artifact_root.mkdir()
    scratch_root.mkdir()
    monkeypatch.setattr(settings, "artifact_root", str(artifact_root))
    monkeypatch.setattr(settings, "worker_scratch_root", str(scratch_root))
    monkeypatch.setattr(settings, "storage_capacity_preflight_enabled", True)
    monkeypatch.setattr(settings, "analysis_artifact_output_multiplier", 1.0)
    monkeypatch.setattr(settings, "analysis_scratch_multiplier", 2.0)
    monkeypatch.setattr(settings, "analysis_storage_headroom_bytes", 10)
    monkeypatch.setattr(storage_capacity.shutil, "disk_usage", lambda _path: Usage(1000, 900, 100))

    result = storage_capacity.preflight_analysis_capacity(100)
    assert result["status"] == "BLOCKED"
    issue = next(item for item in result["issues"] if item["code"] == "INSUFFICIENT_STORAGE_CAPACITY")
    assert issue["required_bytes"] == 320
    assert issue["available_bytes"] == 100
    assert result["reservation_supported"] is False


def test_analysis_preflight_blocks_if_configured_storage_root_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_root", str(tmp_path / "missing-artifacts"))
    monkeypatch.setattr(settings, "worker_scratch_root", str(tmp_path / "missing-scratch"))
    monkeypatch.setattr(settings, "storage_capacity_preflight_enabled", True)
    result = storage_capacity.preflight_analysis_capacity(100)
    assert result["status"] == "BLOCKED"
    assert any(issue["code"] == "STORAGE_PATH_MISSING" for issue in result["issues"])


def test_analysis_preflight_is_explicitly_not_configured_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "storage_capacity_preflight_enabled", False)
    result = storage_capacity.preflight_analysis_capacity(100)
    assert result["status"] == "NOT_CONFIGURED"
    assert result["enabled"] is False
    assert result["reservation_supported"] is False



def test_production_compose_mounts_the_same_scratch_path_for_api_and_worker():
    compose_path = Path(__file__).resolve().parents[1] / "docker-compose.production.yml"
    compose = compose_path.read_text(encoding="utf-8")
    api_block = compose.split("  api:\\n", 1)[1].split("\\n  worker:", 1)[0]
    worker_block = compose.split("  worker:\\n", 1)[1].split("\\n  frontend:", 1)[0]
    expected_mount = "${SIRALOOM_SCRATCH_HOST_PATH:-scratch_data}:/data/siraloom/scratch"
    assert expected_mount in api_block
    assert expected_mount in worker_block
    assert "TMPDIR: /data/siraloom/scratch" in api_block
    assert "TMPDIR: /data/siraloom/scratch" in worker_block
