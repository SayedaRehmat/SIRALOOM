from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Classification,
    Organization,
    ReportabilityDecision,
    User,
    Variant,
)
from backend.app.reporting.reportability import (
    evaluate_analysis,
    finalize_reportability,
    final_reportability_state,
    pending_specialized_artifact_errors,
)


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


def test_final_reportability_state_rejects_decision_linked_to_stale_classification(monkeypatch):
    db = make_db()
    org = Organization(id=uuid4(), name="Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", role="MEDICAL_REVIEWER", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="CASE-LINK", status="ACTIVE", clinical_context={}, language="en", created_by=user.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="1", position=12, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key="GRCh38:1:12:A:G", identifiers={})
    cls1 = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="PATHOGENIC", criterion_ids=[], metadata_json={}, state="FINAL", review_status="APPROVED", version=1, review_version=1)
    cls2 = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result="LIKELY_PATHOGENIC", criterion_ids=[], metadata_json={}, state="FINAL", review_status="APPROVED", version=2, supersedes_classification_id=cls1.id)
    from backend.app.infrastructure.db.models import ReportabilityDecision
    decision = ReportabilityDecision(id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, classification_id=cls1.id, version=1, policy_name="SIRALOOM_DEFAULT_GERMLINE_REPORTABILITY", policy_version="1.0.0", disposition="REPORT", priority_score=100, priority_band="HIGH", reasons=["test"], status="FINAL", review_version=1)
    db.add_all([org, user, case, analysis, variant, cls1, cls2, decision])
    db.commit()
    from backend.app.reporting.reportability import final_reportability_state
    ok, errors = final_reportability_state(db, analysis.id)
    assert not ok
    assert any("stale classification" in error for error in errors)
    from pytest import raises
    with raises(ValueError, match="stale because it is not linked"):
        finalize_reportability(
            db,
            decision_id=decision.id,
            reviewer_id=user.id,
            expected_version=decision.review_version,
            disposition="REPORT",
            reason="Do not accept a stale sign-off retry",
        )
    from fastapi import HTTPException
    from backend.app.api.v1 import reports as reports_api
    monkeypatch.setattr(reports_api, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports_api, "_require_reportability_variant", lambda *_args: None)
    with raises(HTTPException) as exc_info:
        reports_api.list_reportability(
            analysis.id,
            db,
            type("Principal", (), {"organization_id": org.id})(),
        )
    assert exc_info.value.status_code == 409


@pytest.mark.parametrize(
    ("artifact_type", "filename", "reason_code"),
    [
        ("CNV_VARIANT_RECORDS", "cnv-variants.vcf", "CNV_PIPELINE_PENDING"),
        ("STRUCTURAL_VARIANT_RECORDS", "structural-variants.vcf", "SV_PIPELINE_PENDING"),
        ("MITOCHONDRIAL_VARIANT_RECORDS", "mitochondrial-variants.vcf", "MITOCHONDRIAL_VARIANT_PIPELINE_PENDING"),
        ("REPEAT_EXPANSION_RECORDS", "repeat-expansion-variants.vcf", "REPEAT_EXPANSION_PIPELINE_PENDING"),
    ],
)
def test_pending_specialized_variant_artifact_blocks_reportability_finalization(
    artifact_type, filename, reason_code
):
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
        case_identifier="CASE-SPECIALIZED-ROUTING",
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
        position=20,
        reference="A",
        alternate="G",
        normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:20:A:G",
        identifiers={},
    )
    classification = Classification(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        framework_name="ACMG/AMP",
        framework_version="2015",
        result="LIKELY_PATHOGENIC",
        criterion_ids=[],
        metadata_json={},
        state="FINAL",
        review_status="APPROVED",
        version=1,
        review_version=1,
    )
    routed_artifact = Artifact(
        id=uuid4(),
        case_id=case.id,
        analysis_id=analysis.id,
        artifact_type=artifact_type,
        filename=filename,
        media_type="text/vcf",
        size_bytes=1,
        sha256="a" * 64,
        storage_uri="file:///tmp/mitochondrial-variants.vcf",
        genome_build="GRCh38",
        validation_status="VALID",
        # Deliberately omit review_status: the artifact type itself must
        # remain a hard reportability blocker in the first product.
        metadata_json={"interpretation_status": "NOT_ANALYZED"},
    )
    db.add_all([org, user, case, analysis, variant, classification, routed_artifact])
    db.commit()

    proposals = evaluate_analysis(db, analysis)
    db.commit()
    assert len(proposals) == 1

    # The specialized artifact is retained but explicitly outside the fixed
    # first-product SNV/INDEL analytical scope; it is not a sign-out blocker.
    assert pending_specialized_artifact_errors(db, analysis.id) == []
    assert len(proposals) == 1
