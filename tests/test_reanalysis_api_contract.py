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
