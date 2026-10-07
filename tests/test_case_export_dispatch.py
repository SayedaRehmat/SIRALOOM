from __future__ import annotations

from uuid import uuid4

import importlib


def test_case_export_execution_claim_uses_postgresql_session_advisory_lock():
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

    class FakeDB:
        def __init__(self, acquired):
            self.acquired = acquired
            self.scalar_calls = 0

        def get_bind(self):
            return Bind()

        def scalar(self, statement, params):
            self.scalar_calls += 1
            assert "pg_try_advisory_lock" in str(statement)
            assert "lock_key" in params
            return self.acquired

        def get(self, model, export_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert export_id == export.id
            return export

        def add(self, row):
            assert row is export

        def commit(self):
            pass

    duplicate_db = FakeDB(acquired=False)
    assert module._claim_case_export_execution(
        duplicate_db,
        export.id,
        task_id="live-export-task",
        allow_running=True,
    ) is False
    assert duplicate_db.scalar_calls == 1

    recovery_db = FakeDB(acquired=True)
    assert module._claim_case_export_execution(
        recovery_db,
        export.id,
        task_id="live-export-task",
        allow_running=True,
    ) is True
    assert recovery_db.scalar_calls == 1
