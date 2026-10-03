import importlib
from uuid import uuid4


def test_orphaned_dispatch_recovery_requeues_only_definitive_failures(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    analysis = type("Analysis", (), {"id": uuid4(), "case_id": uuid4(), "status": "QUEUED", "queue_task_id": "old-task"})()

    class FakeDB:
        def scalars(self, stmt):
            assert getattr(stmt, "_for_update_arg", None) is None
            return iter([analysis.id])

        def get(self, model, analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert analysis_id == analysis.id
            return analysis

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
        def scalars(self, stmt):
            assert getattr(stmt, "_for_update_arg", None) is None
            return iter([analysis.id])

        def get(self, model, analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert analysis_id == analysis.id
            return analysis

        def add(self, _row): raise AssertionError("PENDING task must not be replaced")
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "PENDING"})())
    monkeypatch.setattr(module.run_analysis_task, "delay", lambda _id: (_ for _ in ()).throw(AssertionError("must not dispatch")))

    assert module.recover_orphaned_analysis_dispatches() == {"inspected": 1, "recovered": 0}


def test_analysis_execution_claim_fences_duplicate_worker():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    from backend.app.domain.enums import AnalysisStatus
    analysis = type("Analysis", (), {"id": uuid4(), "status": AnalysisStatus.QUEUED})()
    class FakeDB:
        def __init__(self): self.commits = 0
        def get(self, model, analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert analysis_id == analysis.id
            return analysis
        def add(self, row): assert row is analysis
        def commit(self): self.commits += 1
    db = FakeDB()
    assert module._claim_analysis_execution(db, analysis.id) is True
    assert analysis.status == AnalysisStatus.RUNNING
    assert db.commits == 1
    assert module._claim_analysis_execution(db, analysis.id) is False
    assert db.commits == 1


def test_analysis_execution_claim_allows_continuation_of_running_work():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    from backend.app.domain.enums import AnalysisStatus
    analysis = type("Analysis", (), {"id": uuid4(), "status": AnalysisStatus.RUNNING})()
    class FakeDB:
        def get(self, model, analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return analysis
    db = FakeDB()
    assert module._claim_analysis_execution(db, analysis.id, allow_running=True) is True
    assert module._claim_analysis_execution(db, analysis.id, allow_running=False) is False
