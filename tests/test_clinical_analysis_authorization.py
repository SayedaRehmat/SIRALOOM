from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.clinical_authorization import (
    ClinicalAuthorizationError,
    assert_analysis_clinical_authorization,
    authorize_analysis_request,
)
from backend.app.infrastructure.db.clinical_requests import (
    AccessionDecision,
    ClinicalRequest,
    ClinicalRequestRevision,
)


def _accepted_context():
    case_id, organization_id = uuid4(), uuid4()
    request_id, revision_id, decision_id = uuid4(), uuid4(), uuid4()
    case = SimpleNamespace(
        id=case_id,
        organization_id=organization_id,
        accession_reconciliation_status="NEW_WORKFLOW",
    )
    request = SimpleNamespace(
        id=request_id,
        case_id=case_id,
        organization_id=organization_id,
        request_identifier="REQ-001",
        status="ACCEPTED",
        current_revision_id=revision_id,
    )
    revision = SimpleNamespace(
        id=revision_id,
        request_id=request_id,
        fingerprint="a" * 64,
    )
    decision = SimpleNamespace(
        id=decision_id,
        decision="ACCEPT",
        created_at=datetime(2026, 11, 10, tzinfo=timezone.utc),
    )

    class FakeSession:
        def get(self, model, key):
            if model is ClinicalRequest and key == request_id:
                return request
            if model is ClinicalRequestRevision and key == revision_id:
                return revision
            return None

        def scalar(self, statement):
            return decision

    return FakeSession(), case, request, revision, decision


def test_clinical_analysis_requires_accepted_request_reference():
    db, case, *_ = _accepted_context()
    with pytest.raises(ClinicalAuthorizationError, match="requires clinical_request_id"):
        authorize_analysis_request(
            db,
            case=case,
            analysis_type="VARIANT_INTERPRETATION",
            configuration={},
            clinical_request_id=None,
        )


def test_clinical_analysis_captures_exact_accepted_request_revision_and_decision():
    db, case, request, revision, decision = _accepted_context()
    snapshot = authorize_analysis_request(
        db,
        case=case,
        analysis_type="VARIANT_INTERPRETATION",
        configuration={},
        clinical_request_id=request.id,
    )
    assert snapshot == {
        "mode": "CLINICAL",
        "clinical_request_id": str(request.id),
        "accepted_revision_id": str(revision.id),
        "accession_decision_id": str(decision.id),
        "request_identifier": "REQ-001",
        "revision_fingerprint": "a" * 64,
        "decision_created_at": decision.created_at.isoformat(),
    }


@pytest.mark.parametrize("status", ["DRAFT", "SUBMITTED", "NEEDS_INFORMATION", "REASSESSMENT_REQUIRED", "REJECTED", "CLOSED"])
def test_non_accepted_request_statuses_cannot_authorize_clinical_analysis(status):
    db, case, request, *_ = _accepted_context()
    request.status = status
    with pytest.raises(ClinicalAuthorizationError, match="must be ACCEPTED"):
        authorize_analysis_request(
            db,
            case=case,
            analysis_type="VARIANT_INTERPRETATION",
            configuration={},
            clinical_request_id=request.id,
        )


def test_legacy_unreconciled_case_cannot_authorize_clinical_analysis():
    db, case, request, *_ = _accepted_context()
    case.accession_reconciliation_status = "LEGACY_UNRECONCILED"
    with pytest.raises(ClinicalAuthorizationError, match="unreconciled"):
        authorize_analysis_request(
            db,
            case=case,
            analysis_type="VARIANT_INTERPRETATION",
            configuration={},
            clinical_request_id=request.id,
        )


def test_research_mode_requires_explicit_purpose_and_rationale():
    db, case, *_ = _accepted_context()
    with pytest.raises(ClinicalAuthorizationError, match="research_justification"):
        authorize_analysis_request(
            db,
            case=case,
            analysis_type="RESEARCH",
            configuration={"workflow_purpose": "RESEARCH"},
            clinical_request_id=None,
        )
    snapshot = authorize_analysis_request(
        db,
        case=case,
        analysis_type="RESEARCH",
        configuration={
            "workflow_purpose": "RESEARCH",
            "research_justification": "Non-clinical methods development",
        },
        clinical_request_id=None,
    )
    assert snapshot["mode"] == "RESEARCH_NON_CLINICAL"


def test_worker_gate_rejects_missing_or_changed_authorization_snapshot():
    db, case, request, revision, decision = _accepted_context()
    with pytest.raises(ClinicalAuthorizationError, match="no immutable"):
        assert_analysis_clinical_authorization(
            db,
            case=case,
            analysis_configuration={},
            analysis_type="VARIANT_INTERPRETATION",
        )

    snapshot = {
        "mode": "CLINICAL",
        "clinical_request_id": str(request.id),
        "accepted_revision_id": str(revision.id),
        "accession_decision_id": str(uuid4()),
        "revision_fingerprint": revision.fingerprint,
    }
    with pytest.raises(ClinicalAuthorizationError, match="acceptance changed"):
        assert_analysis_clinical_authorization(
            db,
            case=case,
            analysis_configuration={"clinical_authorization": snapshot},
            analysis_type="VARIANT_INTERPRETATION",
        )
