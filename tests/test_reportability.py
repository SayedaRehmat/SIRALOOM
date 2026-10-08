from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    Classification,
    Organization,
    ReportabilityDecision,
    User,
    Variant,
)
from backend.app.reporting.reportability import evaluate_analysis, finalize_reportability


def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_reportability_evaluation_is_idempotent_for_same_classification():
    db = make_db()
    org = Organization(id=uuid4(), name="Lab")
    user = User(
        id=uuid4(),
        organization_id=org.id,
        display_name="Reviewer",
        role="MEDICAL_REVIEWER",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=org.id,
        case_identifier="CASE-1",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=user.id,
    )
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version="1.0",
        status="REQUIRES_REVIEW",
        reference_build="GRCh38",
        configuration={},
    )
    variant = Variant(
        id=uuid4(),
        genome_build="GRCh38",
        chromosome="1",
        position=10,
        reference="A",
        alternate="G",
        normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:10:A:G",
        identifiers={},
    )
    classification = Classification(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        framework_name="ACMG/AMP",
        framework_version="2015",
        result="PATHOGENIC",
        criterion_ids=[],
        metadata_json={},
        state="FINAL",
        review_status="APPROVED",
        version=1,
        review_version=1,
    )
    db.add_all([org, user, case, analysis, variant, classification])
    db.commit()

    first = evaluate_analysis(db, analysis)
    db.commit()
    second = evaluate_analysis(db, analysis)

    assert len(first) == 1
    assert second == []
    assert (
        db.query(ReportabilityDecision)
        .filter(
            ReportabilityDecision.analysis_id == analysis.id,
            ReportabilityDecision.variant_id == variant.id,
        )
        .count()
        == 1
    )


def test_reportability_finalization_rejects_stale_decision_after_new_classification():
    db = make_db()
    org = Organization(id=uuid4(), name="Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", role="MEDICAL_REVIEWER", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="CASE-STALE", status="ACTIVE", clinical_context={}, language="en", created_by=user.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="1", position=11, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key="GRCh38:1:11:A:G", identifiers={})
    cls1 = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="PATHOGENIC", criterion_ids=[], metadata_json={}, state="FINAL", review_status="APPROVED", version=1, review_version=1)
    db.add_all([org, user, case, analysis, variant, cls1])
    db.commit()
    first = evaluate_analysis(db, analysis)
    db.commit()
    assert len(first) == 1
    cls2 = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="LIKELY_PATHOGENIC", criterion_ids=[], metadata_json={}, state="FINAL", review_status="APPROVED", version=2, review_version=1)
    db.add(cls2)
    db.commit()
    second = evaluate_analysis(db, analysis)
    db.commit()
    assert len(second) == 1
    from pytest import raises
    with raises(ValueError, match="no longer the latest"):
        finalize_reportability(db, decision_id=first[0].id, reviewer_id=user.id, expected_version=first[0].review_version, disposition="REPORT", reason="Stale decision")
