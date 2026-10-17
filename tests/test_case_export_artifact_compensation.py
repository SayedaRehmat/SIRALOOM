from types import SimpleNamespace
from uuid import uuid4

from backend.app.infrastructure.artifacts import compensation
from backend.app.infrastructure.db.models import Artifact, Case, CaseExport
from backend.app.reporting import export_task


class _VerificationSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, model, _artifact_id):
        assert model is Artifact
        return None


def test_export_worker_removes_uncommitted_package_after_flush_failure(monkeypatch):
    export_id, case_id = uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=uuid4(), case_identifier="CASE-1")
    export = SimpleNamespace(
        id=export_id, case_id=case_id, status="QUEUED", artifact_id=None,
        completed_at=None, error_code=None, error_message=None,
    )
    events = []
    durable_state = {"status": "QUEUED", "artifact_id": None}

    class Database:
        def get(self, model, requested_id, **_kwargs):
            assert requested_id in {export_id, case_id}
            return export if model is CaseExport else case if model is Case else None

        def add(self, _row):
            pass

        def commit(self):
            durable_state["status"] = export.status
            durable_state["artifact_id"] = export.artifact_id
            events.append(("commit", export.status))

        def rollback(self):
            export.status = durable_state["status"]
            export.artifact_id = durable_state["artifact_id"]
            events.append(("rollback", None))

        def flush(self):
            raise RuntimeError("injected export transaction failure")

        def close(self):
            pass

    class Store:
        def __init__(self):
            self.deleted = []

        def uri_for_artifact(self, *, case_id, artifact_id, filename):
            return f"file:///exports/{case_id}/{artifact_id}/{filename}"

        def delete(self, uri):
            self.deleted.append(uri)

    store = Store()
    monkeypatch.setattr(export_task, "SessionLocal", Database)
    monkeypatch.setattr(export_task, "AuditService", lambda _db: SimpleNamespace(record=lambda **_kwargs: None))
    monkeypatch.setattr(export_task, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(compensation, "SessionLocal", lambda: _VerificationSession())

    def build_export(_db, *, export, store):
        events.append(("uploaded", export.id))
        return SimpleNamespace(id=export.id, sha256="a" * 64)

    monkeypatch.setattr(export_task, "build_case_export", build_export)
    export_task.run_case_export(export_id)

    assert export.status == "FAILED"
    assert store.deleted == [
        f"file:///exports/{case_id}/{export_id}/case_export_CASE-1.zip"
    ]
    assert events[0] == ("commit", "RUNNING")
