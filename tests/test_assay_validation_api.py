from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.v1.quality import (
    AssayValidationDecisionInput,
    AssayValidationSubmissionInput,
    decide_assay_validation,
    submit_assay_validation,
)
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.assay_validation import AssayValidationDecision, AssayValidationSubmission
from backend.app.infrastructure.db.models import Assay, Organization, User


def _payload(result="PASS"):
    return {
        "validation_type": "VALIDATION",
        "protocol_identifier": "SOP-NGS-01",
        "protocol_version": "1.0",
        "intended_use": "Clinical germline SNV and small-indel interpretation",
        "specimen_types": ["BLOOD"],
        "variant_classes": ["SNV", "SMALL_INDEL"],
        "reference_builds": ["GRCh38"],
        "workflow_id": "variant-v1",
        "workflow_version": "2.1",
        "pipeline_components": [
            {"name": "bcftools", "version": "1.25", "sha256": "a" * 64},
            {"name": "htslib", "version": "1.25", "sha256": "b" * 64},
            {"name": "native_toolchain_lock", "version": "bcftools-1.25-htslib-1.25-linux-64", "sha256": "c" * 64},
            {"name": "python_dependency_lock", "version": "uv.lock", "sha256": "d" * 64},
            {"name": "siraloom_variant_workflow", "version": "2.1", "sha256": "e" * 64},
            {"name": "container_image", "version": "sha256:" + "f" * 64, "sha256": "f" * 64},
        ],
        "performance_specifications": [
            {"metric": "analytical_sensitivity", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": result},
            {"metric": "analytical_sensitivity", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
            {"metric": "positive_predictive_value", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": "PASS"},
            {"metric": "positive_predictive_value", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
        ],
        "study_design_summary": "Representative positive and negative samples.",
        "sample_count": 50,
        "evidence_manifest": [{"evidence_type": "VALIDATION_REPORT", "reference": "controlled://validation/report-01"}],
    }


def _principal(user_id, organization_id, role):
    return Principal(user_id=user_id, organization_id=organization_id, role=role, subject=str(user_id))


def test_validation_submission_requires_independent_lab_director_approval_and_explicit_expiry():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, submitter_id, approver_id, assay_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.add(Organization(id=organization_id, name="API Validation Lab", external_identifier=str(organization_id)))
            db.flush()
            db.add_all([
                User(id=submitter_id, organization_id=organization_id, external_subject=str(submitter_id),
                     email="submitter@test.invalid", display_name="Submitter", role="ORGANIZATION_ADMIN", status="ACTIVE"),
                User(id=approver_id, organization_id=organization_id, external_subject=str(approver_id),
                     email="approver@test.invalid", display_name="Approver", role="LAB_DIRECTOR", status="ACTIVE"),
            ])
            assay = Assay(id=assay_id, organization_id=organization_id, name="Germline NGS", version="1.0",
                          assay_type="GERMLINE", configuration={"rules": [{"metric": "coverage", "direction": "MIN", "threshold": 20}]},
                          status="ACTIVE")
            db.add(assay)
            db.commit()

            submitted = submit_assay_validation(
                assay_id, AssayValidationSubmissionInput(**_payload()), db,
                _principal(submitter_id, organization_id, "organization_admin"),
            )
            submission_id = UUID(submitted["id"])
            submission = db.get(AssayValidationSubmission, submission_id)
            assert submission is not None
            assert submitted["latest_decision"] is None

            approval_time = datetime.now(timezone.utc)
            with pytest.raises(HTTPException, match="cannot approve their own"):
                decide_assay_validation(
                    submission_id,
                    AssayValidationDecisionInput(
                        decision="APPROVE", reason="Self approval is prohibited",
                        evidence_reference="controlled://approval/invalid",
                        effective_at=approval_time, expires_at=approval_time + timedelta(days=365),
                    ),
                    db,
                    _principal(submitter_id, organization_id, "lab_director"),
                )

            approved = decide_assay_validation(
                submission_id,
                AssayValidationDecisionInput(
                    decision="APPROVE", reason="Independent review passed",
                    evidence_reference="controlled://approval/valid",
                    effective_at=approval_time, expires_at=approval_time + timedelta(days=365),
                ),
                db,
                _principal(approver_id, organization_id, "lab_director"),
            )
            assert approved["decision"] == "APPROVE"
            assert db.query(AssayValidationDecision).filter_by(submission_id=submission_id).count() == 1
    finally:
        engine.dispose()


def test_validation_with_failed_performance_criterion_cannot_be_approved():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, submitter_id, approver_id, assay_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.add(Organization(id=organization_id, name="Failed Validation Lab", external_identifier=str(organization_id)))
            db.flush()
            db.add_all([
                User(id=submitter_id, organization_id=organization_id, external_subject=str(submitter_id),
                     email="submitter2@test.invalid", display_name="Submitter", role="ORGANIZATION_ADMIN", status="ACTIVE"),
                User(id=approver_id, organization_id=organization_id, external_subject=str(approver_id),
                     email="approver2@test.invalid", display_name="Approver", role="LAB_DIRECTOR", status="ACTIVE"),
            ])
            db.add(Assay(id=assay_id, organization_id=organization_id, name="Germline NGS", version="1.0",
                         assay_type="GERMLINE", configuration={"rules": [{"metric": "coverage", "direction": "MIN", "threshold": 20}]},
                         status="ACTIVE"))
            db.commit()
            submitted = submit_assay_validation(
                assay_id, AssayValidationSubmissionInput(**_payload("FAIL")), db,
                _principal(submitter_id, organization_id, "organization_admin"),
            )
            submission_id = UUID(submitted["id"])
            now = datetime.now(timezone.utc)
            with pytest.raises(HTTPException, match="performance criterion"):
                decide_assay_validation(
                    submission_id,
                    AssayValidationDecisionInput(
                        decision="APPROVE", reason="Must not pass",
                        evidence_reference="controlled://approval/fail",
                        effective_at=now, expires_at=now + timedelta(days=365),
                    ),
                    db,
                    _principal(approver_id, organization_id, "lab_director"),
                )
    finally:
        engine.dispose()
