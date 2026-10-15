from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import acmg, pedigree, reports
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


def test_pedigree_member_cannot_reference_specimen_from_another_case(monkeypatch):
    from backend.app.infrastructure.db.models import Case, Specimen

    case_id, specimen_id, organization_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    foreign_specimen = SimpleNamespace(id=specimen_id, case_id=uuid4())

    class _CaseDb:
        def get(self, model, _object_id):
            return {Case: case, Specimen: foreign_specimen}.get(model)

    monkeypatch.setattr(pedigree, "require_case_tenant", lambda *_args: None)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    payload = pedigree.MemberInput(
        member_identifier="family-member",
        specimen_id=specimen_id,
    )

    with pytest.raises(HTTPException) as exc:
        pedigree.add_member(
            case_id=case_id,
            body=payload,
            db=_CaseDb(),
            principal=_principal(organization_id),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Specimen not found in this case"


@pytest.mark.parametrize("route", [reports.get_export, reports.download_case_export])
def test_case_export_hides_foreign_exports_like_missing_exports(route):
    from backend.app.infrastructure.db.models import Case, CaseExport

    organization_id = uuid4()
    principal = _principal(organization_id)
    export = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        status="QUEUED",
        artifact_id=None,
    )
    foreign_case = SimpleNamespace(organization_id=uuid4())

    responses = []
    for row in (None, export):
        class _ExportDb:
            def get(self, model, _object_id):
                if model is CaseExport:
                    return row
                if model is Case:
                    return foreign_case
                raise AssertionError(f"Unexpected model lookup: {model}")

        with pytest.raises(HTTPException) as exc:
            route(export.id if row is not None else uuid4(), db=_ExportDb(), principal=principal)
        responses.append((exc.value.status_code, exc.value.detail))

    assert responses == [(404, "Export not found"), (404, "Export not found")]
