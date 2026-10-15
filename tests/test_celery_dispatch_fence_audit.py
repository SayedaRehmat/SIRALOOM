"""Regression tests for Celery task registration and durable dispatch fencing."""
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.queue import celery_app as queue


class _StaleDispatchDatabase:
    """Minimal DB double whose persisted queue pointer belongs to a newer task."""

    def __init__(self, row):
        self.row = row
        self.get_calls = 0
        self.commits = 0
        self.adds = 0

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    def get(self, *_args, **_kwargs):
        self.get_calls += 1
        return self.row

    def add(self, _row):
        self.adds += 1

    def commit(self):
        self.commits += 1


def test_every_periodic_beat_entry_references_a_registered_task():
    app = queue.celery_app
    scheduled_names = {
        entry["task"] for entry in app.conf.beat_schedule.values()
    }

    assert scheduled_names
    assert scheduled_names <= set(app.tasks.keys())


def test_worker_delivery_configuration_rejects_lost_worker_tasks():
    app = queue.celery_app

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


@pytest.mark.parametrize(
    ("claim", "row", "current_task_id"),
    [
        (
            queue._claim_analysis_execution,
            SimpleNamespace(
                queue_task_id="new-analysis-dispatch",
                status=AnalysisStatus.QUEUED,
            ),
            "old-analysis-dispatch",
        ),
        (
            queue._claim_case_export_execution,
            SimpleNamespace(
                queue_task_id="new-export-dispatch",
                status="QUEUED",
            ),
            "old-export-dispatch",
        ),
    ],
)
def test_stale_dispatch_identity_is_rejected_without_mutating_workload(
    claim, row, current_task_id
):
    db = _StaleDispatchDatabase(row)

    accepted = claim(
        db,
        uuid4(),
        task_id=current_task_id,
    )

    assert accepted is False
    assert db.get_calls == 1
    assert db.adds == 0
    assert db.commits == 0


@pytest.mark.parametrize("task_id", [None, "", "   ", "obsolete-dispatch"])
def test_resource_staging_dispatch_fence_rejects_missing_or_stale_task_ids(task_id):
    row = SimpleNamespace(
        metadata_json={
            "staging_dispatch": {
                "task_id": "current-dispatch",
                "status": "PUBLISHED",
            }
        }
    )

    assert queue._resource_staging_dispatch_matches(row, task_id) is False


def test_resource_staging_dispatch_fence_accepts_current_published_task_id():
    row = SimpleNamespace(
        metadata_json={
            "staging_dispatch": {
                "task_id": "current-dispatch",
                "status": "PUBLISHED",
            }
        }
    )

    assert queue._resource_staging_dispatch_matches(row, "current-dispatch") is True
