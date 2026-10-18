from uuid import uuid4
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Organization, User, Case, Analysis, Variant, Classification, Report, ReportabilityDecision, AnalysisPartition
from backend.app.reporting.reportability import evaluate_analysis, finalize_reportability, final_reportability_state
from backend.app.reporting.service import build_report_content, final_report_eligibility
from backend.app.reporting.finalization import finalize_report, ReportFinalizationError


def make_db():
    e = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(e)
    return Session(e)


def seed(result="PATHOGENIC"):
    db = make_db()
    org = Organization(id=uuid4(), name="Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", role="clinical_geneticist", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="M6", status="ACTIVE", clinical_context={"test":"Panel", "indication":"Example"}, language="en", created_by=user.id)
    analysis = Analysis(id=uuid4(), case_id=case.id, analysis_type="VARIANT_INTERPRETATION", workflow_id="variant-v1", workflow_version="1.0", status="REQUIRES_REVIEW", reference_build="GRCh38", configuration={})
    variant = Variant(id=uuid4(), genome_build="GRCh38", chromosome="1", position=10, reference="A", alternate="G", normalization_status="NORMALIZED", canonical_key=f"GRCh38:1:10:A:G:{uuid4()}", identifiers={})
    classification = Classification(id=uuid4(), variant_id=variant.id, analysis_id=analysis.id, framework_name="ACMG/AMP", framework_version="2015", result=result, criterion_ids=[], metadata_json={}, state="FINAL", review_status="APPROVED", version=1, review_version=1, reviewed_by=user.id)
    db.add_all([org, user, case, analysis, variant, classification]); db.commit()
    return db, user, case, analysis, variant, classification


def test_evaluate_creates_first_class_decision():
    db, _, _, analysis, _, _ = seed("PATHOGENIC")
    created = evaluate_analysis(db, analysis)
    db.commit()
    assert len(created) == 1
    assert created[0].disposition == "REPORT"
    assert created[0].priority_score == 100
    ok, errors = final_reportability_state(db, analysis.id)
    assert not ok and any("not FINAL" in e for e in errors)


def test_reportability_evaluation_rejects_classification_outside_normalization_manifest():
    db, _, _, analysis, _, _ = seed("PATHOGENIC")
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": []},
    ))
    db.commit()

    with pytest.raises(ValueError, match="outside the normalized input"):
        evaluate_analysis(db, analysis)
    assert db.query(ReportabilityDecision).filter_by(analysis_id=analysis.id).count() == 0


def test_reportability_evaluation_route_returns_conflict_for_manifest_mismatch(monkeypatch):
    from fastapi import HTTPException
    from backend.app.api.v1 import reports

    db, _, _, analysis, _, _ = seed("PATHOGENIC")
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": []},
    ))
    db.commit()
    monkeypatch.setattr(reports, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports, "require_role", lambda *_args: None)

    with pytest.raises(HTTPException) as exc:
        reports.evaluate_reportability(analysis.id, db=db, principal=object())

    assert exc.value.status_code == 409
    assert db.query(ReportabilityDecision).filter_by(analysis_id=analysis.id).count() == 0


def test_reportability_state_requires_classification_coverage_of_manifest():
    db, _, _, analysis, _, _ = seed("PATHOGENIC")
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": []},
    ))
    db.commit()

    ready, errors = final_reportability_state(db, analysis.id)
    assert not ready
    assert any("do not exactly match" in error for error in errors)


def test_reportability_state_rejects_orphan_decision_without_classification():
    db, _, _, analysis, variant, classification = seed("PATHOGENIC")
    outside_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="1", position=11,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:11:C:T", identifiers={},
    )
    orphan = ReportabilityDecision(
        id=uuid4(), analysis_id=analysis.id, variant_id=outside_variant.id,
        classification_id=classification.id, version=1, policy_name="TEST_POLICY",
        policy_version="1", disposition="REPORT", priority_score=100,
        priority_band="HIGH", reasons=[], status="FINAL", review_version=1,
    )
    db.add(outside_variant)
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:1", ordinal=0, record_start=0, record_end=1,
        variant_count=1, status="SUCCEEDED", metadata_json={"variant_ids": [str(variant.id)]},
    ))
    db.add(orphan)
    db.commit()

    ready, errors = final_reportability_state(db, analysis.id)
    assert not ready
    assert any("without a classification" in error for error in errors)
    assert any("outside the normalized input" in error for error in errors)


def test_reportability_finalize_is_version_checked_and_audited():
    db, user, _, analysis, _, _ = seed("VUS")
    decision = evaluate_analysis(db, analysis)[0]
    db.commit()
    out = finalize_reportability(db, decision_id=decision.id, reviewer_id=user.id, expected_version=0, disposition="REPORT", reason="Explicitly report after clinical review")
    db.commit()
    assert out.status == "FINAL"
    assert out.disposition == "REPORT"
    assert out.reviewed_by == user.id
    ok, errors = final_reportability_state(db, analysis.id)
    assert ok, errors


def test_reportability_finalize_rejects_variant_outside_normalization_manifest():
    db, user, _, analysis, _, _ = seed("PATHOGENIC")
    decision = evaluate_analysis(db, analysis)[0]
    db.commit()
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:0", ordinal=0, record_start=0, record_end=0,
        variant_count=0, status="SUCCEEDED", metadata_json={"variant_ids": []},
    ))
    db.commit()

    with pytest.raises(ValueError, match="outside the normalized analysis input"):
        finalize_reportability(
            db, decision_id=decision.id, reviewer_id=user.id,
            expected_version=decision.review_version, disposition="REPORT",
            reason="Must not finalize an out-of-input variant",
        )


def test_clinical_report_contains_only_final_report_findings():
    db, user, case, analysis, variant, classification = seed("PATHOGENIC")
    evaluate_analysis(db, analysis)
    decision = db.scalar(select(ReportabilityDecision).where(ReportabilityDecision.analysis_id == analysis.id))
    finalize_reportability(db, decision_id=decision.id, reviewer_id=user.id, expected_version=0, disposition="REPORT", reason="Reviewed")
    db.commit()
    content = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    assert len(content["findings"]) == 1
    assert content["findings"][0]["reportability"]["disposition"] == "REPORT"
    assert content["report_schema_version"] == "1.1.0"
    assert content["final_result"]["release_state"] == "NOT_FOR_CLINICAL_RELEASE"


def test_finalization_blocked_until_reportability_final():
    db, user, case, analysis, _, _ = seed("PATHOGENIC")
    evaluate_analysis(db, analysis); db.commit()
    report = Report(id=uuid4(), case_id=case.id, analysis_id=analysis.id, report_version=1, language="en", report_type="CLINICAL_INTERPRETATION", status="DRAFT", content_json={})
    db.add(report); db.commit()
    try:
        finalize_report(db, report_id=report.id, approver_id=user.id, reason="Attempted before reportability sign-out")
        assert False, "Expected finalization gate to reject incomplete reportability"
    except ReportFinalizationError as exc:
        assert "reportability is not FINAL" in str(exc)
