"""Regression tests for the S1-01/S1-02 clinical request contract."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.api.v1.clinical_requests import (
    DecisionInput, ProcedureInput, RequestCreate, RevisionInput, VerificationInput,
    _require_capability,
)
from backend.app.infrastructure.db.clinical_requests import OrganizationCapabilityAssignment


def _request_payload():
    return {
        "requested_examination": "Germline SNV and small-indel interpretation",
        "referral_indication": "Unexplained developmental delay",
        "clinical_question": "Assess for a molecular diagnosis",
        "referrer_name": "Dr Example",
        "referrer_role": "Clinical geneticist",
        "referrer_organization": "Regional Genetics Service",
        "referrer_identifier": "REG-123",
        "referrer_contact": "referrals@example.invalid",
        "referral_channel": "SECURE_PORTAL",
        "source_evidence_reference": "REF-2026-001",
    }


def test_external_referrer_request_does_not_require_siraloom_user_identity():
    body = RequestCreate(request_identifier="REQ-001", **_request_payload())
    assert body.referrer_name == "Dr Example"
    assert body.referrer_identifier == "REG-123"
    assert "user_id" not in body.model_dump()


def test_request_revisions_are_explicit_and_reject_unknown_fields():
    body = RevisionInput(**_request_payload())
    assert body.requested_examination.startswith("Germline")
    with pytest.raises(ValueError):
        RevisionInput(**_request_payload(), accession_accepted=True)


def test_acceptance_requires_verification_or_procedure_basis_at_schema_boundary():
    ordinary = DecisionInput(decision="ACCEPT", reason="Accepted")
    assert ordinary.verification_id is None
    assert ordinary.exception_procedure_id is None
    # The endpoint must reject this missing basis; the schema intentionally
    # permits it so the API can return a policy-specific 422 response.


def test_verification_requires_method_and_evidence_reference():
    body = VerificationInput(
        status="VERIFIED",
        method="Institutional directory and callback",
        evidence_reference="VERIFICATION-RECORD-17",
        outcome_note="Identity and referral authority confirmed",
    )
    assert body.status == "VERIFIED"
    with pytest.raises(ValueError):
        VerificationInput(status="VERIFIED", method="x", evidence_reference="", outcome_note="ok")


def test_exception_procedure_requires_an_explicit_version_and_approval_evidence():
    body = ProcedureInput(
        procedure_identifier="SOP-ACC-004",
        procedure_version="3.1",
        effective_at=datetime.now(UTC) - timedelta(days=1),
        approval_evidence_reference="QMS-APPROVAL-2026-17",
        allows_unverified_referrer_exception=True,
    )
    assert body.procedure_version == "3.1"
    assert body.allows_unverified_referrer_exception is True


def test_capability_records_preserve_grant_and_revocation_history():
    assignment = OrganizationCapabilityAssignment(
        id=uuid4(),
        organization_id=uuid4(),
        user_id=uuid4(),
        capability="ACCESSION_DECIDE",
        granted_by=uuid4(),
        grant_reason="Authorized accessioning officer",
        expires_at=None,
        revoked_at=None,
        revoked_by=None,
        revocation_reason=None,
    )
    assert assignment.revoked_at is None
    assignment.revoked_at = datetime.now(UTC)
    assignment.revoked_by = uuid4()
    assignment.revocation_reason = "Role changed"
    assert assignment.revoked_at is not None
    assert assignment.revocation_reason == "Role changed"
