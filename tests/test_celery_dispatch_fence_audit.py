"""Regression tests for Celery task registration and durable dispatch fencing."""
from types import SimpleNamespace
from uuid import UUID, uuid4

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


def test_every_registered_application_task_has_an_explicit_scope_classification():
    app = queue.celery_app
    workload_tasks = {
        "backend.app.infrastructure.queue.celery_app.run_analysis_task",
        "backend.app.infrastructure.queue.celery_app.run_case_export_task",
        "siraloom.stage_resource_release",
    }
    system_tasks = {
        "siraloom.discover_scientific_resources",
        "siraloom.scan_reanalysis_resources",
        "siraloom.dispatch_pending_analysis_outbox",
        "siraloom.recover_orphaned_analysis_dispatches",
        "siraloom.dispatch_pending_case_export_outbox",
        "siraloom.recover_orphaned_case_export_dispatches",
    }

    # Enumerate the full application-owned namespace before comparing against
    # the scope inventory. Filtering through the expected set first would make
    # this guard blind to a newly registered but unclassified task.
    registered = {
        name
        for name in app.tasks
        if name.startswith(("siraloom.", "backend.app.infrastructure.queue.celery_app."))
    }
    scheduled = {
        entry["task"] for entry in app.conf.beat_schedule.values()
    }

    assert registered == workload_tasks | system_tasks
    assert scheduled == system_tasks
    assert not scheduled & workload_tasks


@pytest.mark.parametrize("organization_id", [None, str(uuid4())])
def test_reanalysis_scan_task_passes_scope_to_domain_scanner(monkeypatch, organization_id):
    from backend.app.infrastructure.db import session as session_module

    class FakeDatabase:
        closed = False

        def close(self):
            self.closed = True

    db = FakeDatabase()
    calls = []
    monkeypatch.setattr(session_module, "SessionLocal", lambda: db)

    def scan(actual_db, *, organization_id):
        calls.append((actual_db, organization_id))
        return 3

    monkeypatch.setattr(
        "backend.app.domain.reanalysis.scan_active_resources_for_reanalysis", scan
    )

    result = queue.scan_reanalysis_resources.run(organization_id)

    assert result == {"candidates_created": 3}
    assert calls == [(db, UUID(organization_id) if organization_id else None)]
    assert db.closed is True


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
