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

        def refresh(self, _row):
            pass

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

        def refresh(self, _row):
            pass

    db = FakeDB()
    monkeypatch.setattr(
        "backend.app.infrastructure.queue.celery_app.publish_analysis_dispatch",
        lambda _dispatch_id: None,
    )

    assert enqueue_analysis(db, analysis) is None
    assert analysis.status == AnalysisStatus.QUEUED
    dispatch = next(row for row in db.rows if row.__class__.__name__ == "AnalysisDispatch")
    assert dispatch.dispatch_generation == 5
    assert analysis.queue_task_id is None
