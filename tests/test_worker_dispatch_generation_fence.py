from uuid import uuid4

import pytest

from backend.app.infrastructure.queue import celery_app as queue


class _UntouchedDatabase:
    """A missing task identity must be rejected before database access."""

    def get_bind(self):
        raise AssertionError("claim attempted database access without a dispatch identity")

    def get(self, *_args, **_kwargs):
        raise AssertionError("claim attempted database access without a dispatch identity")


@pytest.mark.parametrize("task_id", [None, "", "   "])
@pytest.mark.parametrize(
    ("claim", "identifier_name"),
    [
        (queue._claim_analysis_execution, "analysis"),
        (queue._claim_case_export_execution, "case export"),
    ],
)
def test_worker_claim_rejects_missing_dispatch_identity_before_database_access(
    claim, identifier_name, task_id
):
    """A task UUID alone is not authority to execute a tenant-owned workload."""
    db = _UntouchedDatabase()
    identifier = uuid4()

    assert claim(db, identifier, task_id=task_id) is False, (
        f"{identifier_name} worker accepted a task without a durable dispatch ID"
    )
