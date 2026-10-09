from pathlib import Path
from types import SimpleNamespace

from backend.app.workflows.variant import _materialize_artifact_for_worker


def test_materialize_local_file_uri_returns_existing_path(tmp_path):
    source = tmp_path / "input.vcf"
    source.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
    artifact = SimpleNamespace(
        id="artifact-local",
        storage_uri=source.as_uri(),
        filename="input.vcf",
    )
    temporary_paths = []

    result = _materialize_artifact_for_worker(artifact, temporary_paths)

    assert result == source
    assert result.read_text(encoding="utf-8").startswith("##fileformat")
    assert temporary_paths == []


def test_materialize_cloud_artifact_downloads_worker_local_copy(monkeypatch):
    import backend.app.workflows.variant as workflow

    class FakeFirebaseArtifactStore:
        def __init__(self, bucket):
            assert bucket == "test-bucket"

        def download_to_file(self, uri, destination):
            assert uri == "gs://test-bucket/case/artifact/input.vcf"
            Path(destination).write_bytes(b"##fileformat=VCFv4.2\n")
            return Path(destination)

    monkeypatch.setattr(workflow.settings, "firebase_storage_enabled", True)
    monkeypatch.setattr(workflow.settings, "firebase_storage_bucket", "test-bucket")
    monkeypatch.setattr(workflow, "FirebaseArtifactStore", FakeFirebaseArtifactStore)

    artifact = SimpleNamespace(
        id="artifact-cloud",
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf.gz",
    )
    temporary_paths = []

    result = _materialize_artifact_for_worker(artifact, temporary_paths)

    try:
        assert result.is_file()
        assert result.suffix == ".gz"
        assert result.read_bytes() == b"##fileformat=VCFv4.2\n"
        assert temporary_paths == [result]
    finally:
        for path in temporary_paths:
            path.unlink(missing_ok=True)


def test_materialize_cloud_artifact_fails_closed_without_worker_storage_config(monkeypatch):
    import pytest
    import backend.app.workflows.variant as workflow

    monkeypatch.setattr(workflow.settings, "firebase_storage_enabled", False)
    monkeypatch.setattr(workflow.settings, "firebase_storage_bucket", None)

    artifact = SimpleNamespace(
        id="artifact-cloud",
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf",
    )

    with pytest.raises(RuntimeError, match="cloud storage is not configured"):
        _materialize_artifact_for_worker(artifact, [])
