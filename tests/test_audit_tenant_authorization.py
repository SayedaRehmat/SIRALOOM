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
from backend.app.domain.enums import AnalysisStatus


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


def test_read_only_user_cannot_create_analysis_resource_provenance_snapshot(monkeypatch):
    organization_id = uuid4()
    analysis_id = uuid4()
    principal = _principal(organization_id, role="read_only")
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4(), status="SUCCEEDED")
    monkeypatch.setattr(reanalysis_api, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(
        reanalysis_api,
        "snapshot_analysis_resources",
        lambda *_args, **_kwargs: pytest.fail("read-only request must not create snapshots"),
    )

    with pytest.raises(HTTPException) as exc:
        reanalysis_api.snapshot(analysis_id, object(), principal)

    assert exc.value.status_code == 403


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


@pytest.mark.parametrize("broken_link", ["foreign_resource", "missing_resource"])
def test_acmg_auto_assessment_rejects_invalid_population_resource_lineage(
    monkeypatch, broken_link
):
    from backend.app.infrastructure.db.models import Annotation, PopulationObservation, Resource

    analysis_id, variant_id, resource_id = uuid4(), uuid4(), uuid4()
    organization_id = uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    annotation = SimpleNamespace(payload={})
    observation = SimpleNamespace(resource_id=resource_id)
    resource = (
        SimpleNamespace(id=resource_id, organization_id=uuid4())
        if broken_link == "foreign_resource"
        else None
    )

    class _AssessmentDb:
        def scalar(self, statement):
            assert statement.column_descriptions[0]["entity"] is Annotation
            return annotation

        def scalars(self, statement):
            entity = statement.column_descriptions[0]["entity"]
            rows = [observation] if entity is PopulationObservation else ([resource] if resource else [])
            return SimpleNamespace(all=lambda: rows)

    monkeypatch.setattr(acmg, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(acmg, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(acmg, "require_role", lambda *_args: None)
    monkeypatch.setattr(
        acmg,
        "ACMGSpecificationAssessmentService",
        lambda: (_ for _ in ()).throw(AssertionError("assessment must not run")),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        acmg.auto_assess(
            analysis_id=analysis_id,
            variant_id=variant_id,
            payload=acmg.ACMGAutoAssessRequest(gene="GENE1"),
            db=_AssessmentDb(),
            principal=_principal(organization_id),
        )

    assert exc.value.status_code == 409


def test_pedigree_member_cannot_reference_specimen_from_another_case(monkeypatch):
    from backend.app.infrastructure.db.models import Case, Specimen

    case_id, specimen_id, organization_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    foreign_specimen = SimpleNamespace(id=specimen_id, case_id=uuid4())

    class _CaseDb:
        def get(self, model, _object_id):
            return {Case: case, Specimen: foreign_specimen}.get(model)

    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
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


def test_pedigree_relationship_rejects_cycle_before_persisting(monkeypatch):
    from backend.app.infrastructure.db.models import Case, PedigreeMember, PedigreeRelationship

    organization_id = uuid4()
    case_id = uuid4()
    member_a_id, member_b_id, member_c_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    members = {
        member_a_id: SimpleNamespace(id=member_a_id, case_id=case_id),
        member_b_id: SimpleNamespace(id=member_b_id, case_id=case_id),
        member_c_id: SimpleNamespace(id=member_c_id, case_id=case_id),
    }
    existing = [
        SimpleNamespace(parent_member_id=member_a_id, child_member_id=member_b_id),
        SimpleNamespace(parent_member_id=member_b_id, child_member_id=member_c_id),
    ]

    class _PedigreeDb:
        added = None

        def get(self, model, object_id, **_kwargs):
            if model is Case:
                return case if object_id == case_id else None
            if model is PedigreeMember:
                return members.get(object_id)
            return None

        def refresh(self, *_args, **_kwargs):
            pass

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: existing)

        def scalar(self, _statement):
            return None

        def add(self, row):
            self.added = row

    db = _PedigreeDb()
    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)

    with pytest.raises(HTTPException) as exc:
        pedigree.add_relationship(
            case_id=case_id,
            body=pedigree.RelationshipInput(
                parent_member_id=member_c_id,
                child_member_id=member_a_id,
            ),
            db=db,
            principal=_principal(organization_id),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "Pedigree relationship would create a parentage cycle"
    assert db.added is None


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


@pytest.mark.parametrize(
    ("analysis_status", "should_resume"),
    [
        (AnalysisStatus.SUCCEEDED, False),
        (AnalysisStatus.REQUIRES_REVIEW, True),
        (AnalysisStatus.QUEUED, True),
        (AnalysisStatus.RUNNING, True),
    ],
)
def test_reportability_final_retry_is_idempotent_after_analysis_terminal(
    monkeypatch, analysis_status, should_resume
):
    from backend.app.infrastructure.db.models import Analysis, ReportabilityDecision

    analysis = SimpleNamespace(id=uuid4(), status=analysis_status)
    decision = SimpleNamespace(
        id=uuid4(), analysis_id=analysis.id, variant_id=uuid4(), status="FINAL",
        version=2, review_version=3, disposition="REPORT", priority_score=100,
        priority_band="HIGH", reviewed_by=uuid4(), approved_at=None,
    )
    resume_calls = []
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports, "_require_reportability_variant", lambda *_args: None)
    monkeypatch.setattr(reports, "finalize_reportability", lambda *_args, **_kwargs: decision)
    monkeypatch.setattr(
        reports,
        "resume_analysis",
        lambda *_args: resume_calls.append(analysis.id) or "dispatch-id",
    )

    class _Db:
        commits = 0

        def get(self, model, _object_id):
            assert model is ReportabilityDecision
            return decision

        def commit(self):
            self.commits += 1

    db = _Db()
    result = reports.finalize_reportability_decision(
        decision.id,
        SimpleNamespace(expected_version=2, disposition="REPORT", reason="Reviewed"),
        db,
        _principal(uuid4(), role="lab_director"),
    )

    assert result["status"] == "FINAL"
    assert result["workflow_resume_queued"] is should_resume
    assert bool(resume_calls) is should_resume
    assert db.commits == 1


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


def test_variant_details_hide_unassigned_case_even_for_org_member(monkeypatch):
    variant_id, analysis_id = uuid4(), uuid4()
    principal = _principal(uuid4())

    class _ScalarRows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class _Db:
        calls = 0

        def scalars(self, _query):
            self.calls += 1
            return _ScalarRows([analysis_id] if self.calls == 1 else [])

    db = _Db()
    monkeypatch.setattr(
        variants,
        "get_accessible_analysis",
        lambda *_args: (_ for _ in ()).throw(HTTPException(404, "Case not found")),
    )
    monkeypatch.setattr(
        variants,
        "get_analysis_variant",
        lambda *_args: pytest.fail("variant membership must not be read before case access"),
    )

    with pytest.raises(HTTPException) as exc:
        variants.get_variant(variant_id, db, principal, analysis_id=analysis_id)

    assert (exc.value.status_code, exc.value.detail) == (404, "Variant not found")
    assert db.calls == 1


def test_variant_details_select_newest_analysis_the_user_can_read(monkeypatch):
    variant_id = uuid4()
    newest_unassigned_id, older_assigned_id = uuid4(), uuid4()
    principal = _principal(uuid4())
    analysis = SimpleNamespace(id=older_assigned_id)
    variant = SimpleNamespace(
        id=variant_id, genome_build="GRCh38", chromosome="1", position=123,
        reference="A", alternate="G", normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:123:A:G", identifiers={},
    )

    class _ScalarRows:
        def __init__(self, values):
            self.values = values

        def all(self):
            return self.values

    class _Db:
        calls = 0

        def scalars(self, _query):
            self.calls += 1
            return _ScalarRows(
                [newest_unassigned_id, older_assigned_id] if self.calls == 1 else []
            )

    db = _Db()
    visited = []

    def accessible(analysis_id, *_args):
        visited.append(analysis_id)
        if analysis_id == newest_unassigned_id:
            raise HTTPException(404, "Case not found")
        return analysis

    monkeypatch.setattr(variants, "get_accessible_analysis", accessible)
    monkeypatch.setattr(variants, "get_analysis_variant", lambda *_args: variant)

    response = variants.get_variant(variant_id, db, principal)

    assert visited == [newest_unassigned_id, older_assigned_id]
    assert response["variant"]["id"] == str(variant_id)
    assert db.calls == 6


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


def test_inheritance_assessment_rejects_duplicate_normalized_models_before_reads(monkeypatch):
    analysis_id, variant_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=uuid4())
    principal = _principal(uuid4(), role="reviewer")

    monkeypatch.setattr(pedigree, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(pedigree, "get_analysis_variant", lambda *_args: SimpleNamespace(id=variant_id))
    monkeypatch.setattr(pedigree, "require_role", lambda *_args: None)

    class _Db:
        def scalars(self, _query):
            pytest.fail("duplicate model request must be rejected before database reads")

    payload = pedigree.AssessmentInput(models=["AD", "autosomal dominant"])
    with pytest.raises(HTTPException) as exc:
        pedigree.assess_inheritance(analysis_id, variant_id, payload, _Db(), principal)

    assert exc.value.status_code == 400
    assert exc.value.detail == "Duplicate inheritance model: AD"


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

    monkeypatch.setattr(pedigree, "require_case_permission", lambda *_args: None)
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
    ("status", "invalid_check", "detail"),
    [
        (
            "DRAFT",
            "has_valid_draft_artifact",
            "Report draft artifact does not match its case and analysis",
        ),
        (
            "FINAL",
            "has_valid_signed_artifact",
            "Final or superseded report is missing a valid linked signed artifact",
        ),
        (
            "SUPERSEDED",
            "has_valid_signed_artifact",
            "Final or superseded report is missing a valid linked signed artifact",
        ),
    ],
)
def test_report_list_rejects_invalid_pdf_lineage(monkeypatch, status, invalid_check, detail):
    analysis_id, case_id = uuid4(), uuid4()
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id)
    row = SimpleNamespace(case_id=case_id, status=status)
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports, "has_valid_draft_artifact", lambda *_args: invalid_check != "has_valid_draft_artifact")
    monkeypatch.setattr(reports, "has_valid_signed_artifact", lambda *_args: invalid_check != "has_valid_signed_artifact")

    class _Db:
        def scalars(self, _query):
            return [row]

    with pytest.raises(HTTPException) as exc:
        reports.list_reports(analysis_id, _Db(), _principal(uuid4()))

    assert exc.value.status_code == 409
    assert exc.value.detail == detail


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


def test_notification_read_rejects_invalid_case_lineage_before_mutation():
    from backend.app.infrastructure.db.models import Case, Notification

    organization_id = uuid4()
    principal = _principal(organization_id)
    row = SimpleNamespace(
        id=uuid4(), organization_id=organization_id, user_id=principal.user_id,
        case_id=uuid4(), analysis_id=None, candidate_id=None,
        notification_type="REANALYSIS_CANDIDATE", metadata_json={}, status="UNREAD",
        read_at=None,
    )

    class _Db:
        commits = 0

        def get(self, model, object_id):
            if model is Notification and object_id == row.id:
                return row
            if model is Case and object_id == row.case_id:
                return SimpleNamespace(id=row.case_id, organization_id=uuid4())
            return None

        def commit(self):
            self.commits += 1

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        reanalysis_api.mark_notification_read(row.id, db, principal)

    assert exc.value.status_code == 409
    assert row.status == "UNREAD"
    assert db.commits == 0


def test_notification_read_retry_preserves_first_read_timestamp():
    from datetime import datetime, timezone

    from backend.app.infrastructure.db.models import Notification

    principal = _principal(uuid4())
    first_read_at = datetime(2026, 10, 17, tzinfo=timezone.utc)
    row = SimpleNamespace(
        id=uuid4(), organization_id=principal.organization_id, user_id=principal.user_id,
        case_id=None, analysis_id=None, candidate_id=None,
        notification_type="SYSTEM", metadata_json={}, status="READ", read_at=first_read_at,
    )

    class _Db:
        commits = 0

        def get(self, model, object_id):
            return row if model is Notification and object_id == row.id else None

        def commit(self):
            self.commits += 1

    db = _Db()
    result = reanalysis_api.mark_notification_read(row.id, db, principal)

    assert result == {"notification_id": str(row.id), "status": "READ"}
    assert row.read_at is first_read_at
    assert db.commits == 0


def test_notification_list_omits_case_notifications_after_access_revocation(monkeypatch):
    principal = _principal(uuid4())
    visible_case_id, revoked_case_id = uuid4(), uuid4()
    visible = SimpleNamespace(
        id=uuid4(), organization_id=principal.organization_id, user_id=principal.user_id,
        notification_type="REANALYSIS_CANDIDATE", status="UNREAD", title="Visible case",
        body="Review is available", case_id=visible_case_id, analysis_id=uuid4(),
        candidate_id=uuid4(), metadata_json={}, created_at=None, read_at=None,
    )
    revoked = SimpleNamespace(
        id=uuid4(), organization_id=principal.organization_id, user_id=principal.user_id,
        notification_type="REANALYSIS_CANDIDATE", status="UNREAD", title="Revoked case",
        body="No longer assigned", case_id=revoked_case_id, analysis_id=uuid4(),
        candidate_id=uuid4(), metadata_json={}, created_at=None, read_at=None,
    )

    class _NotificationDb:
        def scalars(self, _query):
            return SimpleNamespace(all=lambda: [visible, revoked])

    monkeypatch.setattr(reanalysis_api, "_validate_notification_lineage", lambda *_args: None)

    def require_case_access(row, _db, _principal):
        if row.id == revoked.id:
            raise HTTPException(status_code=404, detail="Case not found")

    monkeypatch.setattr(reanalysis_api, "_require_notification_case_access", require_case_access)

    result = reanalysis_api.notifications(_NotificationDb(), principal)

    assert len(result) == 1
    assert result[0]["notification_id"] == str(visible.id)


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
    monkeypatch.setattr(phenotypes, "require_case_permission", lambda *_args: None)

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
