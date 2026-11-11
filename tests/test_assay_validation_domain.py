from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.domain.assay_validation import (
    AssayValidationError,
    authorize_assay_validation,
    normalize_validation_submission,
    validation_payload_sha256,
)
from backend.app.infrastructure.db.assay_validation import (
    AssayValidationDecision,
    AssayValidationSubmission,
)
from backend.app.infrastructure.db.base import Base
from backend.app.infrastructure.db.models import Assay, Organization, User


def _payload():
    return normalize_validation_submission({
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
            {"name": "SIRALOOM Variant workflow", "version": "2.1", "sha256": "a" * 64}
        ],
        "performance_specifications": [
            {"metric": "sensitivity", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": "PASS"},
            {"metric": "sensitivity", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
            {"metric": "positive_predictive_value", "variant_class": "SNV", "acceptance_criteria": ">=95%", "observed_result": "99%", "unit": "%", "result": "PASS"},
            {"metric": "positive_predictive_value", "variant_class": "SMALL_INDEL", "acceptance_criteria": ">=95%", "observed_result": "98%", "unit": "%", "result": "PASS"},
        ],
        "study_design_summary": "Representative positive and negative samples across the intended use.",
        "sample_count": 50,
        "evidence_manifest": [
            {"evidence_type": "VALIDATION_REPORT", "reference": "controlled://validation/report-01", "sha256": "b" * 64}
        ],
    })


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    organization_id, submitter_id, approver_id, assay_id = uuid4(), uuid4(), uuid4(), uuid4()
    with Session(engine) as db:
        organization = Organization(id=organization_id, name="Validation Lab", external_identifier=str(organization_id))
        db.add(organization)
        db.flush()
        db.add_all([
            User(id=submitter_id, organization_id=organization_id, external_subject=str(submitter_id),
                 email="submitter@example.test", display_name="Submitter", role="LAB_SCIENTIST", status="ACTIVE"),
            User(id=approver_id, organization_id=organization_id, external_subject=str(approver_id),
                 email="approver@example.test", display_name="Approver", role="LAB_DIRECTOR", status="ACTIVE"),
        ])
        assay = Assay(id=assay_id, organization_id=organization_id, name="Germline NGS",
                      version="1.0", assay_type="GERMLINE",
                      configuration={"rules": [{"metric": "coverage", "direction": "MIN", "threshold": 20}]},
                      status="ACTIVE")
        db.add(assay)
        db.commit()
    return engine, organization_id, submitter_id, approver_id, assay_id


def _submit_and_approve(db, organization_id, submitter_id, approver_id, assay_id, *, expiry_days=365):
    payload = _payload()
    submission = AssayValidationSubmission(
        id=uuid4(), organization_id=organization_id, assay_id=assay_id, revision=1,
        **payload, payload_sha256=validation_payload_sha256(payload), supersedes_id=None,
        submitted_by=submitter_id,
    )
    db.add(submission)
    db.flush()
    now = datetime.now(timezone.utc)
    decision = AssayValidationDecision(
        id=uuid4(), submission_id=submission.id, decision="APPROVE",
        reason="Independent review completed", evidence_reference="controlled://approval/01",
        effective_at=now - timedelta(days=2 if expiry_days < 0 else 1),
        expires_at=(now - timedelta(days=1)) if expiry_days < 0 else (now + timedelta(days=expiry_days)),
        actor_id=approver_id,
    )
    db.add(decision)
    db.commit()
    return submission, decision


def test_assay_validation_requires_evidence_and_variant_class_performance_coverage():
    payload = _payload()
    payload["evidence_manifest"] = []
    with pytest.raises(AssayValidationError, match="evidence_manifest"):
        normalize_validation_submission(payload)

    payload = _payload()
    payload["performance_specifications"] = [
        item for item in payload["performance_specifications"] if item["variant_class"] == "SNV"
    ]
    with pytest.raises(AssayValidationError, match="Each declared variant class"):
        normalize_validation_submission(payload)


def test_clinical_use_requires_current_approved_validation_and_exact_scope():
    engine, organization_id, submitter_id, approver_id, assay_id = _database()
    try:
        with Session(engine) as db:
            with pytest.raises(AssayValidationError, match="currently effective"):
                authorize_assay_validation(
                    db, assay_id=assay_id, organization_id=organization_id,
                    workflow_id="variant-v1", workflow_version="2.1",
                    reference_build="GRCh38", specimen_type="BLOOD",
                )
            _submit_and_approve(db, organization_id, submitter_id, approver_id, assay_id)
            snapshot = authorize_assay_validation(
                db, assay_id=assay_id, organization_id=organization_id,
                workflow_id="variant-v1", workflow_version="2.1",
                reference_build="GRCh38", specimen_type="BLOOD",
            )
            assert snapshot["protocol_identifier"] == "SOP-NGS-01"
            with pytest.raises(AssayValidationError, match="workflow and version"):
                authorize_assay_validation(
                    db, assay_id=assay_id, organization_id=organization_id,
                    workflow_id="variant-v1", workflow_version="2.2",
                    reference_build="GRCh38", specimen_type="BLOOD",
                )
            with pytest.raises(AssayValidationError, match="reference build"):
                authorize_assay_validation(
                    db, assay_id=assay_id, organization_id=organization_id,
                    workflow_id="variant-v1", workflow_version="2.1",
                    reference_build="GRCh37", specimen_type="BLOOD",
                )
    finally:
        engine.dispose()


def test_expired_assay_validation_cannot_authorize_clinical_use():
    engine, organization_id, submitter_id, approver_id, assay_id = _database()
    try:
        with Session(engine) as db:
            _submit_and_approve(db, organization_id, submitter_id, approver_id, assay_id, expiry_days=-1)
            with pytest.raises(AssayValidationError, match="currently effective"):
                authorize_assay_validation(
                    db, assay_id=assay_id, organization_id=organization_id,
                    workflow_id="variant-v1", workflow_version="2.1",
                    reference_build="GRCh38", specimen_type="BLOOD",
                )
    finally:
        engine.dispose()
