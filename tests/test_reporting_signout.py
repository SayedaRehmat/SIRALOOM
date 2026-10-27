from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import (
    ACMGAssessment,
    Analysis,
    AnalysisPartition,
    Annotation,
    Assay,
    Artifact,
    Case,
    Classification,
    ConfirmationRecord,
    Evidence,
    Organization,
    Report,
    ReportabilityDecision,
    QCAssessment,
    TechnicalQCObservation,
    SecondaryFindingDecision,
    User,
    Variant,
    WorkflowStep,
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
    assay = Assay(
        id=uuid4(), organization_id=org.id, name="Test Assay",
        version="1", assay_type="WGS", status="ACTIVE",
        configuration={"rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 20}]},
    )
    analysis = Analysis(
        id=uuid4(),
        case_id=case.id,
        assay_id=assay.id,
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
    db.add(AnalysisPartition(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize",
        partition_key="0:1", ordinal=0, record_start=0, record_end=1,
        variant_count=1, status="SUCCEEDED",
        metadata_json={
            "variant_ids": [str(variant.id)],
            "sample_calls": [{
                "variant_id": str(variant.id), "status": "AVAILABLE",
                "sample_name": "SAMPLE-1", "genotype": "0/1",
                "zygosity": "HETEROZYGOUS", "phase": "UNPHASED",
                "phase_set": None, "format_values": {"DP": "30", "GQ": "60"},
            }],
        },
    ))
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
    qc_observation = TechnicalQCObservation(
        id=uuid4(), analysis_id=analysis.id, metric_name="mean_depth",
        metric_value=40, status="AVAILABLE", source="LAB_QC",
        created_at=datetime.now(UTC),
    )
    qc = QCAssessment(
        id=uuid4(), analysis_id=analysis.id, assay_id=assay.id,
        status="PASS", profile_name=assay.name, profile_version=assay.version,
        metrics_json={"mean_depth": 40},
        evaluated_rules=[{"metric": "mean_depth", "value": 40, "status": "PASS", "direction": "MIN", "threshold": 20, "minimum": None, "maximum": None, "severity": "FAIL"}],
        observation_snapshot=[],
        gate_status="PASS", reviewed_by=str(reviewer.id),
        reviewed_at=datetime.now(UTC),
    )
    db.add_all([org, reviewer, case, assay, analysis, variant, classification, decision, draft_artifact, qc_observation, qc])
    db.flush()

    from backend.app.domain.quality_provenance import qc_observation_snapshot
    qc.observation_snapshot = qc_observation_snapshot(db, analysis, [qc_observation])
    db.flush()

    report_content = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    report = Report(
        id=uuid4(),
        case_id=case.id,
        analysis_id=analysis.id,
        report_version=1,
        language="en",
        report_type="CLINICAL_INTERPRETATION",
        status="DRAFT",
        artifact_id=draft_artifact.id,
        content_json=report_content,
    )
    db.add(report)
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


@pytest.mark.parametrize(
    ("qc_change", "expected_error"),
    [
        ("missing", "reviewed technical QC assessment"),
        ("failed", "requires a PASS technical QC assessment"),
        ("stale_profile", "does not match the current assay profile version"),
    ],
)
def test_clinical_report_eligibility_requires_current_passing_qc(qc_change, expected_error):
    db, _reviewer, analysis, _report = seed_finalizable_report()
    qc = db.scalar(select(QCAssessment).where(QCAssessment.analysis_id == analysis.id))
    if qc_change == "missing":
        db.delete(qc)
    elif qc_change == "failed":
        qc.status = "FAIL"
        qc.gate_status = "FAIL"
    else:
        assay = db.get(Assay, qc.assay_id)
        assay.version = "2"
    db.commit()

    eligible, errors = final_report_eligibility(
        db, analysis_id=analysis.id, report_type="CLINICAL_INTERPRETATION"
    )

    assert not eligible
    assert any(expected_error in error for error in errors)


@pytest.mark.parametrize(
    ("status", "required", "complete_provenance", "expected_eligible"),
    [
        ("COMPLETED", True, True, True),
        ("COMPLETED", True, False, False),
        ("WAIVED", True, True, True),
        ("WAIVED", True, False, False),
        ("NOT_REQUIRED", False, True, True),
        ("NOT_REQUIRED", False, False, False),
        ("PENDING", False, False, False),
    ],
)
def test_report_eligibility_requires_reviewed_confirmation_provenance(
    status, required, complete_provenance, expected_eligible
):
    db, reviewer, analysis, _report = seed_finalizable_report()
    variant_id = db.scalar(
        select(Classification.variant_id).where(Classification.analysis_id == analysis.id)
    )
    confirmation = ConfirmationRecord(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant_id,
        version=1,
        required=required,
        status=status,
        method="Sanger" if status == "COMPLETED" and complete_provenance else None,
        result="CONFIRMED" if status == "COMPLETED" and complete_provenance else None,
        laboratory="Test Lab" if status == "COMPLETED" and complete_provenance else None,
        accession="ACC-1" if status == "COMPLETED" and complete_provenance else None,
        performed_at=datetime.now(UTC) if status == "COMPLETED" and complete_provenance else None,
        reviewed_by=reviewer.id if complete_provenance else None,
        reviewed_at=datetime.now(UTC) if complete_provenance else None,
        notes=("Approved by the laboratory reviewer" if complete_provenance else None),
    )
    db.add(confirmation)
    db.commit()

    eligible, errors = final_report_eligibility(
        db, analysis_id=analysis.id, report_type="CLINICAL_INTERPRETATION"
    )

    assert eligible is expected_eligible, errors
    if not expected_eligible:
        assert any("confirmation" in error.lower() for error in errors)


def test_clinical_report_eligibility_rejects_changed_rules_without_version_change():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    assay = db.get(Assay, analysis.assay_id)
    assay.configuration = {"rules": [{"metric": "mean_depth", "direction": "MIN", "threshold": 50}]}
    db.commit()

    eligible, errors = final_report_eligibility(
        db, analysis_id=analysis.id, report_type="CLINICAL_INTERPRETATION"
    )

    assert not eligible
    assert any("does not match the current assay QC rules" in error for error in errors)


def test_analytical_report_does_not_require_clinical_qc_gate():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    qc = db.scalar(select(QCAssessment).where(QCAssessment.analysis_id == analysis.id))
    db.delete(qc)
    db.commit()

    eligible, errors = final_report_eligibility(
        db, analysis_id=analysis.id, report_type="ANALYTICAL"
    )

    assert eligible, errors


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


def test_report_preserves_and_renders_unresolved_transcript_selection():
    from backend.app.reporting.service import _html_document

    db, _reviewer, analysis, _report = seed_finalizable_report()
    variant = db.scalar(select(Variant).where(Variant.canonical_key == "GRCh38:17:1:A:G"))
    db.add(Annotation(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        provider_name="VEP",
        provider_version="115",
        payload={"normalized": {
            "gene": {"symbol": None},
            "transcript": None,
            "transcript_selection": {
                "status": "AMBIGUOUS_CANONICAL",
                "policy": "UNIQUE_MANE_SELECT_THEN_UNIQUE_CANONICAL",
                "selected_transcript_id": None,
            },
        }},
    ))
    db.commit()

    content = build_report_content(
        db, analysis, "en", report_type="CLINICAL_INTERPRETATION"
    )
    finding = content["findings"][0]
    rendered = _html_document(content)

    assert finding["transcript_selection"]["status"] == "AMBIGUOUS_CANONICAL"
    assert "Transcript selection:</strong> AMBIGUOUS_CANONICAL (-)" in rendered


def test_rendered_report_contains_persisted_qc_gate_and_observation_provenance():
    from backend.app.reporting.service import _html_document

    db, _reviewer, analysis, _report = seed_finalizable_report()
    content = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    rendered = _html_document(content)

    assert "Technical Quality Assessment" in rendered
    assert "mean_depth" in rendered
    assert "LAB_QC" in rendered
    assert "Evaluated QC rules" in rendered
    assert "QC observation provenance" in rendered


def test_report_contains_genotype_from_persisted_normalization_partition():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    content = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")

    assert content["findings"][0]["genotype"] == {
        "gt": "0/1",
        "zygosity": "HETEROZYGOUS",
        "phase": "UNPHASED",
        "phase_set": None,
    }


def test_signout_is_blocked_when_normalized_input_has_no_complete_genotype():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    partition = db.scalar(select(AnalysisPartition).where(
        AnalysisPartition.analysis_id == analysis.id,
        AnalysisPartition.step_id == "normalize",
    ))
    updated_metadata = dict(partition.metadata_json)
    updated_calls = [dict(call) for call in updated_metadata["sample_calls"]]
    updated_calls[0].update({
        "status": "MISSING_OR_PARTIAL",
        "genotype": "./.",
        "zygosity": "NO_CALL",
    })
    updated_metadata["sample_calls"] = updated_calls
    partition.metadata_json = updated_metadata
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    assert not eligible
    assert any("no complete sample genotype" in error for error in errors)


def test_signout_is_blocked_for_homozygous_reference_record():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    partition = db.scalar(select(AnalysisPartition).where(
        AnalysisPartition.analysis_id == analysis.id,
        AnalysisPartition.step_id == "normalize",
    ))
    updated_metadata = dict(partition.metadata_json)
    updated_calls = [dict(call) for call in updated_metadata["sample_calls"]]
    updated_calls[0].update({
        "genotype": "0/0",
        "zygosity": "HOMOZYGOUS_REFERENCE",
    })
    updated_metadata["sample_calls"] = updated_calls
    partition.metadata_json = updated_metadata
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    assert not eligible
    assert any("homozygous reference" in error for error in errors)


def test_signout_is_blocked_when_qc_changes_after_draft_generation():
    db, reviewer, analysis, report = seed_finalizable_report()
    qc = db.scalar(select(QCAssessment).where(QCAssessment.analysis_id == analysis.id))
    qc.status = "WARN"
    qc.gate_status = "WARN"
    db.commit()

    with pytest.raises(Exception, match="requires a PASS technical QC assessment"):
        finalize_report(
            db, report_id=report.id, approver_id=reviewer.id,
            reason="Attempt sign-out after QC changed",
        )


def test_signout_rejects_changed_passing_qc_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    qc = db.scalar(select(QCAssessment).where(QCAssessment.analysis_id == analysis.id))
    qc.reviewed_by = "different-reviewer"
    db.commit()

    with pytest.raises(Exception, match="Technical QC assessment changed after report draft generation"):
        finalize_report(
            db, report_id=report.id, approver_id=reviewer.id,
            reason="Attempt sign-out after QC snapshot changed",
        )


def test_clinical_qc_requires_reassessment_after_new_observation():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    db.add(TechnicalQCObservation(
        id=uuid4(), analysis_id=analysis.id, metric_name="mean_depth",
        metric_value=40, status="AVAILABLE", source="LAB_QC",
        created_at=datetime.now(UTC),
    ))
    db.commit()

    eligible, errors = final_report_eligibility(
        db, analysis_id=analysis.id, report_type="CLINICAL_INTERPRETATION"
    )

    assert not eligible
    assert any("observations changed after assessment" in error for error in errors)


@pytest.mark.parametrize(
    ("routing", "expected_count"),
    [
        ({
            "gvcf_reference_blocks": 2,
            "gvcf_unresolved_variant_records": 0,
            "structural_variant_records": 1,
        }, 3),
        ({"telomere_records": 1}, 1),
        ({"telomere_after_contig_records": 1}, 1),
    ],
)
def test_signout_rejects_reports_when_unsupported_routed_records_were_preserved_uninterpreted(
    routing, expected_count,
):
    db, reviewer, analysis, report = seed_finalizable_report()
    db.add(WorkflowStep(
        id=uuid4(), analysis_id=analysis.id, step_id="normalize", step_order=2,
        status="SUCCEEDED", attempt=1, input_artifacts=[], output_artifacts=[],
        metadata_json={"routing": routing},
    ))
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)

    assert not eligible
    assert any(
        f"{expected_count} preserved GVCF/SV/telomere record(s)" in error
        for error in errors
    )
    with pytest.raises(Exception, match="preserved GVCF/SV/telomere record"):
        finalize_report(
            db, report_id=report.id, approver_id=reviewer.id,
            reason="Attempt sign-out while a routed VCF record is unreviewed",
        )
    db.refresh(report)
    assert report.status == "DRAFT"


def test_report_generation_and_signout_eligibility_reject_classification_outside_manifest():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    partition = db.scalar(select(AnalysisPartition).where(
        AnalysisPartition.analysis_id == analysis.id,
        AnalysisPartition.step_id == "normalize",
    ))
    partition.metadata_json = {"variant_ids": [], "sample_calls": []}
    partition.variant_count = 0
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    assert not eligible
    assert any("absent from the analysis input" in error for error in errors)
    with pytest.raises(ValueError, match="absent from the analysis input"):
        build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")


def test_report_generation_and_signout_reject_reportable_secondary_variant_outside_manifest():
    db, _reviewer, analysis, _report = seed_finalizable_report()
    outside_variant = Variant(
        id=uuid4(), genome_build="GRCh38", chromosome="17", position=2,
        reference="C", alternate="T", normalization_status="NORMALIZED",
        canonical_key="GRCh38:17:2:C:T", identifiers={},
    )
    secondary = SecondaryFindingDecision(
        id=uuid4(), analysis_id=analysis.id, variant_id=outside_variant.id,
        version=1, policy_name="TEST_POLICY", policy_version="1.0",
        eligibility="ELIGIBLE", consent_status="DOCUMENTED",
        disposition="REPORT", status="FINAL", rationale="Approved fixture",
        gene_disease_context={}, reviewed_by=_reviewer.id,
    )
    db.add_all([outside_variant, secondary])
    db.commit()

    eligible, errors = final_report_eligibility(db, analysis_id=analysis.id)
    assert not eligible
    assert any("Secondary-finding decisions reference variants absent" in error for error in errors)
    with pytest.raises(ValueError, match="Secondary-finding decisions reference variants absent"):
        build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")



def test_signout_rejects_mutated_classification_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()

    classification = db.scalar(select(Classification).where(Classification.analysis_id == analysis.id))
    classification.result = "VUS"
    db.commit()

    from backend.app.reporting.finalization import ReportFinalizationError
    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "ACMG classification" in str(exc)
    else:
        raise AssertionError("Sign-out must reject a mutated classification snapshot")




def test_signout_rejects_mutated_acmg_evidence_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    variant = db.scalar(select(Variant).where(Variant.canonical_key == "GRCh38:17:1:A:G"))
    classification = db.scalar(select(Classification).where(Classification.analysis_id == analysis.id))
    evidence = Evidence(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        evidence_type="POPULATION",
        statement="Rare in population",
        direction="SUPPORTS",
        source_name="test",
        source_version="1",
        evidence_fingerprint="test-evidence-fingerprint",
        created_by_type="TEST",
        created_by_id="test",
        payload={"af": 0.0001},
    )
    db.add(evidence)
    db.flush()
    assessment = db.scalar(select(ACMGAssessment).where(ACMGAssessment.analysis_id == analysis.id))
    if assessment is None:
        assessment = ACMGAssessment(
            id=uuid4(),
            analysis_id=analysis.id,
            variant_id=variant.id,
            framework_name="ACMG/AMP",
            framework_version="2015",
            criterion="PM2",
            state="PROPOSED",
            automated_assessment={"evidence_ids": [str(evidence.id)]},
            review_version=1,
        )
        db.add(assessment)
    else:
        assessment.automated_assessment = {**(assessment.automated_assessment or {}), "evidence_ids": [str(evidence.id)]}
    classification.criterion_ids = [str(assessment.id)]
    db.commit()

    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()
    evidence.statement = "Changed after draft generation"
    db.commit()

    from backend.app.reporting.finalization import ReportFinalizationError
    with pytest.raises(ReportFinalizationError, match="evidence .* changed"):
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")

def test_signout_rejects_mutated_classification_metadata_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()

    classification = db.scalar(select(Classification).where(Classification.analysis_id == analysis.id))
    classification.metadata_json = {"review_note": "changed after draft"}
    db.commit()

    from backend.app.reporting.finalization import ReportFinalizationError
    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "ACMG classification" in str(exc)
    else:
        raise AssertionError("Sign-out must reject mutated classification metadata")

def test_signout_rejects_mutated_acmg_assessment_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    variant = db.scalar(select(Variant).where(Variant.canonical_key == "GRCh38:17:1:A:G"))
    classification = db.scalar(select(Classification).where(Classification.analysis_id == analysis.id))
    assessment = __import__("backend.app.infrastructure.db.models", fromlist=["ACMGAssessment"]).ACMGAssessment(
        id=uuid4(),
        variant_id=variant.id,
        analysis_id=analysis.id,
        framework_name="ACMG/AMP",
        framework_version="2015",
        specification_provider="SIRALOOM",
        specification_id="ACMG_2015",
        specification_version="1.0",
        criterion="PM2",
        automated_assessment={"strength": "MODERATE", "direction": "BENIGN", "evidence_ids": []},
        state="PROPOSED",
        review_version=1,
    )
    db.add(assessment)
    classification.criterion_ids = [str(assessment.id)]
    db.commit()

    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()

    assessment.reviewed_assessment = {
        "decision": "ACCEPT",
        "strength": "MODERATE",
        "reason": "Reviewed after draft generation",
    }
    assessment.review_version = 2
    db.commit()

    from backend.app.reporting.finalization import ReportFinalizationError
    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "ACMG assessment" in str(exc)
    else:
        raise AssertionError("Sign-out must reject a mutated ACMG assessment snapshot")

def test_signout_rejects_stale_secondary_finding_snapshot():
    db, reviewer, analysis, report = seed_finalizable_report()
    variant = db.scalar(select(Variant).where(Variant.canonical_key == "GRCh38:17:1:A:G"))
    decision = SecondaryFindingDecision(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        version=1,
        policy_name="ACMG_SF",
        policy_version="3.3.2",
        eligibility="ELIGIBLE",
        consent_status="CONSENTED",
        disposition="REPORT",
        status="FINAL",
        rationale="Initial secondary finding decision",
        gene_disease_context={},
    )
    db.add(decision)
    db.commit()

    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()

    replacement = SecondaryFindingDecision(
        id=uuid4(),
        analysis_id=analysis.id,
        variant_id=variant.id,
        version=2,
        supersedes_decision_id=decision.id,
        policy_name="ACMG_SF",
        policy_version="3.3.2",
        eligibility="ELIGIBLE",
        consent_status="CONSENTED",
        disposition="REPORT",
        status="FINAL",
        rationale="Updated secondary finding decision",
        gene_disease_context={},
    )
    db.add(replacement)
    db.commit()

    from backend.app.reporting.finalization import ReportFinalizationError
    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "secondary finding" in str(exc)
    else:
        raise AssertionError("Sign-out must reject a stale secondary-finding snapshot")


def test_signout_rejects_new_secondary_reportable_decision_missing_from_draft():
    db, reviewer, analysis, report = seed_finalizable_report()
    report.content_json = build_report_content(db, analysis, "en", report_type="CLINICAL_INTERPRETATION")
    db.commit()
    variant = db.scalar(select(Variant).where(Variant.canonical_key == "GRCh38:17:1:A:G"))
    db.add(SecondaryFindingDecision(
        id=uuid4(), analysis_id=analysis.id, variant_id=variant.id, version=1,
        policy_name="ACMG_SF", policy_version="3.3.2", eligibility="ELIGIBLE",
        consent_status="CONSENTED", disposition="REPORT", status="FINAL",
        rationale="Added after draft generation", gene_disease_context={},
    ))
    db.commit()
    from backend.app.reporting.finalization import ReportFinalizationError
    try:
        finalize_report(db, report_id=report.id, approver_id=reviewer.id, reason="Sign out")
    except ReportFinalizationError as exc:
        assert "secondary-finding set" in str(exc)
    else:
        raise AssertionError("Sign-out must reject a newly reportable secondary finding absent from the draft")


def test_signout_creates_immutable_signed_artifact_and_provenance(monkeypatch):
    db, reviewer, analysis, report = seed_finalizable_report()
    from backend.app.reporting import finalization

    reviewer.display_name = "Sign-out <Reviewer>"
    report.content_json = build_report_content(
        db, analysis, "en", report_type="CLINICAL_INTERPRETATION"
    )
    db.commit()
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
    assert finalized.content_json["final_result"]["release_state"] == "AUTHORIZED_SIGNOUT"
    assert finalized.content_json["final_result"]["clinical_use_status"] == "LABORATORY_VALIDATION_REQUIRED"
    assert finalized.content_json["final_result"]["signed_out_by"] == str(reviewer.id)
    assert finalized.content_json["final_result"]["signed_out_by_display_name"] == "Sign-out <Reviewer>"
    signed_out_at = datetime.fromisoformat(finalized.content_json["final_result"]["signed_out_at"])
    approved_at = finalized.approved_at
    if approved_at.tzinfo is None:
        approved_at = approved_at.replace(tzinfo=UTC)
    assert signed_out_at == approved_at
    from backend.app.reporting.service import render_html

    signed_html = render_html(finalized.content_json).decode("utf-8")
    assert "Authorized sign-out is recorded." in signed_html
    assert "Authorized signatory:</strong> Sign-out &lt;Reviewer&gt;" in signed_html
    assert "Authorized signatory:</strong> Sign-out <Reviewer>" not in signed_html
    assert f"Report issued:</strong> {finalized.content_json['final_result']['signed_out_at']}" in signed_html
    assert "Clinical use remains subject to laboratory-specific validation" in signed_html
    assert "not a clinical release until an authorized sign-out is recorded" not in signed_html

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
    reviewer.status = "SUSPENDED"
    db.commit()
    replay = finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Retry of already completed sign-out",
    )
    assert replay.signed_artifact_id == signed_id


def test_signout_requires_active_signatory_bound_to_report_organization():
    from backend.app.reporting.finalization import ReportFinalizationError

    db, reviewer, _analysis, report = seed_finalizable_report()
    reviewer.status = "SUSPENDED"
    db.commit()

    with pytest.raises(ReportFinalizationError, match="active, organization-bound signatory"):
        finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Attempted by suspended user",
        )

    db.refresh(report)
    assert report.status == "DRAFT"
    assert report.signed_artifact_id is None
    db.close()


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
