from uuid import uuid4

import pytest

from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.artifacts.store import ArtifactStore


class _FailingFlushSession:
    def add(self, _row):
        pass

    def flush(self):
        raise RuntimeError("injected database flush failure")


def _put_arguments(source_path):
    return {
        "db": _FailingFlushSession(),
        "case_id": uuid4(),
        "analysis_id": None,
        "source_path": source_path,
        "filename": "input.vcf",
        "artifact_type": "VCF",
        "media_type": "text/vcf",
        "genome_build": "GRCh38",
    }


def test_local_store_removes_new_object_when_artifact_row_flush_fails(tmp_path):
    source = tmp_path / "source.vcf"
    source.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
    storage_root = tmp_path / "artifacts"
    store = ArtifactStore(storage_root)

    with pytest.raises(RuntimeError, match="injected database flush failure"):
        store.put_file(**_put_arguments(source))

    assert list(storage_root.rglob("*")) == []


def test_cloud_store_deletes_new_object_when_artifact_row_flush_fails(tmp_path):
    source = tmp_path / "source.vcf"
    source.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")

    class Blob:
        metadata = None
        content_type = None
        uploaded = False
        deleted = False

        def upload_from_filename(self, *_args, **_kwargs):
            self.uploaded = True

        def delete(self):
            self.deleted = True

    class Bucket:
        def __init__(self):
            self.blob_value = Blob()

        def blob(self, _name):
            return self.blob_value

    store = FirebaseArtifactStore("test-bucket")
    bucket = Bucket()
    store._bucket = bucket

    with pytest.raises(RuntimeError, match="injected database flush failure"):
        store.put_file(**_put_arguments(source))

    assert bucket.blob_value.uploaded is True
    assert bucket.blob_value.deleted is True
