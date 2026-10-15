from uuid import uuid4

from backend.app.api.v1 import artifacts as artifacts_api


class _Database:
    def __init__(self):
        self.rollbacks = 0

    def rollback(self):
        self.rollbacks += 1


class _Store:
    def __init__(self):
        self.deleted = []

    def delete(self, storage_uri):
        self.deleted.append(storage_uri)


class _VerificationSession:
    def __init__(self, artifact):
        self.artifact = artifact

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _model, _artifact_id):
        if isinstance(self.artifact, Exception):
            raise self.artifact
        return self.artifact


def test_failed_artifact_transaction_deletes_object_only_when_row_is_absent(monkeypatch):
    artifact_id = uuid4()
    db = _Database()
    store = _Store()
    monkeypatch.setattr(artifacts_api, "SessionLocal", lambda: _VerificationSession(None))

    artifacts_api._compensate_uncommitted_artifact(
        db, store, artifact_id, "file:///artifact/uncommitted.vcf",
    )

    assert db.rollbacks == 1
    assert store.deleted == ["file:///artifact/uncommitted.vcf"]


def test_commit_outcome_uncertainty_preserves_object(monkeypatch):
    artifact_id = uuid4()
    db = _Database()
    store = _Store()
    monkeypatch.setattr(artifacts_api, "SessionLocal", lambda: _VerificationSession(object()))

    artifacts_api._compensate_uncommitted_artifact(
        db, store, artifact_id, "file:///artifact/possibly-committed.vcf",
    )

    assert db.rollbacks == 1
    assert store.deleted == []


def test_failed_verification_preserves_object_and_does_not_mask_original_error(monkeypatch):
    db = _Database()
    store = _Store()
    monkeypatch.setattr(
        artifacts_api,
        "SessionLocal",
        lambda: _VerificationSession(RuntimeError("database unavailable")),
    )

    artifacts_api._compensate_uncommitted_artifact(
        db, store, uuid4(), "gs://lab-bucket/artifact/uncertain.vcf",
    )

    assert db.rollbacks == 1
    assert store.deleted == []
