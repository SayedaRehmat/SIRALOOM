from __future__ import annotations

from uuid import uuid4

import importlib


def test_case_export_execution_claim_uses_dedicated_postgresql_connection():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")

    export = type(
        "CaseExport",
        (),
        {
            "id": uuid4(),
            "status": "RUNNING",
            "queue_task_id": "live-export-task",
        },
    )()

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class LockResult:
        def __init__(self, acquired):
            self.acquired = acquired

        def scalar_one(self):
            return self.acquired

    class LockConnection:
        def __init__(self, acquired):
            self.acquired = acquired
            self.info = {}
            self.statements = []
            self.commits = 0

        def execute(self, statement, params):
            self.statements.append((str(statement), params))
            assert "pg_try_advisory_lock" in str(statement)
            assert "lock_key" in params
            return LockResult(self.acquired)

        def commit(self):
            self.commits += 1

    class FakeDB:
        def __init__(self):
            self.scalar_calls = 0
            self.commits = 0

        def get_bind(self):
            return Bind()

        def scalar(self, statement, params):
            self.scalar_calls += 1
            raise AssertionError(
                "PostgreSQL execution lock must use the dedicated connection"
            )

        def get(self, model, export_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert export_id == export.id
            return export

        def add(self, row):
            assert row is export

        def commit(self):
            self.commits += 1

    # A live export owns the lock: duplicate delivery is rejected before it
    # can inspect or mutate the export row.
    duplicate_db = FakeDB()
    duplicate_connection = LockConnection(acquired=False)
    assert module._claim_case_export_execution(
        duplicate_db,
        export.id,
        task_id="live-export-task",
        allow_running=True,
        lock_connection=duplicate_connection,
    ) is False
    assert len(duplicate_connection.statements) == 1
    assert duplicate_db.scalar_calls == 0
    assert duplicate_connection.commits == 1

    # After worker loss, PostgreSQL releases the lock with the original
    # connection. A redelivery can claim the still-RUNNING export. Crucially,
    # committing the ORM session does not change the dedicated lock connection.
    recovery_db = FakeDB()
    recovery_connection = LockConnection(acquired=True)
    assert module._claim_case_export_execution(
        recovery_db,
        export.id,
        task_id="live-export-task",
        allow_running=True,
        lock_connection=recovery_connection,
    ) is True
    assert recovery_connection.info[
        "siraloom_case_export_execution_lock_key"
    ]
    assert recovery_connection.commits == 1
    assert recovery_db.commits == 1
    assert recovery_db.scalar_calls == 0


def test_case_export_enqueue_persists_dispatch_before_publication(monkeypatch):
    module = importlib.import_module("backend.app.application.case_export")
    export = type(
        "CaseExport",
        (),
        {"id": uuid4(), "status": "QUEUED", "queue_task_id": None},
    )()
    events = []

    class FakeDB:
        def get(self, model, export_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert export_id == export.id
            return export

        def refresh(self, row, **kwargs):
            assert row is export
            assert kwargs == {"with_for_update": True}

        def scalar(self, statement):
            return 0

        def add(self, row):
            events.append(("add", type(row).__name__, getattr(row, "id", None)))

        def commit(self):
            events.append(("commit", export.queue_task_id))

    def publish(dispatch_id):
        events.append(("publish", dispatch_id))
        assert export.queue_task_id == str(dispatch_id)

    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_case_export_dispatch",
        publish,
    )

    dispatch_id = module.enqueue_case_export(FakeDB(), export)

    assert dispatch_id == export.queue_task_id
    assert events[-1][0] == "publish"
    assert str(events[-1][1]) == dispatch_id
    commit_index = next(i for i, event in enumerate(events) if event[0] == "commit")
    publish_index = next(i for i, event in enumerate(events) if event[0] == "publish")
    assert commit_index < publish_index
    assert events[commit_index][1] == dispatch_id


def test_case_export_execution_rejects_missing_dispatch_capability_before_db_access():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    export_id = uuid4()

    class UntouchableDB:
        def get_bind(self):
            raise AssertionError("missing dispatch must be rejected before DB access")

        def get(self, *args, **kwargs):
            raise AssertionError("missing dispatch must not load or mutate export")

        def scalar(self, *args, **kwargs):
            raise AssertionError("missing dispatch must not acquire a lock")

    for task_id in (None, ""):
        assert module._claim_case_export_execution(
            UntouchableDB(),
            export_id,
            task_id=task_id,
            allow_running=True,
        ) is False


def test_case_export_execution_rejects_stale_dispatch_generation():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    export_id = uuid4()
    export = type(
        "CaseExport",
        (),
        {"id": export_id, "status": "RUNNING", "queue_task_id": "current-generation"},
    )()

    class Dialect:
        name = "sqlite"

    class Bind:
        dialect = Dialect()

    class FakeDB:
        def get_bind(self):
            return Bind()

        def get(self, model, requested_id, **kwargs):
            assert requested_id == export_id
            assert kwargs == {"with_for_update": True}
            return export

        def add(self, row):
            raise AssertionError("stale generation must not mutate the export")

        def commit(self):
            raise AssertionError("stale generation must not commit")

    assert module._claim_case_export_execution(
        FakeDB(),
        export_id,
        task_id="stale-dispatch-generation",
        allow_running=True,
    ) is False
