import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.workflows.variant import _materialize_artifact_for_worker


class FakeDB:
    def __init__(self, organization_id):
        self.organization_id = organization_id

    def get(self, model, _case_id):
        from backend.app.infrastructure.db.models import Case

        assert model is Case
        return SimpleNamespace(organization_id=self.organization_id)


def test_artifact_upload_store_uses_organization_storage_binding(monkeypatch):
    from uuid import uuid4

    from backend.app.api.v1 import artifacts as artifact_routes

    organization_id = uuid4()
    expected_store = object()
    calls = []

    def resolve(db, *, organization_id):
        calls.append((db, organization_id))
        return expected_store

    monkeypatch.setattr(artifact_routes, "artifact_store_for_organization", resolve)

    result = artifact_routes._store("db-session", organization_id)

    assert result is expected_store
    assert calls == [("db-session", organization_id)]


def test_materialize_local_file_uri_returns_existing_path(monkeypatch, tmp_path):
    import backend.app.workflows.variant as workflow
    from backend.app.infrastructure.artifacts.store import ArtifactStore

    payload = b"##fileformat=VCFv4.2\n"
    root = tmp_path / "artifacts"
    source = root / "case" / "artifact" / "input.vcf"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    case_id, organization_id = "case-id", "organization-id"
    monkeypatch.setattr(
        workflow,
        "artifact_store_for_uri",
        lambda db, *, organization_id, storage_uri: ArtifactStore(root),
    )
    artifact = SimpleNamespace(
        id="artifact-local",
        case_id=case_id,
        storage_uri=source.as_uri(),
        filename="input.vcf",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )
    temporary_paths = []

    result = _materialize_artifact_for_worker(
        FakeDB(organization_id), artifact, temporary_paths
    )

    assert result == source
    assert result.read_text(encoding="utf-8").startswith("##fileformat")
    assert temporary_paths == []


def test_materialize_cloud_artifact_downloads_worker_local_copy(monkeypatch):
    import backend.app.workflows.variant as workflow

    organization_id = "organization-id"
    case_id = "case-id"

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

    fake_store = FakeFirebaseArtifactStore("test-bucket")

    def resolve_uri(db, *, organization_id, storage_uri):
        assert organization_id == "organization-id"
        assert storage_uri.startswith("gs://test-bucket/")
        return fake_store

    monkeypatch.setattr(workflow, "artifact_store_for_uri", resolve_uri)

    artifact = SimpleNamespace(
        id="artifact-cloud",
        case_id=case_id,
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf.gz",
        sha256=hashlib.sha256(b"##fileformat=VCFv4.2\n").hexdigest(),
        size_bytes=len(b"##fileformat=VCFv4.2\n"),
    )
    temporary_paths = []

    result = _materialize_artifact_for_worker(
        FakeDB(organization_id), artifact, temporary_paths
    )

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
    from backend.app.domain.storage_profiles import StorageProfileError

    monkeypatch.setattr(
        workflow,
        "artifact_store_for_uri",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            StorageProfileError("unassigned")
        ),
    )

    artifact = SimpleNamespace(
        id="artifact-cloud",
        case_id="case-id",
        storage_uri="gs://test-bucket/case/artifact/input.vcf",
        filename="input.vcf",
        sha256=hashlib.sha256(b"##fileformat=VCFv4.2\n").hexdigest(),
        size_bytes=len(b"##fileformat=VCFv4.2\n"),
    )

    with pytest.raises(RuntimeError, match="not assigned to its organization"):
        _materialize_artifact_for_worker(FakeDB("organization-id"), artifact, [])


def test_materialize_local_artifact_rejects_persisted_digest_mismatch(monkeypatch, tmp_path):
    import backend.app.workflows.variant as workflow
    from backend.app.infrastructure.artifacts.store import ArtifactStore

    source = tmp_path / "case" / "artifact" / "input.vcf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"tampered bytes")
    root = tmp_path
    monkeypatch.setattr(
        workflow,
        "artifact_store_for_uri",
        lambda db, *, organization_id, storage_uri: ArtifactStore(root),
    )
    artifact = SimpleNamespace(
        id="artifact-local",
        case_id="case-id",
        storage_uri=source.as_uri(),
        filename="input.vcf",
        sha256="0" * 64,
        size_bytes=14,
    )

    with pytest.raises(ValueError, match="do not match persisted"):
        _materialize_artifact_for_worker(FakeDB("organization-id"), artifact, [])
