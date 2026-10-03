import importlib
from uuid import uuid4


def test_orphaned_dispatch_recovery_requeues_only_definitive_failures(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    analysis = type("Analysis", (), {"id": uuid4(), "case_id": uuid4(), "status": "QUEUED", "queue_task_id": "old-task"})()

    class FakeDB:
        def scalars(self, stmt):
            assert getattr(stmt, "_for_update_arg", None) is None
            self.scalar_calls = getattr(self, "scalar_calls", 0) + 1
            call_no = self.scalar_calls
            class ScalarRows:
                def __iter__(self):
                    return iter([analysis.id]) if call_no == 1 else iter([])
                def first(self):
                    return analysis.id if call_no == 1 else None
            return ScalarRows()

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
            self.scalar_calls = getattr(self, "scalar_calls", 0) + 1
            call_no = self.scalar_calls
            class ScalarRows:
                def __iter__(self):
                    return iter([analysis.id]) if call_no == 1 else iter([])
                def first(self):
                    return analysis.id if call_no == 1 else None
            return ScalarRows()

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


def test_analysis_execution_claim_rejects_stale_dispatch_generation():
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    from backend.app.domain.enums import AnalysisStatus

    analysis = type(
        "Analysis",
        (),
        {
            "id": uuid4(),
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": "new-dispatch",
        },
    )()

    class FakeDB:
        def get(self, model, analysis_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return analysis

        def add(self, row):
            assert row is analysis

        def commit(self):
            pass

    db = FakeDB()

    # A delayed broker message from the previous retry generation must not
    # claim the newly queued execution.
    assert module._claim_analysis_execution(
        db,
        analysis.id,
        task_id="old-dispatch",
    ) is False
    assert analysis.status == AnalysisStatus.QUEUED

    # Only the current durable dispatch generation may claim the analysis.
    assert module._claim_analysis_execution(
        db,
        analysis.id,
        task_id="new-dispatch",
    ) is True
    assert analysis.status == AnalysisStatus.RUNNING

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
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": str(dispatch_id)})()
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
    analysis = type("Analysis", (), {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": str(dispatch_id)})()
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
    assert analysis.queue_task_id == str(dispatch_id)


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


def test_published_dispatch_definitive_failure_does_not_recurse_on_immediate_republish_failure(monkeypatch):
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
        def __init__(self):
            self.commits = 0
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == dispatch_id else analysis
        def add(self, _row):
            pass
        def commit(self):
            self.commits += 1
        def close(self):
            pass

    calls = {"publish": 0}

    def fail_publish(**_kwargs):
        calls["publish"] += 1
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.celery_app, "AsyncResult", lambda _id: type("Result", (), {"state": "FAILURE"})())
    monkeypatch.setattr(module.run_analysis_task, "apply_async", fail_publish)

    assert module.publish_analysis_dispatch(dispatch_id) is None
    assert calls["publish"] == 1
    assert dispatch.status == "PENDING"
    assert dispatch.task_id is None
    assert dispatch.attempts == 2
    assert dispatch.last_error == "broker unavailable"
    assert analysis.queue_task_id == str(dispatch_id)


def test_published_dispatch_is_idempotent_when_relay_runs_again(monkeypatch):
    """A second relay observation must reuse the live publication."""
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": str(dispatch_id),
        },
    )()
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
        id = "live-dispatch-task"

    publish_calls = {"count": 0}

    def publish(**_kwargs):
        publish_calls["count"] += 1
        return FakeTask()

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", publish)
    monkeypatch.setattr(
        module.celery_app,
        "AsyncResult",
        lambda _id: type("Result", (), {"state": "PENDING"})(),
    )

    assert module.publish_analysis_dispatch(dispatch_id) == "live-dispatch-task"
    assert dispatch.status == "PUBLISHED"
    assert analysis.queue_task_id == "live-dispatch-task"

    assert module.publish_analysis_dispatch(dispatch_id) == "live-dispatch-task"
    assert publish_calls["count"] == 1


def test_published_task_survives_dispatch_commit_failure_and_relay_reuses_execution_fence(monkeypatch):
    """A broker publication before DB commit failure must not create a second execution."""
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": None,
        },
    )()
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
        commit_calls = 0

        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == dispatch_id else analysis

        def add(self, _row):
            pass

        def commit(self):
            type(self).commit_calls += 1
            if type(self).commit_calls == 1:
                raise RuntimeError("database commit failed after broker publication")

        def close(self):
            pass

    class FakeTask:
        id = str(dispatch_id)

    publish_calls = {"count": 0}

    def publish(**kwargs):
        publish_calls["count"] += 1
        assert kwargs["task_id"] == str(dispatch_id)
        return FakeTask()

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", publish)

    try:
        module.publish_analysis_dispatch(dispatch_id)
    except RuntimeError as exc:
        assert str(exc) == "database commit failed after broker publication"
    else:
        raise AssertionError("commit failure must propagate")

    assert publish_calls["count"] == 1
    assert dispatch.status == "PUBLISHED"
    assert dispatch.task_id == str(dispatch_id)
    assert analysis.queue_task_id == str(dispatch_id)

    # A later relay may observe the durable intent again. If the broker reports
    # the original task as live/unknown, it must not publish a second task.
    monkeypatch.setattr(
        module.celery_app,
        "AsyncResult",
        lambda _id: type("Result", (), {"state": "PENDING"})(),
    )
    assert module.publish_analysis_dispatch(dispatch_id) == str(dispatch_id)
    assert publish_calls["count"] == 1

    # The consumer-side execution fence is the authoritative protection if a
    # duplicate broker delivery nevertheless exists.
    worker_analysis = type(
        "WorkerAnalysis",
        (),
        {"id": analysis_id, "status": AnalysisStatus.QUEUED},
    )()
    worker_db = type(
        "WorkerDB",
        (),
        {
            "get": lambda self, model, row_id, **kwargs: worker_analysis,
            "add": lambda self, row: None,
            "commit": lambda self: None,
        },
    )()
    assert module._claim_analysis_execution(worker_db, analysis_id) is True
    assert module._claim_analysis_execution(worker_db, analysis_id) is False


def test_concurrent_relay_workers_serialize_on_dispatch_row_lock(monkeypatch):
    """Two relay workers must publish one dispatch only when row locking serializes them."""
    import threading

    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    dispatch_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {"id": analysis_id, "status": AnalysisStatus.QUEUED, "queue_task_id": str(dispatch_id)},
    )()
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

    row_lock = threading.RLock()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            row_lock.acquire()
            if row_id == dispatch_id:
                return dispatch
            return analysis

        def add(self, _row):
            pass

        def commit(self):
            row_lock.release()

        def close(self):
            # The production transaction releases the row lock on commit.
            # Keep this idempotent for paths that return without committing.
            try:
                row_lock.release()
            except RuntimeError:
                pass

    publish_calls = {"count": 0}
    publish_started = threading.Event()
    allow_publish = threading.Event()

    class FakeTask:
        id = str(dispatch_id)

    def publish(**_kwargs):
        publish_calls["count"] += 1
        publish_started.set()
        allow_publish.wait(timeout=2)
        return FakeTask()

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", publish)
    monkeypatch.setattr(
        module.celery_app,
        "AsyncResult",
        lambda _id: type("Result", (), {"state": "PENDING"})(),
    )

    results = []
    errors = []

    def relay():
        try:
            results.append(module.publish_analysis_dispatch(dispatch_id))
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=relay)
    second = threading.Thread(target=relay)
    first.start()
    assert publish_started.wait(timeout=2)
    second.start()

    allow_publish.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not errors
    assert not first.is_alive()
    assert not second.is_alive()
    assert results.count(str(dispatch_id)) == 2
    assert publish_calls["count"] == 1
    assert dispatch.status == "PUBLISHED"
    assert analysis.queue_task_id == str(dispatch_id)


def test_enqueue_analysis_locks_row_and_reuses_existing_queue(monkeypatch):
    """Concurrent start callers must serialize on the analysis row."""
    module = importlib.import_module("backend.app.application.analysis")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.CREATED,
            "queue_task_id": None,
        },
    )()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": uuid4(),
            "analysis_id": analysis_id,
            "dispatch_generation": 1,
            "status": "PUBLISHED",
            "task_id": "dispatch-task-1",
        },
    )()

    class FakeScalar:
        def __init__(self, value):
            self.value = value
        def __bool__(self):
            return bool(self.value)

    class FakeDB:
        def __init__(self):
            self.get_calls = 0
            self.commits = 0
            self.added = []

        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            assert row_id == analysis_id
            self.get_calls += 1
            return analysis

        def scalar(self, statement):
            return 0

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.commits += 1

        def refresh(self, row):
            if row is analysis:
                assert analysis.status == AnalysisStatus.QUEUED

    db = FakeDB()
    publish_calls = {"count": 0}

    def publish(_dispatch_id):
        publish_calls["count"] += 1
        analysis.queue_task_id = "dispatch-task-1"
        return "dispatch-task-1"

    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
        publish,
    )

    assert module.enqueue_analysis(db, analysis) == "dispatch-task-1"
    assert analysis.status == AnalysisStatus.QUEUED
    assert analysis.queue_task_id == "dispatch-task-1"
    assert publish_calls["count"] == 1
    assert db.get_calls == 1
    assert db.commits == 1

    # A second caller, even with the same object identity, sees the durable
    # QUEUED state under the row lock and reuses the existing queue pointer.
    assert module.enqueue_analysis(db, analysis) == "dispatch-task-1"
    assert publish_calls["count"] == 1
    assert db.get_calls == 2
    assert db.commits == 1


def test_enqueue_analysis_does_not_create_second_dispatch_for_queued_analysis():
    module = importlib.import_module("backend.app.application.analysis")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": "existing-task",
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return analysis

        def scalar(self, _statement):
            raise AssertionError("queued analysis must not allocate a dispatch generation")

        def add(self, _row):
            raise AssertionError("queued analysis must not create another dispatch")

        def commit(self):
            raise AssertionError("queued analysis must not commit")

        def refresh(self, _row):
            raise AssertionError("queued analysis must not refresh")

    assert module.enqueue_analysis(FakeDB(), analysis) == "existing-task"


def test_stale_pending_dispatch_is_superseded_without_reclaiming_analysis(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    old_dispatch_id = uuid4()
    new_dispatch_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": str(new_dispatch_id),
        },
    )()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": old_dispatch_id,
            "analysis_id": analysis_id,
            "status": "PENDING",
            "task_id": None,
            "attempts": 1,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == old_dispatch_id else analysis

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    publish_calls = {"count": 0}

    def publish(**_kwargs):
        publish_calls["count"] += 1
        raise AssertionError("stale dispatch must never be published")

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", publish)

    assert module.publish_analysis_dispatch(old_dispatch_id) == str(new_dispatch_id)
    assert dispatch.status == "SUPERSEDED"
    assert publish_calls["count"] == 0
    assert analysis.queue_task_id == str(new_dispatch_id)


def test_stale_published_dispatch_cannot_reclaim_analysis_after_retry(monkeypatch):
    module = importlib.import_module("backend.app.infrastructure.queue.celery_app")
    db_session = importlib.import_module("backend.app.infrastructure.db.session")
    from backend.app.domain.enums import AnalysisStatus

    analysis_id = uuid4()
    old_dispatch_id = uuid4()
    new_dispatch_id = uuid4()
    analysis = type(
        "Analysis",
        (),
        {
            "id": analysis_id,
            "status": AnalysisStatus.QUEUED,
            "queue_task_id": str(new_dispatch_id),
        },
    )()
    dispatch = type(
        "AnalysisDispatch",
        (),
        {
            "id": old_dispatch_id,
            "analysis_id": analysis_id,
            "status": "PUBLISHED",
            "task_id": str(old_dispatch_id),
            "attempts": 1,
            "last_error": None,
            "published_at": None,
        },
    )()

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return dispatch if row_id == old_dispatch_id else analysis

        def add(self, _row):
            pass

        def commit(self):
            pass

        def close(self):
            pass

    publish_calls = {"count": 0}
    async_result_calls = {"count": 0}

    def publish(**_kwargs):
        publish_calls["count"] += 1
        raise AssertionError("stale published dispatch must not be republished")

    def async_result(_task_id):
        async_result_calls["count"] += 1
        raise AssertionError("stale dispatch must be fenced before broker-state inspection")

    monkeypatch.setattr(db_session, "SessionLocal", FakeDB)
    monkeypatch.setattr(module.run_analysis_task, "apply_async", publish)
    monkeypatch.setattr(module.celery_app, "AsyncResult", async_result)

    assert module.publish_analysis_dispatch(old_dispatch_id) == str(new_dispatch_id)
    assert dispatch.status == "SUPERSEDED"
    assert publish_calls["count"] == 0
    assert async_result_calls["count"] == 0
    assert analysis.queue_task_id == str(new_dispatch_id)
