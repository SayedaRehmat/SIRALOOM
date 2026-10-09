from uuid import uuid4

from backend.app.application.analysis import enqueue_analysis
from backend.app.domain.enums import AnalysisStatus


def test_enqueue_analysis_commits_dispatch_intent_before_publication(monkeypatch):
    analysis = type(
        "Analysis",
        (),
        {
            "id": uuid4(),
            "status": AnalysisStatus.CREATED,
            "queue_task_id": None,
        },
    )()

    class FakeDB:
        def __init__(self):
            self.rows = []
            self.commits = 0

        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return analysis

        def scalar(self, _stmt):
            return 0

        def add(self, row):
            self.rows.append(row)

        def commit(self):
            self.commits += 1

        def refresh(self, _row, **kwargs):
            if kwargs:
                assert kwargs == {"with_for_update": True}

    db = FakeDB()
    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
        lambda _dispatch_id: None,
    )

    assert enqueue_analysis(db, analysis) is None
    assert analysis.status == AnalysisStatus.QUEUED
    dispatches = [row for row in db.rows if row.__class__.__name__ == "AnalysisDispatch"]
    assert len(dispatches) == 1
    assert dispatches[0].analysis_id == analysis.id
    assert dispatches[0].dispatch_generation == 1
    assert dispatches[0].status == "PENDING"
    assert analysis.queue_task_id == str(dispatches[0].id)
    assert db.commits == 1


def test_enqueue_analysis_uses_new_dispatch_generation_for_retry(monkeypatch):
    analysis = type(
        "Analysis",
        (),
        {
            "id": uuid4(),
            "status": AnalysisStatus.FAILED,
            "queue_task_id": "failed-task",
        },
    )()

    class FakeDB:
        def __init__(self):
            self.rows = []
            self.commits = 0

        def get(self, model, row_id, **kwargs):
            assert kwargs == {"with_for_update": True}
            return analysis

        def scalar(self, _stmt):
            return 4

        def add(self, row):
            self.rows.append(row)

        def commit(self):
            self.commits += 1

        def refresh(self, _row, **kwargs):
            if kwargs:
                assert kwargs == {"with_for_update": True}

    db = FakeDB()
    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
        lambda _dispatch_id: None,
    )

    assert enqueue_analysis(db, analysis) is None
    assert analysis.status == AnalysisStatus.QUEUED
    dispatch = next(row for row in db.rows if row.__class__.__name__ == "AnalysisDispatch")
    assert dispatch.dispatch_generation == 5
    assert analysis.queue_task_id == str(dispatch.id)


def test_dispatch_outbox_relay_only_scans_queued_analyses(monkeypatch):
    import importlib
    from types import SimpleNamespace

    module = importlib.import_module(
        "backend.app.infrastructure.queue.celery_app"
    )

    class FakeDB:
        def __init__(self):
            self.closed = False

        def scalars(self, _stmt):
            return iter(["queued-dispatch"])

        def close(self):
            self.closed = True

    db = FakeDB()
    monkeypatch.setattr(
        "backend.app.infrastructure.db.session.SessionLocal",
        lambda: db,
    )

    published = []
    monkeypatch.setattr(
        module,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(dispatch_id) or dispatch_id,
    )

    result = module.dispatch_pending_analysis_outbox()

    assert result == {"inspected": 1, "dispatched": 1}
    assert published == ["queued-dispatch"]
    assert db.closed


def test_dispatch_boundary_rejects_laboratory_analysis_without_resource_profile(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import backend.app.application.analysis as analysis_module
    from backend.app.domain.enums import AnalysisStatus

    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        status=AnalysisStatus.CREATED,
        queue_task_id=None,
        configuration={},
    )
    case = SimpleNamespace(organization_id=uuid4())

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            if model.__name__ == "Analysis":
                return analysis
            if model.__name__ == "Case":
                return case
            return None

        def refresh(self, _row, **_kwargs):
            return None

    monkeypatch.setattr(
        analysis_module,
        "resolve_resource_deployment_policy",
        lambda *_args, **_kwargs: SimpleNamespace(is_laboratory=True),
    )

    with pytest.raises(ValueError, match="RESOURCE_PROFILE_REQUIRED"):
        enqueue_analysis(FakeDB(), analysis)


def test_dispatch_boundary_rejects_profile_without_runnable_persisted_plan(monkeypatch):
    from types import SimpleNamespace
    import pytest
    import backend.app.application.analysis as analysis_module
    from backend.app.domain.enums import AnalysisStatus

    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        status=AnalysisStatus.CREATED,
        queue_task_id=None,
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {"status": "BLOCKED", "plan_hash": "blocked"},
        },
    )
    case = SimpleNamespace(organization_id=uuid4())

    class FakeDB:
        def get(self, model, row_id, **kwargs):
            if model.__name__ == "Analysis":
                return analysis
            if model.__name__ == "Case":
                return case
            return None

        def refresh(self, _row, **_kwargs):
            return None

    monkeypatch.setattr(
        analysis_module,
        "resolve_resource_deployment_policy",
        lambda *_args, **_kwargs: SimpleNamespace(is_laboratory=True),
    )

    with pytest.raises(ValueError, match="RESOURCE_PLAN_NOT_READY"):
        enqueue_analysis(FakeDB(), analysis)
