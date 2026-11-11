import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.variant_eligibility import evaluate_small_variant_eligibility
from backend.app.domain.clinical_authorization import (
    ClinicalAuthorizationError,
    assert_analysis_clinical_authorization,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.assay_validation import AssayValidationDecision, AssayValidationSubmission
from backend.app.domain.assay_validation import authorize_assay_validation, normalize_validation_submission, validation_payload_sha256
from backend.app.infrastructure.db.clinical_requests import (
    AccessionDecision,
    ClinicalRequest,
    ClinicalRequestRevision,
    ReferrerVerification,
)
from backend.app.infrastructure.db.models import Artifact, Assay, Case, Organization, Specimen, User


def _clinical_fixture():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, user_id, case_id = uuid4(), uuid4(), uuid4()
    specimen_id, artifact_id = uuid4(), uuid4()
    request_id, revision_id, verification_id, decision_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )
    with Session(engine, expire_on_commit=False) as db:
        organization = Organization(
            id=organization_id,
            name="Eligibility Test Lab",
            external_identifier=str(organization_id),
        )
        db.add(organization)
        db.flush()
        user = User(
            id=user_id,
            organization_id=organization_id,
            external_subject=str(user_id),
            email=f"{user_id}@example.test",
            display_name="Eligibility Test",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        )
        db.add(user)
        db.flush()
        assay_configuration = {
            "rules": [
                {"metric": "coverage", "direction": "MIN", "threshold": 20, "severity": "FAIL"}
            ]
        }
        assay = Assay(
            id=uuid4(),
            organization_id=organization_id,
            name="Clinical Germline Assay",
            version="1.0",
            assay_type="GERMLINE",
            configuration=assay_configuration,
            status="ACTIVE",
        )
        db.add(assay)
        db.flush()
        case = Case(
            id=case_id,
            organization_id=organization_id,
            case_identifier=f"ELIG-{case_id}",
            status="OPEN",
            accession_reconciliation_status="NEW_WORKFLOW",
            clinical_context={},
            language="en",
            created_by=user_id,
        )
        db.add(case)
        db.flush()
        specimen = Specimen(
            id=specimen_id,
            case_id=case_id,
            specimen_identifier="SPEC-001",
            specimen_type="BLOOD",
            metadata_json={"vcf_sample_name": "SAMPLE-01"},
        )
        db.add(specimen)
        db.flush()
        validation = {
            "sample_names": ["SAMPLE-01"],
            "source_record_count": 12,
            "parsed_variant_record_count": 12,
            "symbolic_source_record_count": 0,
            "breakend_source_record_count": 0,
            "gvcf_marker_count": 0,
            "telomere_record_count": 0,
            "unresolved_spanning_deletion_record_count": 0,
        }
        artifact = Artifact(
            id=artifact_id,
            analysis_id=None,
            case_id=case_id,
            artifact_type="VCF",
            filename="input.vcf",
            media_type="text/vcf",
            size_bytes=100,
            sha256="a" * 64,
            storage_uri="file:///tmp/input.vcf",
            genome_build="GRCh38",
            specimen_id=specimen_id,
            validation_status="VALID",
            metadata_json={"validation": validation},
        )
        db.add(artifact)
        db.flush()
        request = ClinicalRequest(
            id=request_id,
            case_id=case_id,
            organization_id=organization_id,
            request_identifier="REQ-ELIG-001",
            status="ACCEPTED",
            current_revision_id=revision_id,
            created_by=user_id,
        )
        revision = ClinicalRequestRevision(
            id=revision_id,
            request_id=request_id,
            version=1,
            schema_version=1,
            fingerprint="f" * 64,
            payload={"requested_examination": "SNV and small-indel interpretation"},
            created_by=user_id,
        )
        verification = ReferrerVerification(
            id=verification_id,
            request_id=request_id,
            revision_id=revision_id,
            status="VERIFIED",
            method="Controlled callback",
            evidence_reference="VERIFY-ELIG-001",
            outcome_note="Verified",
            verified_by=user_id,
        )
        db.add_all([request, revision, verification])
        db.flush()
        decision = AccessionDecision(
            id=decision_id,
            request_id=request_id,
            revision_id=revision_id,
            decision="ACCEPT",
            reason="Verified referral",
            actor_id=user_id,
            verification_id=verification_id,
            exception_procedure_id=None,
        )
        db.add(decision)
        approver_id = uuid4()
        db.add(User(
            id=approver_id,
            organization_id=organization_id,
            external_subject=str(approver_id),
            email=f"{approver_id}@example.test",
            display_name="Independent Assay Approver",
            role="LAB_DIRECTOR",
            status="ACTIVE",
        ))
        validation_payload = normalize_validation_submission({
            "validation_type": "VALIDATION",
            "protocol_identifier": "SOP-NGS-VALIDATION",
            "protocol_version": "1.0",
            "intended_use": "Clinical germline SNV and small-indel interpretation",
            "specimen_types": ["BLOOD"],
            "variant_classes": ["SNV", "SMALL_INDEL"],
            "reference_builds": ["GRCh38"],
            "workflow_id": "variant-v1",
            "workflow_version": "2.1",
            "pipeline_components": [{"name": "SIRALOOM Variant workflow", "version": "2.1", "sha256": "b" * 64}],
            "performance_specifications": [
                {"metric": "analytical_sensitivity", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": "PASS"},
                {"metric": "analytical_sensitivity", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
                {"metric": "positive_predictive_value", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": "PASS"},
                {"metric": "positive_predictive_value", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
            ],
            "study_design_summary": "Representative positive and negative specimens assessed across the declared intended-use scope.",
            "sample_count": 50,
            "evidence_manifest": [{"evidence_type": "VALIDATION_REPORT", "reference": "controlled://validation/report-001", "sha256": "c" * 64}],
        })
        submission = AssayValidationSubmission(
            id=uuid4(), organization_id=organization_id, assay_id=assay.id, revision=1,
            **validation_payload, payload_sha256=validation_payload_sha256(validation_payload),
            supersedes_id=None, submitted_by=user_id,
        )
        db.add(submission)
        db.flush()
        db.add(AssayValidationDecision(
            id=uuid4(), submission_id=submission.id, decision="APPROVE",
            reason="Independent validation review passed",
            evidence_reference="controlled://validation/approval-001",
            effective_at=datetime.now(timezone.utc) - timedelta(days=1),
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
            actor_id=approver_id,
        ))
        db.commit()
    with Session(engine) as db:
        validation_snapshot = authorize_assay_validation(
            db, assay_id=assay.id, organization_id=organization_id,
            workflow_id="variant-v1", workflow_version="2.1",
            reference_build="GRCh38", specimen_type="BLOOD",
        )
    workflow_eligibility = evaluate_small_variant_eligibility(validation)
    workflow_eligibility["validation_artifact_sha256"] = "a" * 64
    assay_snapshot = {
        "assay_id": str(assay.id),
        "name": assay.name,
        "version": assay.version,
        "assay_type": assay.assay_type,
        "configuration": assay_configuration,
        "configuration_sha256": hashlib.sha256(
            json.dumps(assay_configuration, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    assay_snapshot_sha256 = hashlib.sha256(
        json.dumps(assay_snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    configuration = {
        "clinical_authorization": {
            "mode": "CLINICAL",
            "clinical_request_id": str(request_id),
            "accepted_revision_id": str(revision_id),
            "accession_decision_id": str(decision_id),
            "request_identifier": "REQ-ELIG-001",
            "revision_fingerprint": "f" * 64,
        },
        "input_artifact_id": str(artifact_id),
        "specimen_id": str(specimen_id),
        "vcf_sample_name": "SAMPLE-01",
        "workflow_eligibility": workflow_eligibility,
        "assay_id": str(assay.id),
        "assay_snapshot": assay_snapshot,
        "assay_snapshot_sha256": assay_snapshot_sha256,
        "assay_validation_snapshot": validation_snapshot,
    }
    return engine, case_id, artifact_id, specimen_id, assay.id, configuration


def test_clinical_worker_gate_accepts_current_request_and_eligible_vcf():
    engine, case_id, _artifact_id, _specimen_id, assay_id, configuration = _clinical_fixture()
    try:
        with Session(engine) as db:
            case = db.get(Case, case_id)
            assert_analysis_clinical_authorization(
                db,
                case=case,
                analysis_configuration=configuration,
                analysis_type="VARIANT_INTERPRETATION",

                analysis_assay_id=assay_id,
                analysis_workflow_id="variant-v1",
                analysis_workflow_version="2.1",
                analysis_reference_build="GRCh38",
            )
    finally:
        engine.dispose()


def test_clinical_worker_gate_blocks_structural_vcf_even_if_snapshot_claims_eligible():
    engine, case_id, artifact_id, _specimen_id, assay_id, configuration = _clinical_fixture()
    try:
        with Session(engine) as db:
            artifact = db.get(Artifact, artifact_id)
            validation = dict(artifact.metadata_json["validation"])
            validation["symbolic_source_record_count"] = 1
            artifact.metadata_json = {"validation": validation}
            db.commit()
        with Session(engine) as db:
            case = db.get(Case, case_id)
            with pytest.raises(ClinicalAuthorizationError, match="outside the SNV/small-indel"):
                assert_analysis_clinical_authorization(
                    db,
                    case=case,
                    analysis_configuration=configuration,
                    analysis_type="VARIANT_INTERPRETATION",

                    analysis_assay_id=assay_id,
                )
    finally:
        engine.dispose()


def test_clinical_worker_gate_blocks_changed_specimen_sample_mapping():
    engine, case_id, _artifact_id, specimen_id, assay_id, configuration = _clinical_fixture()
    try:
        with Session(engine) as db:
            specimen = db.get(Specimen, specimen_id)
            specimen.metadata_json = {"vcf_sample_name": "OTHER-SAMPLE"}
            db.commit()
        with Session(engine) as db:
            case = db.get(Case, case_id)
            with pytest.raises(ClinicalAuthorizationError, match="sample mapping changed"):
                assert_analysis_clinical_authorization(
                    db,
                    case=case,
                    analysis_configuration=configuration,
                    analysis_type="VARIANT_INTERPRETATION",

                    analysis_assay_id=assay_id,
                )
    finally:
        engine.dispose()

def test_clinical_worker_gate_blocks_assay_configuration_mutation():
    engine, case_id, _artifact_id, _specimen_id, assay_id, configuration = _clinical_fixture()
    try:
        with Session(engine) as db:
            assay = db.get(Assay, assay_id)
            assay.configuration = {
                "rules": [
                    {"metric": "coverage", "direction": "MIN", "threshold": 30, "severity": "FAIL"}
                ]
            }
            db.commit()
        with Session(engine) as db:
            case = db.get(Case, case_id)
            with pytest.raises(ClinicalAuthorizationError, match="assay identity or QC configuration changed"):
                assert_analysis_clinical_authorization(
                    db,
                    case=case,
                    analysis_configuration=configuration,
                    analysis_type="VARIANT_INTERPRETATION",
                    analysis_assay_id=assay_id,
                )
    finally:
        engine.dispose()


def test_clinical_worker_gate_requires_persisted_assay_foreign_key():
    engine, case_id, _artifact_id, _specimen_id, _assay_id, configuration = _clinical_fixture()
    try:
        with Session(engine) as db:
            case = db.get(Case, case_id)
            with pytest.raises(ClinicalAuthorizationError, match="assay_id does not match"):
                assert_analysis_clinical_authorization(
                    db,
                    case=case,
                    analysis_configuration=configuration,
                    analysis_type="VARIANT_INTERPRETATION",
                    analysis_assay_id=None,
                )
    finally:
        engine.dispose()
