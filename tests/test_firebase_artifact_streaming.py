from pathlib import Path

from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore


class FakeBlob:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.downloaded_to = None
        self.metadata = None

    def download_to_filename(self, filename):
        self.downloaded_to = Path(filename)
        self.downloaded_to.write_bytes(self.payload)

    def open(self, mode):
        assert mode == "rb"
        import io
        return io.BytesIO(self.payload)


def test_download_to_file_does_not_use_download_as_bytes(monkeypatch, tmp_path):
    store = FirebaseArtifactStore("test-bucket")
    blob = FakeBlob(b"x" * (1024 * 1024))
    monkeypatch.setattr(store, "_blob_from_uri", lambda uri: blob)
    target = tmp_path / "large.vcf.gz"

    result = store.download_to_file("gs://test-bucket/large.vcf.gz", target)

    assert result == target
    assert target.stat().st_size == 1024 * 1024
    assert blob.downloaded_to == target


def test_iter_bytes_yields_bounded_chunks(monkeypatch):
    store = FirebaseArtifactStore("test-bucket")
    blob = FakeBlob(b"abcdefghij")
    monkeypatch.setattr(store, "_blob_from_uri", lambda uri: blob)

    chunks = list(store.iter_bytes("gs://test-bucket/test.bin", chunk_size=4))

    assert chunks == [b"abcd", b"efgh", b"ij"]
