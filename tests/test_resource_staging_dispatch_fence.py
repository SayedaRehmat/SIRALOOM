from types import SimpleNamespace

import pytest

from backend.app.infrastructure.queue import celery_app as queue


@pytest.mark.parametrize(
    ("task_id", "dispatch", "expected"),
    [
        (None, {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("", {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("dispatch-old", {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("dispatch-current", {"status": "FAILED", "task_id": "dispatch-current"}, False),
        ("dispatch-current", {"status": "PUBLISHED", "task_id": "dispatch-current"}, True),
        ("dispatch-current", {"status": "RUNNING", "task_id": "dispatch-current"}, True),
        ("dispatch-current", {"status": "QUEUING", "task_id": "dispatch-current"}, True),
    ],
)
def test_resource_staging_worker_requires_current_persisted_dispatch(task_id, dispatch, expected):
    row = SimpleNamespace(metadata_json={"staging_dispatch": dispatch})
    assert queue._resource_staging_dispatch_matches(row, task_id) is expected


def test_duplicate_resource_staging_delivery_is_fenced_by_postgres_lock(monkeypatch):
    import importlib
    from uuid import uuid4

    session_module = importlib.import_module("backend.app.infrastructure.db.session")

    class Result:
        def scalar_one(self):
            return False

    class LockConnection:
        def __init__(self):
            self.info = {}
            self.closed = False
            self.commits = 0

        def execute(self, statement, params):
            assert "pg_try_advisory_lock" in str(statement)
            assert "lock_key" in params
            return Result()

        def commit(self):
            self.commits += 1

        def close(self):
            self.closed = True

    class Engine:
        dialect = SimpleNamespace(name="postgresql")

        def __init__(self, connection):
            self.connection = connection

        def connect(self):
            return self.connection

    class DB:
        def __init__(self):
            self.closed = False

        def get(self, *args, **kwargs):
            raise AssertionError(
                "a duplicate worker must be fenced before loading staging state"
            )

        def close(self):
            self.closed = True

    connection = LockConnection()
    db = DB()
    monkeypatch.setattr(session_module, "engine", Engine(connection))
    monkeypatch.setattr(session_module, "SessionLocal", lambda: db)

    task = queue.run_resource_staging_task
    task.push_request(id="dispatch-current", retries=0, delivery_info={"redelivered": True})
    try:
        result = task.run(str(uuid4()))
    finally:
        task.pop_request()

    assert result["status"] == "ALREADY_CLAIMED"
    assert connection.commits == 1
    assert connection.closed is True
    assert db.closed is True


def test_resource_staging_worker_rejects_tampered_destination_before_writing(monkeypatch, tmp_path):
    import importlib
    from datetime import datetime, timezone
    from uuid import uuid4

    from backend.app.infrastructure.db.models import Resource, ResourceStaging

    session_module = importlib.import_module("backend.app.infrastructure.db.session")
    organization_id = uuid4()
    staging_id = uuid4()
    registered = tmp_path / "resources" / str(organization_id) / "registered.fa"
    tampered = tmp_path / "resources" / str(uuid4()) / "foreign.fa"
    resource = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        version="v1",
        location=str(registered),
        access_method="LOCAL",
    )
    row = SimpleNamespace(
        id=staging_id,
        resource_id=resource.id,
        resource_version="v1",
        destination_uri=str(tampered),
        storage_backend="ORGANIZATION_LOCAL_FILESYSTEM",
        status="READY_TO_STAGE",
        metadata_json={"staging_dispatch": {"status": "PUBLISHED", "task_id": "dispatch-current"}},
        error_code=None,
        error_message=None,
    )

    class Engine:
        dialect = SimpleNamespace(name="sqlite")

    class DB:
        def __init__(self):
            self.closed = False

        def get(self, model, object_id, **_kwargs):
            if model is ResourceStaging and object_id == staging_id:
                return row
            if model is Resource and object_id == resource.id:
                return resource
            raise AssertionError(f"Unexpected lookup: {model!r} {object_id!r}")

        def add(self, _row):
            pass

        def flush(self):
            pass

        def commit(self):
            pass

        def refresh(self, _row):
            pass

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    db = DB()
    monkeypatch.setattr(session_module, "engine", Engine())
    monkeypatch.setattr(session_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        "backend.app.domain.resource_staging.cleanup_staging_temporary_files",
        lambda *_args: pytest.fail("invalid destination must be rejected before cleanup"),
    )
    monkeypatch.setattr(
        "backend.app.domain.resource_staging.stage_resource_release",
        lambda *_args, **_kwargs: pytest.fail("invalid destination must never be staged"),
    )

    from backend.app.domain.resource_staging import transition_staging as real_transition

    def transition(_db, staging, status, *, error_code=None, error_message=None):
        real_transition(_db, staging, status, error_code=error_code, error_message=error_message)
        return staging

    monkeypatch.setattr("backend.app.domain.resource_staging.transition_staging", transition)

    task = queue.run_resource_staging_task
    task.push_request(id="dispatch-current", retries=0, delivery_info={"redelivered": False})
    try:
        result = task.run(str(staging_id))
    finally:
        task.pop_request()

    assert result["status"] == "PREFLIGHT_FAILED"
    assert result["error_code"] == "RESOURCE_DESTINATION_MISMATCH"
    assert row.updated_at is not None
    assert row.updated_at <= datetime.now(timezone.utc)
    assert db.closed is True
