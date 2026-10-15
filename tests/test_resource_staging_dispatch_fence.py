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
