from uuid import uuid4

import pytest

from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.artifacts.store import ArtifactStore


class _FailingFlushSession:
    def get(self, *_args):
        return None

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
        generation = 17

        def upload_from_filename(self, *_args, **_kwargs):
            self.uploaded = True
            self.upload_arguments = _kwargs

        def delete(self, **kwargs):
            self.deleted = True
            self.delete_arguments = kwargs

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
    assert bucket.blob_value.upload_arguments["if_generation_match"] == 0
    assert bucket.blob_value.delete_arguments["if_generation_match"] == 17


def test_local_store_never_overwrites_existing_artifact_bytes(tmp_path):
    class Session:
        def __init__(self):
            self.artifacts = {}

        def get(self, model, artifact_id):
            assert model.__name__ == "Artifact"
            return self.artifacts.get(artifact_id)

        def add(self, artifact):
            self.artifact = artifact

        def flush(self):
            self.artifacts[self.artifact.id] = self.artifact

    source = tmp_path / "source.vcf"
    source.write_bytes(b"original scientific artifact")
    changed_source = tmp_path / "changed.vcf"
    changed_source.write_bytes(b"different scientific artifact")
    case_id, artifact_id = uuid4(), uuid4()
    store = ArtifactStore(tmp_path / "artifacts")
    db = Session()

    original = store.put_file(
        **{
            **_put_arguments(source),
            "db": db,
            "case_id": case_id,
            "artifact_id": artifact_id,
        }
    )
    original_bytes = store.read_bytes(original.storage_uri)

    with pytest.raises(FileExistsError, match="durable database record"):
        store.put_file(
            **{
                **_put_arguments(changed_source),
                "db": db,
                "case_id": case_id,
                "artifact_id": artifact_id,
            }
        )

    assert store.read_bytes(original.storage_uri) == original_bytes


def test_local_store_reuses_only_byte_identical_orphan_object(tmp_path):
    class Session:
        def get(self, *_args):
            return None

        def add(self, artifact):
            self.artifact = artifact

        def flush(self):
            pass

    source = tmp_path / "source.vcf"
    source.write_bytes(b"orphan content")
    changed_source = tmp_path / "changed.vcf"
    changed_source.write_bytes(b"changed content")
    case_id, artifact_id = uuid4(), uuid4()
    store = ArtifactStore(tmp_path / "artifacts")
    destination = store._artifact_path(case_id, artifact_id, "input.vcf")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(source.read_bytes())

    artifact = store.put_file(
        **{
            **_put_arguments(source),
            "db": Session(),
            "case_id": case_id,
            "artifact_id": artifact_id,
        }
    )
    assert store.read_bytes(artifact.storage_uri) == source.read_bytes()

    with pytest.raises(FileExistsError, match="different bytes"):
        store.put_file(
            **{
                **_put_arguments(changed_source),
                "db": Session(),
                "case_id": case_id,
                "artifact_id": artifact_id,
            }
        )
    assert destination.read_bytes() == source.read_bytes()


def test_local_store_rejects_artifact_parent_symlink_outside_root(tmp_path):
    source = tmp_path / "source.vcf"
    source.write_bytes(b"artifact bytes")
    storage_root = tmp_path / "artifacts"
    store = ArtifactStore(storage_root)
    case_id, artifact_id = uuid4(), uuid4()
    external_directory = tmp_path / "external"
    external_directory.mkdir()
    (storage_root / str(case_id)).symlink_to(external_directory, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the configured storage root"):
        store.put_file(
            **{
                **_put_arguments(source),
                "case_id": case_id,
                "artifact_id": artifact_id,
                "db": _FailingFlushSession(),
            }
        )

    assert list(external_directory.iterdir()) == []


@pytest.mark.parametrize(
    "orphan_state",
    ["matching", "metadata_mismatch", "content_mismatch"],
)
def test_cloud_store_reuses_only_matching_preexisting_orphan(tmp_path, orphan_state):
    import hashlib

    source = tmp_path / "source.vcf"
    source.write_bytes(b"cloud orphan content")
    changed_source = tmp_path / "changed.vcf"
    changed_source.write_bytes(b"cloud otherx content")
    selected_source = changed_source if orphan_state == "content_mismatch" else source
    case_id, artifact_id = uuid4(), uuid4()
    expected_digest = hashlib.sha256(selected_source.read_bytes()).hexdigest()

    class PreconditionFailed(Exception):
        code = 412

    class Blob:
        generation = 23
        size = len(source.read_bytes())

        def __init__(self):
            self.metadata = None
            self.upload_arguments = None
            self.reload_count = 0

        def upload_from_filename(self, *_args, **kwargs):
            self.upload_arguments = kwargs
            raise PreconditionFailed("object already exists")

        def reload(self):
            self.reload_count += 1
            self.metadata = {
                "sha256": "f" * 64 if orphan_state == "metadata_mismatch" else expected_digest,
                "artifact_id": str(artifact_id),
                "case_id": str(case_id),
                "filename": "input.vcf",
            }

        def open(self, mode, **kwargs):
            import io

            assert mode == "rb"
            assert kwargs["if_generation_match"] == 23
            return io.BytesIO(source.read_bytes())

    class Bucket:
        def __init__(self):
            self.blob_value = Blob()

        def blob(self, _name):
            return self.blob_value

    class Session:
        def get(self, *_args):
            return None

        def add(self, artifact):
            self.artifact = artifact

        def flush(self):
            pass

    store = FirebaseArtifactStore("test-bucket")
    bucket = Bucket()
    store._bucket = bucket
    arguments = {
        **_put_arguments(selected_source),
        "db": Session(),
        "case_id": case_id,
        "artifact_id": artifact_id,
    }

    if orphan_state == "matching":
        artifact = store.put_file(**arguments)
        assert artifact.sha256 == expected_digest
        assert bucket.blob_value.reload_count == 1
    else:
        message = (
            "different or unverifiable data"
            if orphan_state == "metadata_mismatch"
            else "fail integrity verification"
        )
        with pytest.raises(FileExistsError, match=message):
            store.put_file(**arguments)
        assert bucket.blob_value.reload_count == 1
    assert bucket.blob_value.upload_arguments["if_generation_match"] == 0
