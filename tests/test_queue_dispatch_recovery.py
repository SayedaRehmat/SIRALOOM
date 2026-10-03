import importlib
from uuid import uuid4


def test_orphaned_dispatch_recovery_requeues_only_definitive_failures(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    analysis = type("Analysis", (), {"id": uuid4(), "case_id": uuid4(), "status": "QUEUED", "queue_task_id": "old-task"})()

    class FakeDB:
        def scalars(self, stmt):
            assert getattr(stmt, "_for_update_arg", None) is None
            return type("ScalarRows", (), {"first": lambda self: analysis.id})()

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


def test_publish_analysis_dispatch_persists_task_id_after_publication(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": None})()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": dispatch_id,
            "analysis_id": analysis_id,
            "status": "PENDING",
            "task_id": None,
            "attempts": 0,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def __init__(self):
            self.commits = 0
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            if row_id == dispatch_id:
                return dispatch
            assert row_id == analysis_id
            return analysis
        def add(self, _row):
            pass
        def commit(self):
            self.commits += 1
        def close(self):
            pass

    class FakeTask:
        id = "dispatch-task-1"

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", lambda **kwargs: FakeTask())

    assert module.publish_analysis_dispatch(dispatch_id) == "dispatch-task-1"
    assert dispatch.status == "PUBLISHED"
    assert dispatch.task_id == "dispatch-task-1"
    assert analysis.queue_task_id == "dispatch-task-1"
    assert dispatch.attempts == 1
    assert db_session.SessionLocal is FakeDB


def test_publish_analysis_dispatch_keeps_intent_pending_when_broker_publish_fails(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": None})()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": dispatch_id,
            "analysis_id": analysis_id,
            "status": "PENDING",
            "task_id": None,
            "attempts": 0,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == dispatch_id else analysis
        def add(self, _row):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    def fail_publish(**_kwargs):
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", fail_publish)

    assert module.publish_analysis_dispatch(dispatch_id) is None
    assert dispatch.status == "PENDING"
    assert dispatch.attempts == 1
    assert dispatch.last_error == "broker unavailable"
    assert analysis.queue_task_id is None


def test_published_dispatch_is_retried_only_after_definitive_celery_failure(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": "old-task"})()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": dispatch_id,
            "analysis_id": analysis_id,
            "status": "PUBLISHED",
            "task_id": "old-task",
            "attempts": 1,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == dispatch_id else analysis
        def add(self, _row):
            pass
        def commit(self):
            pass
        def close(self):
            pass

    class FakeTask:
        id = "replacement-task"

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "FAILURE"})())
    monkeypatch.setattr(module.run_analysis_task, "apply_async", lambda **kwargs: FakeTask())

    assert module.publish_analysis_dispatch(dispatch_id) == "replacement-task"
    assert dispatch.status == "PUBLISHED"
    assert dispatch.task_id == "replacement-task"
    assert analysis.queue_task_id == "replacement-task"
    assert dispatch.attempts == 2


def test_published_dispatch_is_not_replaced_while_celery_state_is_unknown(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": "pending-task"})()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": dispatch_id,
            "analysis_id": analysis_id,
            "status": "PUBLISHED",
            "task_id": "pending-task",
            "attempts": 1,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == dispatch_id else analysis
        def commit(self):
            raise AssertionError("unknown broker state must not mutate dispatch")
        def close(self):
            pass

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "PENDING"})())

    assert module.publish_analysis_dispatch(dispatch_id) == "pending-task"
