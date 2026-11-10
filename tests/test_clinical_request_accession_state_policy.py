"""State-policy tests for clinical request accession decisions."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1.clinical_requests import _assert_accession_decision_state


@pytest.mark.parametrize("status", ["SUBMITTED", "UNDER_REVIEW"])
def test_accession_decision_accepts_only_submitted_workflow_states(status):
    request = SimpleNamespace(status=status, current_revision_id=uuid4())
    _assert_accession_decision_state(request)


@pytest.mark.parametrize(
    "status",
    [
        "DRAFT",
        "NEEDS_INFORMATION",
        "REASSESSMENT_REQUIRED",
        "ACCEPTED",
        "REJECTED",
        "CLOSED",
    ],
)
def test_accession_decision_rejects_states_that_require_resubmission_or_are_terminal(status):
    request = SimpleNamespace(status=status, current_revision_id=uuid4())
    with pytest.raises(HTTPException) as exc:
        _assert_accession_decision_state(request)
    assert exc.value.status_code == 409


def test_accession_decision_requires_current_revision():
    request = SimpleNamespace(status="SUBMITTED", current_revision_id=None)
    with pytest.raises(HTTPException) as exc:
        _assert_accession_decision_state(request)
    assert exc.value.status_code == 409
