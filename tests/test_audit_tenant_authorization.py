from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1 import (
    acmg,
    clinical_followup,
    evidence,
    pedigree,
    phenotypes,
    quality,
    reports,
    reanalysis as reanalysis_api,
    variants,
)
from backend.app.api.v1.audit import audit
from backend.app.auth.principal import Principal


class _Db:
    def __init__(self, case):
        self.case = case

    def get(self, _model, _case_id):
        return self.case


def _principal(organization_id, role="reviewer"):
    return Principal(
        user_id=uuid4(),
        organization_id=organization_id,
        role=role,
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


def test_evidence_endpoint_hides_foreign_evidence_like_missing_evidence(monkeypatch):
    from backend.app.infrastructure.db.models import Evidence

    evidence_id = uuid4()
    row = SimpleNamespace(id=evidence_id, analysis_id=uuid4())
    monkeypatch.setattr(
        evidence,
        "get_accessible_analysis",
        lambda *_args: (_ for _ in ()).throw(HTTPException(404, "Analysis not found")),
    )

    class _EvidenceDb:
        def __init__(self, stored):
            self.stored = stored

        def get(self, model, _object_id):
            assert model is Evidence
            return self.stored

    responses = []
    for stored in (None, row):
        with pytest.raises(HTTPException) as exc:
            evidence.get_evidence(evidence_id, _EvidenceDb(stored), _principal(uuid4()))
        responses.append((exc.value.status_code, exc.value.detail))

    assert responses == [(404, "Evidence not found"), (404, "Evidence not found")]


def test_evidence_endpoint_hides_variant_outside_analysis(monkeypatch):
    from backend.app.infrastructure.db.models import Evidence

    evidence_id = uuid4()
    row = SimpleNamespace(
        id=evidence_id,
        analysis_id=uuid4(),
        variant_id=uuid4(),
    )
    analysis = SimpleNamespace(id=row.analysis_id)
    monkeypatch.setattr(evidence, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        evidence,
        "get_analysis_variant",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(404, "Variant is not part of this analysis")
        ),
    )

    class _EvidenceDb:
        def get(self, model, _object_id):
            assert model is Evidence
            return row

    with pytest.raises(HTTPException) as exc:
        evidence.get_evidence(evidence_id, _EvidenceDb(), _principal(uuid4()))

    assert exc.value.status_code == 404
    assert exc.value.detail == "Evidence not found"


def test_followup_endpoint_hides_foreign_plan_like_missing_plan(monkeypatch):
    from backend.app.infrastructure.db.models import FollowUpPlan

    followup_id = uuid4()
    row = SimpleNamespace(id=followup_id, analysis_id=uuid4())
    monkeypatch.setattr(
        clinical_followup,
        "get_accessible_analysis",
        lambda *_args: (_ for _ in ()).throw(HTTPException(404, "Analysis not found")),
    )
    payload = clinical_followup.FollowUpInput(action_type="contact")

    class _FollowUpDb:
        def __init__(self, stored):
            self.stored = stored

        def get(self, model, _object_id):
            assert model is FollowUpPlan
            return self.stored

    responses = []
    for stored in (None, row):
        with pytest.raises(HTTPException) as exc:
            clinical_followup.update_followup(
                followup_id, payload, _FollowUpDb(stored), _principal(uuid4())
            )
        responses.append((exc.value.status_code, exc.value.detail))

    assert responses == [
        (404, "Follow-up plan not found"),
        (404, "Follow-up plan not found"),
    ]


def test_reportability_signoff_hides_foreign_decision_like_missing_decision(monkeypatch):
    from backend.app.infrastructure.db.models import ReportabilityDecision

    decision_id = uuid4()
    row = SimpleNamespace(id=decision_id, analysis_id=uuid4())
    monkeypatch.setattr(
        reports,
        "get_accessible_analysis",
        lambda *_args: (_ for _ in ()).throw(HTTPException(404, "Analysis not found")),
    )

    class _DecisionDb:
        def __init__(self, stored):
            self.stored = stored

        def get(self, model, _object_id):
            assert model is ReportabilityDecision
            return self.stored

    payload = SimpleNamespace()
    responses = []
    for stored in (None, row):
        with pytest.raises(HTTPException) as exc:
            reports.finalize_reportability_decision(
                decision_id, payload, _DecisionDb(stored), _principal(uuid4())
            )
        responses.append((exc.value.status_code, exc.value.detail))

    assert responses == [
        (404, "Reportability decision not found"),
        (404, "Reportability decision not found"),
    ]


def test_reportability_signoff_rejects_variant_outside_analysis(monkeypatch):
    analysis = SimpleNamespace(id=uuid4())
    decision = SimpleNamespace(id=uuid4(), analysis_id=analysis.id, variant_id=uuid4())
    principal = _principal(uuid4(), role="lab_director")
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        reports,
        "get_analysis_variant",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(404, "Variant is not part of this analysis")
        ),
    )

    class _DecisionDb:
        def get(self, model, _object_id):
            from backend.app.infrastructure.db.models import ReportabilityDecision

            assert model is ReportabilityDecision
            return decision

    with pytest.raises(HTTPException) as exc:
        reports.finalize_reportability_decision(
            decision.id, SimpleNamespace(), _DecisionDb(), principal
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Reportability decision references a variant outside its analysis"


def test_reportability_listing_rejects_variant_outside_analysis(monkeypatch):
    analysis = SimpleNamespace(id=uuid4())
    decision = SimpleNamespace(variant_id=uuid4())
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        reports,
        "get_analysis_variant",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(404, "Variant is not part of this analysis")
        ),
    )

    class _Rows:
        def __iter__(self):
            return iter([decision])

    class _Db:
        def scalars(self, _query):
            return _Rows()

    with pytest.raises(HTTPException) as exc:
        reports.list_reportability(
            analysis.id, _Db(), _principal(uuid4())
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Reportability decision references a variant outside its analysis"


def test_followup_update_rejects_case_mismatch_with_its_analysis(monkeypatch):
    analysis = SimpleNamespace(id=uuid4(), case_id=uuid4())
    row = SimpleNamespace(
        id=uuid4(), analysis_id=analysis.id, case_id=uuid4(), variant_id=None
    )
    principal = _principal(uuid4(), role="lab_director")
    monkeypatch.setattr(
        clinical_followup, "get_accessible_analysis", lambda *_args: analysis
    )

    class _Db:
        def get(self, model, _object_id):
            from backend.app.infrastructure.db.models import FollowUpPlan

            assert model is FollowUpPlan
            return row

    with pytest.raises(HTTPException) as exc:
        clinical_followup.update_followup(
            row.id, clinical_followup.FollowUpInput(action_type="contact"),
            _Db(), principal,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Follow-up plan case does not match its analysis"


def test_variant_details_require_analysis_membership(monkeypatch):
    from backend.app.infrastructure.db.models import Analysis, Variant

    variant_id, analysis_id = uuid4(), uuid4()
    annotation = SimpleNamespace(analysis_id=analysis_id)
    variant = SimpleNamespace(id=variant_id)
    analysis = SimpleNamespace(id=analysis_id)
    principal = _principal(uuid4())

    class _ScalarRows:
        def __init__(self, value):
            self.value = value

        def first(self):
            return self.value

        def all(self):
            return []

    class _Db:
        def get(self, model, _object_id):
            return {Variant: variant, Analysis: analysis}.get(model)

        def scalar(self, _query):
            return annotation

        def scalars(self, _query):
            return _ScalarRows(None)

    monkeypatch.setattr(
        variants,
        "get_analysis_variant",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(404, "Variant is not part of this analysis")
        ),
    )

    with pytest.raises(HTTPException) as exc:
        variants.get_variant(variant_id, _Db(), principal)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Variant not found"


@pytest.mark.parametrize("operation", ["read", "assess"])
def test_segregation_lineage_rejects_member_from_another_case(monkeypatch, operation):
    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    foreign_member_id = uuid4()
    observation = SimpleNamespace(pedigree_member_id=foreign_member_id)
    principal = _principal(uuid4(), role="reviewer")

    class _Db:
        def __init__(self):
            self.results = [[observation], []]

        def scalars(self, _query):
            return self.results.pop(0)

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        if operation == "read":
            pedigree.get_segregation(analysis_id, variant_id, db, principal)
        else:
            pedigree.assess_inheritance(
                analysis_id,
                variant_id,
                SimpleNamespace(models=[], reviewer_note=None),
                db,
                principal,
            )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Segregation observation member does not belong to the analysis case"


@pytest.mark.parametrize("broken_link", ["relationship", "specimen"])
def test_pedigree_dossier_rejects_cross_case_links(monkeypatch, broken_link):
    case_id, member_id, specimen_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=uuid4())
    member = SimpleNamespace(
        id=member_id,
        specimen_id=specimen_id if broken_link == "specimen" else None,
    )
    relationship = (
        SimpleNamespace(parent_member_id=uuid4(), child_member_id=member_id)
        if broken_link == "relationship"
        else None
    )

    class _Db:
        def __init__(self):
            self.results = [[member], [relationship] if relationship else []]
            if broken_link == "specimen":
                self.results.append([SimpleNamespace(id=specimen_id, case_id=uuid4())])

        def get(self, _model, _object_id):
            return case

        def scalars(self, _query):
            return self.results.pop(0)

    monkeypatch.setattr(pedigree, "require_case_tenant", lambda *_args: None)
    with pytest.raises(HTTPException) as exc:
        pedigree.get_pedigree(case_id, _Db(), _principal(case.organization_id))

    assert exc.value.status_code == 409


def test_report_list_rejects_case_link_different_from_analysis(monkeypatch):
    analysis_id, case_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    malformed_report = SimpleNamespace(case_id=uuid4())
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)

    class _Db:
        def scalars(self, _query):
            return [malformed_report]

    with pytest.raises(HTTPException) as exc:
        reports.list_reports(analysis_id, _Db(), _principal(uuid4()))

    assert exc.value.status_code == 409
    assert exc.value.detail == "Report case does not match its analysis"


@pytest.mark.parametrize(
    "broken_link",
    [
        "case_tenant",
        "analysis_case",
        "candidate_case",
        "resource_tenant",
        "resource_discovery",
    ],
)
def test_notification_list_rejects_cross_tenant_or_inconsistent_links(broken_link):
    from backend.app.infrastructure.db.models import (
        Analysis,
        Case,
        ReanalysisCandidate,
        Resource,
        ResourceDiscovery,
    )

    organization_id, foreign_organization_id = uuid4(), uuid4()
    user_id = uuid4()
    case_id, foreign_case_id = uuid4(), uuid4()
    analysis_id, candidate_id, resource_id, discovery_id = uuid4(), uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(
        id=case_id if broken_link != "case_tenant" else foreign_case_id,
        organization_id=(
            foreign_organization_id if broken_link == "case_tenant" else organization_id
        ),
    )
    analysis = SimpleNamespace(
        id=analysis_id,
        case_id=foreign_case_id if broken_link == "analysis_case" else case_id,
    )
    candidate = SimpleNamespace(
        organization_id=organization_id,
        case_id=foreign_case_id if broken_link == "candidate_case" else case_id,
        parent_analysis_id=analysis_id,
    )
    resource = SimpleNamespace(
        id=resource_id,
        organization_id=foreign_organization_id if broken_link == "resource_tenant" else None,
    )
    discovery = SimpleNamespace(
        resource_id=uuid4() if broken_link == "resource_discovery" else resource_id
    )
    row = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        notification_type=(
            "RESOURCE_RELEASE_DISCOVERED"
            if broken_link in {"resource_tenant", "resource_discovery"}
            else "REANALYSIS_CANDIDATE"
        ),
        case_id=None if broken_link in {"resource_tenant", "resource_discovery"} else case.id,
        analysis_id=(
            analysis_id if broken_link in {"analysis_case", "candidate_case"} else None
        ),
        candidate_id=candidate_id if broken_link == "candidate_case" else None,
        metadata_json=(
            {"resource_id": str(resource_id), "discovery_id": str(discovery_id)}
            if broken_link in {"resource_tenant", "resource_discovery"}
            else {}
        ),
    )

    class _Db:
        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [row])

        def get(self, model, object_id):
            if model is Case and object_id == row.case_id:
                return case
            if model is Analysis and object_id == analysis_id:
                return analysis
            if model is ReanalysisCandidate and object_id == candidate_id:
                return candidate
            if model is Resource and object_id == resource_id:
                return resource
            if model is ResourceDiscovery and object_id == discovery_id:
                return discovery
            return None

    with pytest.raises(HTTPException) as exc:
        reanalysis_api.notifications(
            _Db(),
            SimpleNamespace(organization_id=organization_id, user_id=user_id),
        )

    assert exc.value.status_code == 409


def test_secondary_finding_list_rejects_variant_outside_analysis(monkeypatch):
    analysis_id, variant_id = uuid4(), uuid4()
    principal = _principal(uuid4())
    analysis = SimpleNamespace(id=analysis_id)
    row = SimpleNamespace(analysis_id=analysis_id, variant_id=variant_id)
    monkeypatch.setattr(clinical_followup, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        clinical_followup,
        "_variant_access",
        lambda *_args: (_ for _ in ()).throw(
            HTTPException(404, "Variant is not part of this analysis")
        ),
    )

    class _Db:
        def scalars(self, _query):
            return [row]

    with pytest.raises(HTTPException) as exc:
        clinical_followup.list_secondary_findings(
            analysis_id=analysis_id,
            db=_Db(),
            principal=principal,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Variant is not part of this analysis"


def test_quality_read_rejects_analysis_assay_from_another_tenant(monkeypatch):
    from backend.app.infrastructure.db.models import Assay

    organization_id = uuid4()
    analysis = SimpleNamespace(id=uuid4(), assay_id=uuid4())
    foreign_assay = SimpleNamespace(organization_id=uuid4())
    monkeypatch.setattr(quality, "get_accessible_analysis", lambda *_args: analysis)

    class _Db:
        def scalars(self, _query):
            return []

        def get(self, model, _object_id):
            assert model is Assay
            return foreign_assay

    with pytest.raises(HTTPException) as exc:
        quality.get_quality(
            analysis_id=analysis.id,
            db=_Db(),
            principal=_principal(organization_id),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Analysis assay reference is outside its organization"


def test_case_phenotype_list_rejects_analysis_from_another_case(monkeypatch):
    from backend.app.infrastructure.db.models import Analysis, Case

    case_id, foreign_case_id, organization_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    row = SimpleNamespace(case_id=case_id, analysis_id=uuid4())
    foreign_analysis = SimpleNamespace(case_id=foreign_case_id)
    monkeypatch.setattr(phenotypes, "require_case_tenant", lambda *_args: None)

    class _Db:
        def get(self, model, _object_id):
            return {Case: case, Analysis: foreign_analysis}.get(model)

        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [row])

    with pytest.raises(HTTPException) as exc:
        phenotypes.list_case_phenotypes(
            case_id=case_id,
            db=_Db(),
            principal=_principal(organization_id),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Phenotype analysis does not match its case"
