import hashlib
from pathlib import Path

import pytest

from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore


class FakeBlob:
    def __init__(self, payload: bytes, sha256: str | None):
        self.payload = payload
        self.metadata = {"sha256": sha256} if sha256 is not None else {}

    def download_to_filename(self, filename: str) -> None:
        Path(filename).write_bytes(self.payload)


class FakeBucket:
    def __init__(self, blob: FakeBlob):
        self._blob = blob

    def blob(self, object_name: str) -> FakeBlob:
        assert object_name == "case/artifact/input.vcf"
        return self._blob


def _store(payload: bytes, sha256: str | None) -> FirebaseArtifactStore:
    store = FirebaseArtifactStore("test-bucket")
    store._bucket = FakeBucket(FakeBlob(payload, sha256))
    return store


def test_download_to_file_verifies_object_sha256_metadata(tmp_path):
    payload = b"##fileformat=VCFv4.2\n"
    digest = hashlib.sha256(payload).hexdigest()
    store = _store(payload, digest)

    destination = tmp_path / "input.vcf"
    result = store.download_to_file("gs://test-bucket/case/artifact/input.vcf", destination)

    assert result == destination
    assert destination.read_bytes() == payload


def test_download_to_file_fails_closed_on_sha256_mismatch(tmp_path):
    payload = b"corrupted payload\n"
    store = _store(payload, "0" * 64)

    destination = tmp_path / "input.vcf"

    with pytest.raises(RuntimeError, match="SHA-256 mismatch"):
        store.download_to_file("gs://test-bucket/case/artifact/input.vcf", destination)

    assert not destination.exists()


def test_download_to_file_honors_explicit_expected_size(tmp_path):
    payload = b"small artifact\n"
    digest = hashlib.sha256(payload).hexdigest()
    store = _store(payload, digest)

    destination = tmp_path / "input.vcf"

    with pytest.raises(RuntimeError, match="size mismatch"):
        store.download_to_file(
            "gs://test-bucket/case/artifact/input.vcf",
            destination,
            expected_size_bytes=len(payload) + 1,
        )

    assert not destination.exists()
