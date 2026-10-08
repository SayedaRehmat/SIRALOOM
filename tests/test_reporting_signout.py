from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    Case,
    Classification,
    Organization,
    Report,
    ReportabilityDecision,
    User,
    Variant,
)
from backend.app.reporting.finalization import finalize_report
from backend.app.reporting.service import build_report_content, final_report_eligibility


def make_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def seed_finalizable_report():
    db = make_db()
    org = Organization(id=uuid4(), name="Test Lab")
    reviewer = User(
        id=uuid4(),
        organization_id=org.id,
        display_name="Sign-out Reviewer",
        email="signout@example.org",
        role="lab_director",
        status="ACTIVE",
    )
    case = Case(
        id=uuid4(),
        organization_id=org.id,
        case_identifier="RPT-1",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=reviewer.id,
    )
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version="2.1",
        status="SUCCEEDED",
        reference_build="GRCh38",
        configuration={},
        created_by=reviewer.id,
    )
    variant = Variant(
        id=uuid4(),
        genome_build="GRCh38",
        chromosome="17",
        position=1,
        reference="A",
        alternate="G",
        normalization_status="NORMALIZED",
        canonical_key="GRCh38:17:1:A:G",
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
        reviewed_by=reviewer.id,
    )
    decision = ReportabilityDecision(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        classification_id=classification.id,
        version=1,
        policy_name="TEST_POLICY",
        policy_version="1.0",
        disposition="REPORT",
        priority_score=100,
        priority_band="HIGH",
        reasons=["Reviewed"],
        status="FINAL",
        review_version=1,
        reviewed_by=reviewer.id,
    )
    draft_artifact = Artifact(
        id=uuid4(),
        analysis_id=analysis.id,
        case_id=case.id,
        artifact_type="REPORT_PDF",
        filename="report_v1_draft.pdf",
        media_type="application/pdf",
        size_bytes=12,
        sha256="a" * 64,
        storage_uri="file:///tmp/siraloom-tests/report_v1_draft.pdf",
        genome_build="GRCh38",
        validation_status="VALID",
        metadata_json={"report_state": "DRAFT"},
    )
    report = Report(
        id=uuid4(),
        case_id=case.id,
        analysis_id=analysis.id,
        report_version=1,
        language="en",
        report_type="CLINICAL_INTERPRETATION",
        status="DRAFT",
        artifact_id=draft_artifact.id,
        content_json={
            "report_schema_version": "1.1.0",
            "report_version": 1,
            "report_status": "DRAFT",
            "final_result": {
                "status": "DRAFT",
                "release_state": "NOT_FOR_CLINICAL_RELEASE",
            },
        },
    )
    db.add_all([org, reviewer, case, analysis, variant, classification, decision, draft_artifact, report])
    db.commit()
    return db, reviewer, analysis, report


def test_report_is_not_eligible_until_reportability_is_final():
    db = make_db()
    org = Organization(id=uuid4(), name="Lab")
    user = User(id=uuid4(), organization_id=org.id, display_name="Reviewer", role="lab_director", status="ACTIVE")
    case = Case(id=uuid4(), organization_id=org.id, case_identifier="RPT-GATE", status="ACTIVE", clinical_context={}, language="en", created_by=user.id)
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        analysis_type="VARIANT_INTERPRETATION",
        workflow_id="variant-v1",
        workflow_version="2.1",
        status="SUCCEEDED",
        reference_build="GRCh38",
        configuration={},
        created_by=user.id,
    )
    variant = Variant(
        id=uuid4(),
        genome_build="GRCh38",
        chromosome="1",
        position=1,
        reference="A",
        alternate="G",
        normalization_status="NORMALIZED",
        canonical_key="GRCh38:1:1:A:G",
        identifiers={},
    )
    classification = Classification(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        framework_name="ACMG/AMP",
        framework_version="2015",
        result="VUS",
        criterion_ids=[],
        metadata_json={},
        state="FINAL",
        review_status="APPROVED",
        version=1,
        review_version=1,
        reviewed_by=user.id,
    )
    decision = ReportabilityDecision(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        classification_id=classification.id,
        version=1,
        policy_name="TEST_POLICY",
        policy_version="1.0",
        disposition="REPORT",
        priority_score=50,
        priority_band="REVIEW",
        reasons=[],
        status="PROPOSED",
        review_version=0,
    )
    db.add_all([org, user, case, analysis, variant, classification, decision])
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)

    assert eligible is False
    assert any("reportability is not FINAL" in error for error in errors)


def test_report_content_persists_exact_classification_identity():
    db, reviewer, analysis, report = seed_finalizable_report()

    content = build_report_content(
        db,
        analysis,
        "en",
        report_type="CLINICAL_INTERPRETATION",
    )

    assert len(content["findings"]) == 1
    finding = content["findings"][0]
    classification = db.scalar(
        select(Classification).where(
            Classification.analysis_id == analysis.id,
        )
    )
    assert finding["classification_id"] == str(classification.id)
    assert finding["classification_version"] == classification.version


def test_signout_creates_immutable_signed_artifact_and_provenance(monkeypatch):
    db, reviewer, analysis, report = seed_finalizable_report()
    from backend.app.reporting import finalization

    monkeypatch.setattr(finalization, "render_pdf", lambda content: b"%PDF-SIRALOOM-SIGNED%")

    finalized = finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Authorized laboratory sign-out",
    )
    db.commit()

    assert finalized.status == "FINAL"
    assert finalized.signed_artifact_id is not None
    assert finalized.signed_sha256
    assert finalized.signout_reason == "Authorized laboratory sign-out"
    assert finalized.content_json["report_status"] == "FINAL"
    assert finalized.content_json["final_result"]["release_state"] == "CLINICALLY_RELEASED"
    assert finalized.content_json["final_result"]["signed_out_by"] == str(reviewer.id)

    signed_artifact = db.get(__import__("backend.app.infrastructure.db.models", fromlist=["Artifact"]).Artifact, finalized.signed_artifact_id)
    assert signed_artifact is not None
    assert signed_artifact.sha256 == finalized.signed_sha256
    assert signed_artifact.metadata_json["signed"] is True

    signed_id = finalized.signed_artifact_id
    signed_sha = finalized.signed_sha256
    second = finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="A different reason must not mutate a signed report",
    )
    assert second.signed_artifact_id == signed_id
    assert second.signed_sha256 == signed_sha
    assert second.signout_reason == "Authorized laboratory sign-out"


def test_signed_report_requires_draft_artifact():
    db, reviewer, analysis, report = seed_finalizable_report()
    report.artifact_id = None
    db.commit()
    from backend.app.reporting.finalization import ReportFinalizationError

    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "immutable draft artifact" in str(exc)
    else:
        raise AssertionError("Sign-out must require an immutable draft artifact")
