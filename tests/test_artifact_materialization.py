import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.workflows.variant import _materialize_artifact_for_worker


def test_materialize_local_file_uri_returns_existing_path(tmp_path):
    payload = b"##fileformat=VCFv4.2\n"
    source = tmp_path / "input.vcf"
    source.write_bytes(payload)
    artifact = SimpleNamespace(
        id="artifact-local",
        storage_uri=source.as_uri(),
        filename="input.vcf",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
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

        def download_to_file(self, uri, destination, *, expected_sha256, expected_size_bytes):
            assert uri == "gs://test-bucket/case/artifact/input.vcf"
            payload = b"##fileformat=VCFv4.2\n"
            assert expected_sha256 == hashlib.sha256(payload).hexdigest()
            assert expected_size_bytes == len(payload)
            Path(destination).write_bytes(payload)
            return Path(destination)

    monkeypatch.setattr(workflow.settings, "firebase_storage_enabled", True)
    monkeypatch.setattr(workflow.settings, "firebase_storage_bucket", "test-bucket")
    monkeypatch.setattr(workflow, "FirebaseArtifactStore", FakeFirebaseArtifactStore)

    artifact = SimpleNamespace(
        id="artifact-cloud",
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf.gz",
        sha256=hashlib.sha256(b"##fileformat=VCFv4.2\n").hexdigest(),
        size_bytes=len(b"##fileformat=VCFv4.2\n"),
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
    import backend.app.workflows.variant as workflow

    monkeypatch.setattr(workflow.settings, "firebase_storage_enabled", False)
    monkeypatch.setattr(workflow.settings, "firebase_storage_bucket", None)

    artifact = SimpleNamespace(
        id="artifact-cloud",
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf",
        sha256=hashlib.sha256(b"##fileformat=VCFv4.2\n").hexdigest(),
        size_bytes=len(b"##fileformat=VCFv4.2\n"),
    )

    with pytest.raises(RuntimeError, match="cloud storage is not configured"):
        _materialize_artifact_for_worker(artifact, [])


def test_materialize_local_artifact_rejects_persisted_digest_mismatch(tmp_path):
    source = tmp_path / "input.vcf"
    source.write_bytes(b"tampered bytes")
    artifact = SimpleNamespace(
        id="artifact-local",
        storage_uri=source.as_uri(),
        filename="input.vcf",
        sha256="0" * 64,
        size_bytes=14,
    )

    with pytest.raises(ValueError, match="do not match persisted"):
        _materialize_artifact_for_worker(artifact, [])
