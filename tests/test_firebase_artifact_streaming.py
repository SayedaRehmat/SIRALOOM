from pathlib import Path
from types import SimpleNamespace

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


def test_cloud_readiness_probe_uses_unique_generation_guarded_object_and_deletes_it():
    class ProbeBlob:
        generation = None

        def __init__(self):
            self.calls = []

        def upload_from_string(self, payload, **kwargs):
            self.calls.append(("upload", payload, kwargs))
            self.generation = 17

        def reload(self, **kwargs):
            self.calls.append(("reload", kwargs))

        def download_as_bytes(self, **kwargs):
            self.calls.append(("download", kwargs))
            return b"siraloom-storage-readiness-v1"

        def delete(self, **kwargs):
            self.calls.append(("delete", kwargs))

    class ProbeBucket:
        def __init__(self):
            self.name = None
            self.probe_blob = ProbeBlob()

        def blob(self, name):
            self.name = name
            return self.probe_blob

    store = FirebaseArtifactStore("test-bucket")
    bucket = ProbeBucket()
    store._bucket = bucket

    store.probe(timeout_seconds=2)

    assert bucket.name.startswith("_siraloom/readiness/")
    assert bucket.probe_blob.calls[0][0] == "upload"
    assert bucket.probe_blob.calls[0][2]["if_generation_match"] == 0
    assert bucket.probe_blob.calls[2] == (
        "download",
        {"if_generation_match": 17, "timeout": 2},
    )
    assert bucket.probe_blob.calls[-1] == (
        "delete",
        {"if_generation_match": 17, "timeout": 2},
    )


def test_cloud_readiness_probe_cleans_up_after_read_failure():
    import pytest

    class ProbeBlob:
        generation = 23

        def __init__(self):
            self.deleted_generation = None

        def upload_from_string(self, payload, **kwargs):
            pass

        def reload(self, **kwargs):
            pass

        def download_as_bytes(self, **kwargs):
            raise RuntimeError("provider read failed")

        def delete(self, **kwargs):
            self.deleted_generation = kwargs["if_generation_match"]

    class ProbeBucket:
        def __init__(self):
            self.probe_blob = ProbeBlob()

        def blob(self, _name):
            return self.probe_blob

    store = FirebaseArtifactStore("test-bucket")
    bucket = ProbeBucket()
    store._bucket = bucket

    with pytest.raises(RuntimeError, match="provider read failed"):
        store.probe()
    assert bucket.probe_blob.deleted_generation == 23


def test_named_firebase_apps_use_target_scoped_credentials_and_bucket(monkeypatch, tmp_path):
    import firebase_admin
    from firebase_admin import credentials, storage

    from backend.app.config import settings

    apps = {}
    initializations = []

    def get_app(name="[DEFAULT]"):
        if name not in apps:
            raise ValueError("app not initialized")
        return apps[name]

    def initialize_app(credential, options, name="[DEFAULT]"):
        app = SimpleNamespace(name=name, credential=credential, options=options)
        apps[name] = app
        initializations.append((credential, options, name))
        return app

    monkeypatch.setattr(firebase_admin, "get_app", get_app)
    monkeypatch.setattr(firebase_admin, "initialize_app", initialize_app)
    monkeypatch.setattr(credentials, "Certificate", lambda path: ("certificate", path))
    monkeypatch.setattr(credentials, "ApplicationDefault", lambda: "application-default")
    monkeypatch.setattr(storage, "bucket", lambda name=None, app=None: (name, app))
    monkeypatch.setattr(settings, "firebase_credentials_path", "/secrets/firebase-auth.json")

    credential_a = tmp_path / "lab-a-service-account.json"
    credential_b = tmp_path / "lab-b-service-account.json"
    credential_a.write_text("{}", encoding="utf-8")
    credential_b.write_text("{}", encoding="utf-8")
    store_a = FirebaseArtifactStore(
        "lab-a-bucket",
        credentials_path=str(credential_a),
        project_id="lab-a-project",
        app_name="siraloom-storage-a",
        inherit_global_credentials=False,
    )
    store_b = FirebaseArtifactStore(
        "lab-b-bucket",
        credentials_path=str(credential_b),
        project_id="lab-b-project",
        app_name="siraloom-storage-b",
        inherit_global_credentials=False,
    )

    bucket_a = store_a.bucket
    bucket_b = store_b.bucket

    assert bucket_a[0] == "lab-a-bucket"
    assert bucket_a[1].credential == ("certificate", str(credential_a))
    assert bucket_a[1].options == {
        "projectId": "lab-a-project",
        "storageBucket": "lab-a-bucket",
    }
    assert bucket_b[0] == "lab-b-bucket"
    assert bucket_b[1].credential == ("certificate", str(credential_b))
    assert bucket_b[1].options["projectId"] == "lab-b-project"
    assert bucket_a[1] is not bucket_b[1]
    assert len(initializations) == 2

    adc_store = FirebaseArtifactStore(
        "adc-bucket",
        project_id="adc-project",
        app_name="siraloom-storage-adc",
        inherit_global_credentials=False,
    )
    adc_bucket = adc_store.bucket
    assert adc_bucket[1].credential == "application-default"
    assert adc_store.credentials_path is None
    assert len(initializations) == 3
