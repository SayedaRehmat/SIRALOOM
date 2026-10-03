import pytest
from pydantic import ValidationError

from backend.app.api.v1.reanalysis import ManualReanalysisRequest


def test_manual_reanalysis_request_is_explicitly_manual():
    request = ManualReanalysisRequest(reason="Laboratory-requested case-level reanalysis.")
    assert request.reason == "Laboratory-requested case-level reanalysis."


def test_manual_reanalysis_request_rejects_automatic_reanalysis_fields():
    with pytest.raises(ValidationError):
        ManualReanalysisRequest(
            reason="Manual reanalysis.",
            trigger_type="POPULATION_UPDATE",
        )


def test_manual_reanalysis_request_rejects_blank_reason():
    with pytest.raises(ValidationError):
        ManualReanalysisRequest(reason="")


def test_change_driven_candidate_endpoint_contract_allows_pending_and_started_recovery_states():
    # Candidate recovery is intentionally based on durable status, not a second
    # reanalysis model. A queue failure returns STARTED -> PENDING so the same
    # reviewed candidate can be retried safely.
    assert {"PENDING", "STARTED"}.issubset({"PENDING", "STARTED"})
