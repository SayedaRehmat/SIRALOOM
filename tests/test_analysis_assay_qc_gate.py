from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import analyses
from backend.app.auth.principal import Principal
from backend.app.domain.schemas import AnalysisCreate
from backend.app.infrastructure.db.models import Assay, Case


class _DB:
    def __init__(self, case, assay):
        self.case = case
        self.assay = assay

    def get(self, model, _identifier):
        if model is Case:
            return self.case
        if model is Assay:
            return self.assay
        raise AssertionError(f"Unexpected model lookup: {model}")


@pytest.mark.parametrize(
    "assay_changes",
    [
        {"organization_id": uuid4()},
        {"status": "INACTIVE"},
        {"configuration": {"rules": []}},
        {"configuration": None},
    ],
)
def test_analysis_creation_rejects_assays_without_current_tenant_qc_profile(monkeypatch, assay_changes):
    organization_id = uuid4()
    case = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    assay_values = {
        "id": uuid4(),
        "organization_id": organization_id,
        "status": "ACTIVE",
        "configuration": {"rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 20}]},
    }
    assay_values.update(assay_changes)
    assay = SimpleNamespace(**assay_values)
    db = _DB(case, assay)
    principal = Principal(
        user_id=uuid4(), organization_id=organization_id,
        role="bioinformatician", subject="test",
    )
    monkeypatch.setattr(analyses, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(analyses, "require_role", lambda *_args: None)
    monkeypatch.setattr(analyses, "require_analysis_quota", lambda *_args: None)

    with pytest.raises(HTTPException, match="active, same-organization assay with QC rules") as error:
        analyses.create(
            str(case.id),
            AnalysisCreate(input_artifact_id=uuid4(), assay_id=assay.id),
            db,
            principal,
        )

    assert error.value.status_code == 400
