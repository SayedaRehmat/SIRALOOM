import importlib
from uuid import uuid4


def test_orphaned_dispatch_recovery_requeues_only_definitive_failures(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    analysis = type("Analysis", (), {"id": uuid4(), "case_id": uuid4(), "status": "QUEUED", "queue_task_id": "old-task"})()

    class FakeDB:
        def scalars(self, _stmt): return iter([analysis])
        def scalar(self, _stmt): return None
        def add(self, _row): pass
        def flush(self): pass
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "FAILURE"})())
    monkeypatch.setattr(module.run_analysis_task, "delay", lambda _id: type("Task", (), {"id": "replacement-task"})())

    assert module.recover_orphaned_analysis_dispatches() == {"inspected": 1, "recovered": 1}
    assert analysis.queue_task_id == "replacement-task"


def test_orphaned_dispatch_recovery_does_not_duplicate_unknown_pending(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    analysis = type("Analysis", (), {"id": uuid4(), "case_id": uuid4(), "status": "QUEUED", "queue_task_id": "unknown-task"})()

    class FakeDB:
        def scalars(self, _stmt): return iter([analysis])
        def add(self, _row): raise AssertionError("PENDING task must not be replaced")
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "PENDING"})())
    monkeypatch.setattr(module.run_analysis_task, "delay", lambda _id: (_ for _ in ()).throw(AssertionError("must not dispatch")))

    assert module.recover_orphaned_analysis_dispatches() == {"inspected": 1, "recovered": 0}
