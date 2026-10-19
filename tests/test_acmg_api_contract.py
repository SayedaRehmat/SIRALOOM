from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.acmg.rules import ALL_CRITERIA
from backend.app.api.v1.acmg import ACMGAssessRequest, ACMGCriterionInput


def _criterion(**overrides):
    values = {
        "criterion": "PM2",
        "strength": "MODERATE",
        "direction": "PATHOGENIC",
        "evidence_ids": [uuid4()],
        "reason": "Persisted evidence reviewed",
    }
    values.update(overrides)
    return values


def test_acmg_api_rejects_empty_criterion_list():
    with pytest.raises(ValidationError):
        ACMGAssessRequest.model_validate({"variant_id": str(uuid4()), "criteria": []})


def test_acmg_api_bounds_criteria_to_supported_unique_code_capacity():
    with pytest.raises(ValidationError):
        ACMGAssessRequest.model_validate({
            "variant_id": str(uuid4()),
            "criteria": [_criterion() for _ in range(len(ALL_CRITERIA) + 1)],
        })


def test_acmg_api_bounds_evidence_references_per_criterion():
    with pytest.raises(ValidationError):
        ACMGCriterionInput.model_validate(
            _criterion(evidence_ids=[str(uuid4()) for _ in range(101)])
        )


def test_acmg_api_criterion_schema_uses_engine_supported_code_set():
    accepted = ACMGCriterionInput.model_validate(_criterion())
    assert accepted.criterion in ALL_CRITERIA

    with pytest.raises(ValidationError):
        ACMGCriterionInput.model_validate(_criterion(criterion="PP6"))
