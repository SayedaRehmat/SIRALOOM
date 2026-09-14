from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.enums import ReviewStatus, UserRole
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import ACMGAssessment, Analysis, Case, Classification, Organization, ReviewAction, User, Variant
from backend.app.review.service import ReviewAuthorizationError, ReviewConflictError, ReviewError, ReviewMutation, approve_classification, get_review_bundle, review_criterion, request_more_evidence


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
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="17", position=1, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key=f"GRCh38:17:1:A:G", identifiers={})
    assessment = ACMGAssessment(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", criterion="PM2", automated_assessment={"strength": "SUPPORTING"}, state="PROPOSED", review_version=0)
    classification = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="VUS", criterion_ids=[str(assessment.id)], metadata_json={}, state="PROPOSED", review_status=ReviewStatus.IN_REVIEW, version=1, review_version=0)
    db.add_all([org, user, analyst, case, analysis, variant, assessment, classification])
    db.commit()
    return db, reviewer_or_user(user), analyst, analysis, variant, assessment, classification


def reviewer_or_user(x):
    return x


def test_criterion_review_is_versioned_and_append_only_history():
    db, reviewer, _, analysis, variant, assessment, _ = seed()
    out = review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("MODIFY", "MODERATE", "Reviewed evidence", tuple(), 0), reviewer=reviewer)
    db.commit()
    assert out.review_version == 1
    action = db.query(ReviewAction).one()
    assert action.sequence_number == 1
    assert action.before_state["review_version"] == 0
    assert action.resulting_version == 1


def test_stale_review_is_rejected():
    db, reviewer, _, analysis, variant, _, _ = seed()
    review_criterion(db, analysis_id=analysis.id, variant_id=variant.id, criterion="PM2", mutation=ReviewMutation("ACCEPT", "MODERATE", "Accept", tuple(), 0), reviewer=reviewer)
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
    db, reviewer, _, analysis, variant, _, _ = seed()
    second_analysis = Analysis(id=uuid4(), case_id=analysis.case_id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    db.add(second_analysis)
    db.commit()
    bundle = get_review_bundle(db, analysis_id=analysis.id, variant_id=variant.id)
    assert bundle["analysis_id"] == str(analysis.id)
    assert len(bundle["criteria"]) == 1

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
    paths = {route.path for route in client.app.routes}
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
