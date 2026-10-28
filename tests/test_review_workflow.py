from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.enums import ReviewStatus, UserRole
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import ACMGAssessment, Analysis, Annotation, Assay, Case, AnalysisPartition, Classification, Evidence, Organization, PedigreeMember, PedigreeRelationship, ReportabilityDecision, ReviewAction, SegregationObservation, Specimen, User, Variant, WorkflowStep
from backend.app.review.service import ReviewAuthorizationError, ReviewConflictError, ReviewError, ReviewMutation, approve_classification, get_review_bundle, propose_manual_classification, review_criterion, request_more_evidence
from backend.app.reporting.reportability import evaluate_analysis, final_reportability_state


def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed():
    db = make_db()
    org = Organization(id=uuid4(), name="Test Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", email="r@example.org", role=UserRole.REVIEWER, status="ACTIVE")
    analyst = User(id=uuid4(), organization_id=org.id, display_name="Analyst", email="a@example.org", role=UserRole.ANALYST, status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="C1", status="ACTIVE", clinical_context={}, language="en", created_by=analyst.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="17", position=1, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key="GRCh38:17:1:A:G", identifiers={})
    assessment = ACMGAssessment(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", criterion="PM2", automated_assessment={"strength": "SUPPORTING"}, state="PROPOSED", review_version=0)
    classification = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="VUS", criterion_ids=[str(assessment.id)], metadata_json={}, state="PROPOSED", review_status=ReviewStatus.IN_REVIEW, version=1, review_version=0)
    db.add_all([org, user, analyst, case, analysis, variant, assessment, classification])
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:1", ordinal=0, record_start=0, record_end=1,
        variant_count=1, status="SUCCEEDED", metadata_json={
            "variant_ids": [str(variant.id)],
            "sample_calls": [{
                "variant_id": str(variant.id), "status": "AVAILABLE",
                "sample_name": "PROBAND", "genotype": "0/1",
                "zygosity": "HETEROZYGOUS", "phase": "UNPHASED",
                "phase_set": None, "format_values": {},
            }],
        },
    ))
    db.commit()
    return db, reviewer_or_user(user), analyst, analysis, variant, assessment, classification


def add_review_evidence(db, reviewer, analysis, variant):
    evidence = Evidence(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        evidence_type="LITERATURE", statement="Reviewed literature evidence.",
        direction="SUPPORTING", source_name="PubMed", source_version="fixture-1",
        source_record_id="PMID:12345678", observation_ids=[], payload={},
        created_by_type="HUMAN", created_by_id=str(reviewer.id),
        evidence_fingerprint=f"review-evidence-{uuid4()}",
    )
    db.add(evidence)
    db.flush()
    return evidence


def reviewer_or_user(x):
    return x


@pytest.mark.parametrize("acmg_error_code", [
    "NO_AUTOMATABLE_CLINGEN_CONTEXT",
    "ACMG_VARIANTS_REQUIRE_REVIEW",
    "CLASSIFICATION_COMBINATION_REQUIRES_REVIEW",
])
def test_manual_classification_proposal_is_evidence_linked_and_audited(acmg_error_code):
    db, reviewer, _, analysis, variant, _, classification = seed()
    db.delete(classification)
    annotation = Annotation(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        provider_name="GeneBe", provider_version="2026.10",
        resource_id=None, resource_name="GeneBe", resource_version="2026.10",
        request_fingerprint="manual-review-request", response_sha256="manual-review-response",
        request_metadata={}, observed_at=datetime.now(timezone.utc), retry_count=0,
        payload={"normalized": {"gene": {"symbol": "TEST"}}},
    )
    evidence = Evidence(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        evidence_type="LITERATURE", statement="Published evidence reviewed by the laboratory.",
        direction="SUPPORTING", source_name="PubMed", source_version="2026",
        resource_id=None, source_record_id="PMID:12345678",
        request_fingerprint="manual-evidence-request", response_sha256="manual-evidence-response",
        request_metadata={}, observed_at=datetime.now(timezone.utc), observation_ids=[],
        payload={}, created_by_type="HUMAN", created_by_id=str(reviewer.id),
        evidence_fingerprint="manual-evidence-fingerprint",
    )
    db.add_all([
        annotation,
        evidence,
        WorkflowStep(
            id=uuid4(), analysis_id=analysis.id, step_id="acmg_assessment", step_order=6,
            status="REQUIRES_REVIEW", attempt=1,
            error_code=acmg_error_code,
            error_message="No validated applicable specification.",
            metadata_json={"next_step": "review"},
        ),
    ])
    db.commit()

    proposal = propose_manual_classification(
        db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer,
        result="VUS", reason="Manual interpretation documented because no applicable automated ACMG specification was available.",
        evidence_ids=(evidence.id,),
    )
    db.commit()

    assert proposal.result == "VUS"
    assert proposal.state == "PROPOSED"
    assert proposal.review_status == ReviewStatus.NOT_STARTED
    assert proposal.criterion_ids == []
    assert proposal.metadata_json["decision_mode"] == "MANUAL"
    assert proposal.metadata_json["automation_status"] == "NOT_AUTOMATED"
    assert proposal.metadata_json["evidence_ids"] == [str(evidence.id)]
    action = db.query(ReviewAction).one()
    assert action.action_type == "MANUAL_CLASSIFICATION_PROPOSED"
    assert action.reason.startswith("Manual interpretation documented")


def test_manual_classification_rejects_evidence_from_another_variant():
    db, reviewer, _, analysis, variant, _, classification = seed()
    db.delete(classification)
    other_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=9,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:9:C:T", identifiers={},
    )
    annotation = Annotation(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        provider_name="GeneBe", provider_version="2026.10",
        resource_id=None, resource_name="GeneBe", resource_version="2026.10",
        request_fingerprint="request", response_sha256="response",
        request_metadata={}, observed_at=None, retry_count=0, payload={},
    )
    evidence = Evidence(
        id=uuid4(), variant_id=other_variant.id, analysis_id=analysis.id,
        evidence_type="LITERATURE", statement="Evidence for a different variant.",
        direction="SUPPORTING", source_name="PubMed", source_version="2026",
        resource_id=None, source_record_id="PMID:87654321",
        request_fingerprint="other-request", response_sha256="other-response",
        request_metadata={}, observed_at=None, observation_ids=[], payload={},
        created_by_type="HUMAN", created_by_id=str(reviewer.id),
        evidence_fingerprint="other-evidence-fingerprint",
    )
    db.add_all([
        other_variant, annotation, evidence,
        WorkflowStep(
            id=uuid4(), analysis_id=analysis.id, step_id="acmg_assessment", step_order=6,
            status="REQUIRES_REVIEW", attempt=1,
            error_code="NO_AUTOMATABLE_CLINGEN_CONTEXT",
            error_message="No validated applicable specification.", metadata_json={},
        ),
    ])
    db.commit()

    with pytest.raises(ReviewError, match="must belong to this variant and analysis"):
        propose_manual_classification(
            db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer,
            result="VUS", reason="Manual review", evidence_ids=(evidence.id,),
        )


def _add_annotation(db, analysis, variant):
    annotation = Annotation(
        id=uuid4(), variant_id=variant.id, analysis_id=analysis.id,
        provider_name="GeneBe", provider_version="2026.10",
        resource_id=None, resource_name="GeneBe", resource_version="2026.10",
        request_fingerprint=f"request-{uuid4()}", response_sha256=f"response-{uuid4()}",
        request_metadata={}, observed_at=datetime.now(timezone.utc), retry_count=0,
        payload={"normalized": {"gene": {"symbol": "TEST"}}},
    )
    db.add(annotation)
    db.flush()
    return annotation


def test_completed_acmg_batch_restores_review_and_blocked_counts():
    from backend.app.workflows.variant import _completed_acmg_batch_outcome_counts

    db, _, _, analysis, _, _, _ = seed()
    step = WorkflowStep(
        id=uuid4(),
        analysis_id=analysis.id,
        step_id="acmg_assessment",
        step_order=6,
        status="SUCCEEDED",
        attempt=1,
        metadata_json={
            "batches": {
                "0:10": {
                    "status": "SUCCEEDED",
                    "requires_review": 2,
                    "blocked": 1,
                }
            }
        },
    )
    db.add(step)
    db.commit()

    assert _completed_acmg_batch_outcome_counts(step, 0, 10) == (2, 1)


def test_manual_acmg_approval_reconciles_when_every_annotated_variant_is_approved():
    from backend.app.workflows.variant import _classification_review_gate_ready, _manual_acmg_review_complete

    db, reviewer, _, analysis, variant, assessment, classification = seed()
    _add_annotation(db, analysis, variant)
    db.delete(assessment)
    classification.criterion_ids = []
    classification.state = "FINAL"
    classification.review_status = ReviewStatus.APPROVED
    classification.metadata_json = {
        "decision_mode": "MANUAL",
        "automation_status": "NOT_AUTOMATED",
        "acmg_criteria_available": False,
    }
    db.commit()

    assert _manual_acmg_review_complete(db, analysis.id) is True
    assert _classification_review_gate_ready(db, analysis.id) is True


def test_classification_gate_blocks_if_any_annotated_variant_has_no_classification():
    from backend.app.workflows.variant import _classification_review_gate_ready, _manual_acmg_review_complete

    db, _, _, analysis, variant, _, classification = seed()
    _add_annotation(db, analysis, variant)
    db.delete(classification)
    db.commit()

    assert _manual_acmg_review_complete(db, analysis.id) is False
    assert _classification_review_gate_ready(db, analysis.id) is False


def test_worker_review_gates_reject_downstream_variants_outside_normalization_manifest():
    from backend.app.workflows.variant import _classification_review_gate_ready, _manual_acmg_review_complete, _reportability_gate_ready

    db, _reviewer, _, analysis, variant, assessment, classification = seed()
    classification.criterion_ids = []
    classification.state = "FINAL"
    classification.review_status = "APPROVED"
    classification.metadata_json = {"decision_mode": "MANUAL"}
    db.delete(assessment)
    _add_annotation(db, analysis, variant)

    extra_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="17", position=2,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key="GRCh38:17:2:C:T", identifiers={},
    )
    extra_classification = Classification(
        id=uuid4(), variant_id=extra_variant.id, analysis_id=analysis.id,
        framework_name="ACMG/AMP", framework_version="2015", result="VUS",
        criterion_ids=[], metadata_json={"decision_mode": "MANUAL"},
        state="FINAL", review_status="APPROVED", version=1, review_version=1,
    )
    db.add_all([extra_variant, extra_classification])
    db.flush()
    _add_annotation(db, analysis, extra_variant)
    db.commit()

    # The normalization manifest seeded for this analysis contains only `variant`.
    # A complete-looking annotation/classification for another variant cannot
    # make either workflow human gate ready.
    assert _manual_acmg_review_complete(db, analysis.id) is False
    assert _classification_review_gate_ready(db, analysis.id) is False
    assert _reportability_gate_ready(db, analysis.id) is False


def test_criterion_review_is_versioned_and_append_only_history():
    db, reviewer, _, analysis, variant, assessment, _ = seed()
    evidence = add_review_evidence(db, reviewer, analysis, variant)
    out = review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("MODIFY", "MODERATE", "Reviewed evidence", (evidence.id,), 0), reviewer=reviewer)
    db.commit()
    assert out.review_version == 1
    assert out.final_assessment["evidence_ids"] == [str(evidence.id)]
    action = db.query(ReviewAction).one()
    assert action.sequence_number == 1
    assert action.before_state["review_version"] == 0
    assert action.resulting_version == 1


def test_criterion_review_preserves_automated_evidence_when_reviewer_omits_reselection():
    db, reviewer, _, analysis, variant, assessment, _ = seed()
    evidence = add_review_evidence(db, reviewer, analysis, variant)
    assessment.automated_assessment = {
        "strength": "SUPPORTING",
        "evidence_ids": [str(evidence.id)],
        "reason": "Evidence was resolved during automated assessment.",
    }
    db.commit()

    reviewed = review_criterion(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        criterion="PM2",
        mutation=ReviewMutation("ACCEPT", "SUPPORTING", "Reviewed source and accepted.", tuple(), 0),
        reviewer=reviewer,
    )
    db.commit()

    assert reviewed.final_assessment["evidence_ids"] == [str(evidence.id)]
    assert reviewed.reviewed_assessment["evidence_ids"] == [str(evidence.id)]


@pytest.mark.parametrize("decision", ["ACCEPT", "MODIFY"])
def test_criterion_review_requires_persisted_evidence_when_no_prior_evidence_exists(decision):
    db, reviewer, _, analysis, variant, _, _ = seed()
    with pytest.raises(ReviewError, match="linked evidence record is required"):
        review_criterion(
            db,
            analysis_id=analysis.id,
            variant_id=variant.id,
            criterion="PM2",
            mutation=ReviewMutation(decision, "SUPPORTING", "No evidence to link.", tuple(), 0),
            reviewer=reviewer,
        )


@pytest.mark.parametrize("decision", ["ACCEPT", "MODIFY"])
def test_criterion_review_requires_explicit_strength(decision):
    db, reviewer, _, analysis, variant, _, _ = seed()
    with pytest.raises(ReviewError, match="explicit valid strength"):
        review_criterion(
            db,
            analysis_id=analysis.id,
            variant_id=variant.id,
            criterion="PM2",
            mutation=ReviewMutation(decision, None, "Reviewed evidence", tuple(), 0),
            reviewer=reviewer,
        )


@pytest.mark.parametrize(
    ("criterion", "strength", "message"),
    [
        ("PM2", "STANDALONE", "Unsupported evidence strength"),
        ("BA1", "SUPPORTING", "BA1 must use strength STANDALONE"),
    ],
)
def test_criterion_review_enforces_framework_strength_for_criterion(criterion, strength, message):
    db, reviewer, _, analysis, variant, assessment, _ = seed()
    assessment.criterion = criterion
    db.commit()
    with pytest.raises(ReviewError, match=message):
        review_criterion(
            db,
            analysis_id=analysis.id,
            variant_id=variant.id,
            criterion=criterion,
            mutation=ReviewMutation("ACCEPT", strength, "Reviewed evidence", tuple(), 0),
            reviewer=reviewer,
        )


def test_stale_review_is_rejected():
    db, reviewer, _, analysis, variant, _, _ = seed()
    evidence = add_review_evidence(db, reviewer, analysis, variant)
    review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("ACCEPT", "MODERATE", "Accept", (evidence.id,), 0), reviewer=reviewer)
    with pytest.raises(ReviewConflictError):
        review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("MODIFY", "SUPPORTING", "Stale", tuple(), 0), reviewer=reviewer)


def test_non_reviewer_is_rejected():
    db, _, analyst, analysis, variant, _, _ = seed()
    with pytest.raises(ReviewAuthorizationError):
        review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("ACCEPT", "MODERATE", "No", tuple(), 0), reviewer=analyst)


def test_more_evidence_updates_status_and_history():
    db, reviewer, _, analysis, variant, _, classification = seed()
    out = request_more_evidence(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer, expected_version=0, reason="Need segregation evidence")
    db.commit()
    assert out.review_status == ReviewStatus.MORE_EVIDENCE
    assert out.review_version == 1
    assert db.query(ReviewAction).count() == 1


def test_approval_creates_new_immutable_classification_version():
    db, reviewer, _, analysis, variant, _, classification = seed()
    new = approve_classification(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer, expected_version=0, reason="Evidence reviewed and approved")
    db.commit()
    assert new.id != classification.id
    assert new.version == 2
    assert new.supersedes_classification_id == classification.id
    assert new.review_status == ReviewStatus.APPROVED
    assert new.state == "FINAL"
    assert db.query(Classification).count() == 2


def test_review_bundle_is_analysis_scoped():
    db, _reviewer, _, analysis, variant, _, _ = seed()
    classification = db.query(Classification).filter_by(analysis_id=analysis.id).one()
    db.add(ReportabilityDecision(
        id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
        classification_id=classification.id, version=1,
        policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY",
        policy_version="1.0.0", disposition="REVIEW", priority_score=60,
        priority_band="REVIEW", reasons=["Legacy test fixture"],
        status="PROPOSED", review_version=0,
    ))
    db.commit()
    second_analysis = Analysis(id=uuid4(), case_id=analysis.case_id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    db.add(second_analysis)
    db.commit()
    bundle = get_review_bundle(db, analysis_id=analysis.id, variant_id=variant.id)
    assert bundle["analysis_id"] == str(analysis.id)
    assert len(bundle["criteria"]) == 1
    assert "priority_score" not in bundle["reportability"]
    assert "priority_band" not in bundle["reportability"]


def test_review_bundle_rejects_assay_from_another_organization():
    db, _reviewer, _analyst, analysis, variant, *_ = seed()
    foreign_org = Organization(id=uuid4(), name="Other lab")
    assay = Assay(
        id=uuid4(), organization_id=foreign_org.id, name="Foreign assay",
        version="1", assay_type="WGS", configuration={"private": "other-lab"},
        status="ACTIVE",
    )
    db.add_all([foreign_org, assay])
    analysis.assay_id = assay.id
    db.commit()

    with pytest.raises(ReviewError, match="assay reference is outside its organization"):
        get_review_bundle(db, analysis_id=analysis.id, variant_id=variant.id)


@pytest.mark.parametrize("broken_link", ["observation_member", "relationship_endpoint", "specimen"])
def test_review_bundle_rejects_pedigree_links_outside_analysis_case(broken_link):
    db, _reviewer, analyst, analysis, variant, *_ = seed()
    case = db.get(Case, analysis.case_id)
    foreign_case = Case(
        id=uuid4(), organization_id=case.organization_id,
        case_identifier=f"FOREIGN-{uuid4()}", status="ACTIVE",
        clinical_context={}, language="en", created_by=analyst.id,
    )
    foreign_member = PedigreeMember(
        id=uuid4(), case_id=foreign_case.id, member_identifier="other-case-member",
        affected_status="AFFECTED", is_proband=False, sampled=True,
    )
    db.add_all([foreign_case, foreign_member])
    if broken_link == "observation_member":
        db.add(SegregationObservation(
            id=uuid4(), analysis_id=analysis.id, variant_id=variant.id,
            pedigree_member_id=foreign_member.id, genotype="0/1",
        ))
    elif broken_link == "relationship_endpoint":
        local_member = PedigreeMember(
            id=uuid4(), case_id=case.id, member_identifier="local-member",
            affected_status="UNKNOWN", is_proband=True, sampled=True,
        )
        db.add_all([
            local_member,
            PedigreeRelationship(
                id=uuid4(), case_id=case.id, parent_member_id=foreign_member.id,
                child_member_id=local_member.id, relationship_type="PARENT_CHILD",
            ),
        ])
    else:
        foreign_specimen = Specimen(
            id=uuid4(), case_id=foreign_case.id, specimen_identifier="other-case-specimen",
        )
        local_member = PedigreeMember(
            id=uuid4(), case_id=case.id, member_identifier="local-member",
            affected_status="UNKNOWN", is_proband=True, sampled=True,
            specimen_id=foreign_specimen.id,
        )
        db.add_all([foreign_specimen, local_member])
    db.commit()

    expected_message = {
        "observation_member": "Segregation observation member does not belong to the analysis case",
        "relationship_endpoint": "Pedigree relationship endpoints do not belong to the analysis case",
        "specimen": "Pedigree member specimen does not belong to the analysis case",
    }[broken_link]
    with pytest.raises(ReviewError, match=expected_message):
        get_review_bundle(db, analysis_id=analysis.id, variant_id=variant.id)

def test_start_review_creates_auditable_state_transition():
    db, reviewer, _, analysis, variant, _, classification = seed()
    from backend.app.review.service import start_review
    out = start_review(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer)
    db.commit()
    assert out.review_status == ReviewStatus.IN_REVIEW
    assert out.review_version == 1
    action = db.query(ReviewAction).one()
    assert action.action_type == "REVIEW_STARTED"


def test_review_api_paths_exist(client):
    paths = set(client.app.openapi().get("paths", {}))
    assert "/api/v1/analyses/{analysis_id}/variants/{variant_id}/review" in paths
    assert "/api/v1/analyses/{analysis_id}/variants/{variant_id}/review/start" in paths
    assert "/api/v1/analyses/{analysis_id}/variants/{variant_id}/review/approve" in paths
    assert "/api/v1/analyses/{analysis_id}/variants/{variant_id}/review/more-evidence" in paths
    assert "/api/v1/analyses/{analysis_id}/review-queue" in paths


def test_approval_requires_active_review():
    from uuid import uuid4
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.app.infrastructure.db.models import Base, Organization, User, Case, Analysis, Variant, Classification
    from backend.app.review.service import approve_classification, ReviewError

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    org = Organization(id=uuid4(), name="Lab")
    reviewer = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", role="REVIEWER", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="C-APPROVE-GATE", status="ACTIVE", clinical_context={}, language="en", created_by=reviewer.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={}, created_by=reviewer.id)
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="1", position=1, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key="GRCh38:1:1:A:G", identifiers={})
    classification = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, version=1, framework_name="ACMG/AMP", framework_version="2015", specification_provider="SIRALOOM", result="VUS", criterion_ids=[], state="PROPOSED", review_status="PENDING", review_version=0)
    db.add_all([org, reviewer, case, analysis, variant, classification]); db.commit()
    try:
        approve_classification(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer, expected_version=0, reason="Approve")
    except ReviewError as exc:
        assert "active review" in str(exc)
    else:
        raise AssertionError("approval should require active review")

def test_review_rejects_evidence_from_another_variant_or_analysis():
    from backend.app.infrastructure.db.models import Evidence
    db, reviewer, _, analysis, variant, _, _ = seed()
    foreign_variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="1", position=2, reference="A", alternate="T", normalization_status="NORMALIZED", canonical_key=f"GRCh38:1:2:A:T-{uuid4()}", identifiers={})
    evidence = Evidence(id=uuid4(), variant_id=foreign_variant.id, analysis_id=analysis.id, evidence_type="LITERATURE", statement="foreign", direction="PATHOGENIC", source_name="test", source_version="1", source_record_id="foreign", observation_ids=[], payload={}, created_by_type="SYSTEM", created_by_id="test", evidence_fingerprint=f"foreign-{uuid4()}")
    db.add_all([foreign_variant, evidence]); db.commit()
    with pytest.raises(ReviewError, match="Every selected evidence record"):
        review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("ACCEPT", "MODERATE", "Invalid evidence link", (evidence.id,), 0), reviewer=reviewer)



def test_approval_cannot_bypass_more_evidence_gate():
    db, reviewer, _, analysis, variant, _, classification = seed()
    request_more_evidence(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        reviewer=reviewer,
        expected_version=0,
        reason="Additional evidence is required",
    )
    with pytest.raises(ReviewError, match="active review"):
        approve_classification(
            db,
            analysis_id=analysis.id,
            variant_id=variant.id,
            reviewer=reviewer,
            expected_version=1,
            reason="Approve without resolving evidence request",
        )


def test_approved_classification_cannot_be_reopened():
    db, reviewer, _, analysis, variant, _, classification = seed()
    approved = approve_classification(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        reviewer=reviewer,
        expected_version=0,
        reason="Evidence reviewed and approved",
    )
    with pytest.raises(ReviewError, match="cannot be reopened"):
        from backend.app.review.service import start_review
        start_review(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer)
    assert approved.review_status == ReviewStatus.APPROVED
    assert approved.state == "FINAL"


def test_inactive_reviewer_cannot_approve():
    db, reviewer, _, analysis, variant, _, _ = seed()
    reviewer.status = "INACTIVE"
    db.commit()
    with pytest.raises(ReviewAuthorizationError, match="not active"):
        approve_classification(
            db,
            analysis_id=analysis.id,
            variant_id=variant.id,
            reviewer=reviewer,
            expected_version=0,
            reason="Should be blocked",
        )



def test_reportability_is_not_created_from_proposed_classification():
    db, _, _, analysis, _, _, _ = seed()
    assert evaluate_analysis(db, analysis) == []
    ready, errors = final_reportability_state(db, analysis.id)
    assert ready is False
    assert any("classification is not FINAL + APPROVED" in error for error in errors)


def test_manual_classification_to_final_reportability_gate_is_auditable():
    from backend.app.review.service import start_review
    from backend.app.reporting.reportability import finalize_reportability

    db, reviewer, _, analysis, variant, assessment, classification = seed()
    db.delete(classification)
    db.delete(assessment)
    annotation = _add_annotation(db, analysis, variant)
    evidence = Evidence(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        evidence_type="LITERATURE",
        statement="Literature evidence documented for manual review.",
        direction="SUPPORTING",
        source_name="PubMed",
        source_version="2026",
        source_record_id="PMID:12345678",
        observation_ids=[],
        payload={},
        created_by_type="HUMAN",
        created_by_id=str(reviewer.id),
        evidence_fingerprint=f"manual-chain-{uuid4()}",
    )
    acmg_step = WorkflowStep(
        id=uuid4(),
        analysis_id=analysis.id,
        step_id="acmg_assessment",
        step_order=6,
        status="REQUIRES_REVIEW",
        attempt=1,
        error_code="NO_AUTOMATABLE_CLINGEN_CONTEXT",
        error_message="No validated applicable specification.",
        metadata_json={"next_step": "review"},
    )
    db.add_all([annotation, evidence, acmg_step])
    db.commit()

    proposal = propose_manual_classification(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        reviewer=reviewer,
        result="VUS",
        reason="Manual interpretation documented because no applicable automated specification was available.",
        evidence_ids=(evidence.id,),
    )
    db.commit()
    started = start_review(db, analysis_id=analysis.id, variant_id=variant.id, reviewer=reviewer)
    db.commit()
    approved = approve_classification(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        reviewer=reviewer,
        expected_version=started.review_version,
        reason="Evidence and rationale reviewed and approved.",
    )
    db.commit()

    assert proposal.state == "PROPOSED"
    assert approved.state == "FINAL"
    assert approved.review_status == ReviewStatus.APPROVED
    assert approved.metadata_json["decision_mode"] == "MANUAL"
    assert approved.criterion_ids == []

    decisions = evaluate_analysis(db, analysis)
    db.commit()
    assert len(decisions) == 1
    assert decisions[0].classification_id == approved.id
    assert decisions[0].status == "PROPOSED"

    finalized = finalize_reportability(
        db,
        decision_id=decisions[0].id,
        reviewer_id=reviewer.id,
        expected_version=decisions[0].review_version,
        disposition="REVIEW",
        reason="Reportability reviewed by authorized reviewer.",
    )
    db.commit()
    assert finalized.status == "FINAL"
    ready, errors = final_reportability_state(db, analysis.id)
    assert ready is True, errors

def test_reportability_is_created_only_after_approved_final_classification():
    db, reviewer, _, analysis, variant, _, _ = seed()
    approved = approve_classification(
        db,
        analysis_id=analysis.id,
        variant_id=variant.id,
        reviewer=reviewer,
        expected_version=0,
        reason="Evidence reviewed and approved",
    )
    decisions = evaluate_analysis(db, analysis)
    db.commit()
    assert len(decisions) == 1
    assert decisions[0].classification_id == approved.id
    assert decisions[0].status == "PROPOSED"
    ready, errors = final_reportability_state(db, analysis.id)
    assert ready is False
    assert any("reportability is not FINAL" in error for error in errors)


def test_review_bundle_rejects_variant_not_in_analysis():
    db, _reviewer, _analyst, analysis, _variant, _assessment, _classification = seed()
    foreign_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=2,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:2:C:T-{uuid4()}", identifiers={},
    )
    db.add(foreign_variant)
    db.commit()

    with pytest.raises(ReviewError, match="not part of this analysis"):
        get_review_bundle(db, analysis_id=analysis.id, variant_id=foreign_variant.id)


def test_manual_classification_rejects_variant_not_in_analysis():
    db, reviewer, _analyst, analysis, _variant, _assessment, classification = seed()
    from backend.app.infrastructure.db.models import WorkflowStep

    db.delete(classification)
    db.add(WorkflowStep(
        id=uuid4(), analysis_id=analysis.id, step_id="acmg_assessment",
        step_order=6, status="REQUIRES_REVIEW", attempt=1,
        error_code="NO_AUTOMATABLE_CLINGEN_CONTEXT",
        metadata_json={"next_step": "review"},
    ))
    foreign_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=3,
        reference="G", alternate="A", normalization_status="NORMALIZED",
        canonical_key=f"GRCh38:1:3:G:A-{uuid4()}", identifiers={},
    )
    db.add(foreign_variant)
    db.commit()

    with pytest.raises(ReviewError, match="not part of this analysis"):
        propose_manual_classification(
            db, analysis_id=analysis.id, variant_id=foreign_variant.id,
            reviewer=reviewer, result="VUS", reason="Reviewed outside analysis",
            evidence_ids=(uuid4(),),
        )
