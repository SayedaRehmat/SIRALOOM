from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import acmg
from backend.app.api.v1.audit import audit
from backend.app.auth.principal import Principal


class _Db:
    def __init__(self, case):
        self.case = case

    def get(self, _model, _case_id):
        return self.case


def _principal(organization_id):
    return Principal(
        user_id=uuid4(),
        organization_id=organization_id,
        role="reviewer",
        subject="verified-firebase-subject",
    )


def test_audit_hides_absent_and_cross_tenant_case_ids_identically():
    organization_id = uuid4()
    principal = _principal(organization_id)
    foreign_case = SimpleNamespace(organization_id=uuid4())

    responses = []
    for case in (None, foreign_case):
        with pytest.raises(HTTPException) as exc:
            audit(case_id=uuid4(), db=_Db(case), principal=principal)
        responses.append((exc.value.status_code, exc.value.detail))

    assert responses == [(404, "Case not found"), (404, "Case not found")]


def test_acmg_auto_assessment_rejects_variant_outside_analysis(monkeypatch):
    analysis_id = uuid4()
    variant_id = uuid4()
    principal = _principal(uuid4())
    analysis = SimpleNamespace(id=analysis_id)

    monkeypatch.setattr(acmg, "get_accessible_analysis", lambda *_args: analysis)

    def reject_foreign_variant(_analysis, _variant_id, _db):
        raise HTTPException(status_code=404, detail="Variant is not part of this analysis")

    monkeypatch.setattr(acmg, "get_analysis_variant", reject_foreign_variant)
    payload = acmg.ACMGAutoAssessRequest(gene="GENE1")

    with pytest.raises(HTTPException) as exc:
        acmg.auto_assess(
            analysis_id=analysis_id,
            variant_id=variant_id,
            payload=payload,
            db=object(),
            principal=principal,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Variant is not part of this analysis"
