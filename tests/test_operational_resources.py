from gzip import open as gzip_open
from pathlib import Path
import pytest

from backend.app.domain.resource_capacity import format_bytes, plan_download
from backend.app.domain.local_resources import LocalResourceNotFound, resolve_local_path, resolve_or_require_staging


def test_storage_plan_blocks_when_required_space_exceeds_available(monkeypatch, tmp_path):
    class Usage:
        free = 100
    monkeypatch.setattr("backend.app.domain.resource_capacity.shutil.disk_usage", lambda _: Usage())
    plan = plan_download(destination=tmp_path, artifact_bytes=100, overhead_ratio=0, reserve_bytes=1)
    assert plan.status == "SPACE_REQUIRED"
    assert plan.required_bytes == 101


def test_storage_plan_is_ready_with_capacity(monkeypatch, tmp_path):
    class Usage:
        free = 1000
    monkeypatch.setattr("backend.app.domain.resource_capacity.shutil.disk_usage", lambda _: Usage())
    plan = plan_download(destination=tmp_path, artifact_bytes=100, overhead_ratio=0.2, reserve_bytes=1)
    assert plan.status == "READY"


def test_local_resource_resolution_prefers_configured_path(tmp_path):
    resource = tmp_path / "resource"
    resource.write_text("ok")
    assert resolve_local_path(configured_path=str(resource)).resolve() == resource.resolve()


def test_missing_local_resource_becomes_staging_requirement(tmp_path):
    result = resolve_or_require_staging(configured_path=str(tmp_path / "missing"))
    assert result["status"] == "STAGING_REQUIRED"


def test_missing_local_resource_can_be_hard_blocked(tmp_path):
    with pytest.raises(LocalResourceNotFound):
        resolve_local_path(configured_path=str(tmp_path / "missing"))


def test_format_bytes_is_human_readable():
    assert format_bytes(1024 * 1024) == "1.0 MiB"
