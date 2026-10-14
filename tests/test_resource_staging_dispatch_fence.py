from types import SimpleNamespace

import pytest

from backend.app.infrastructure.queue import celery_app as queue


@pytest.mark.parametrize(
    ("task_id", "dispatch", "expected"),
    [
        (None, {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("", {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("dispatch-old", {"status": "PUBLISHED", "task_id": "dispatch-current"}, False),
        ("dispatch-current", {"status": "FAILED", "task_id": "dispatch-current"}, False),
        ("dispatch-current", {"status": "PUBLISHED", "task_id": "dispatch-current"}, True),
        ("dispatch-current", {"status": "RUNNING", "task_id": "dispatch-current"}, True),
        ("dispatch-current", {"status": "QUEUING", "task_id": "dispatch-current"}, True),
    ],
)
def test_resource_staging_worker_requires_current_persisted_dispatch(task_id, dispatch, expected):
    row = SimpleNamespace(metadata_json={"staging_dispatch": dispatch})
    assert queue._resource_staging_dispatch_matches(row, task_id) is expected
