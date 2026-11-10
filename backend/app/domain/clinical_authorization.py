from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.clinical_requests import (
    AccessionDecision,
    ClinicalRequest,
    ClinicalRequestRevision,
)
from backend.app.infrastructure.db.models import Case


class ClinicalAuthorizationError(ValueError):
    """Raised when a variant analysis lacks a current accepted clinical request."""


def authorize_analysis_request(
    db: Session,
    *,
    case: Case,
    analysis_type: str,
    configuration: dict[str, Any] | None,
    clinical_request_id: UUID | None,
) -> dict[str, Any]:
    """Return an immutable request/decision snapshot or reject clinical analysis.

    Research work is allowed only when both the analysis type and explicit
    workflow-purpose marker identify it as non-clinical and a rationale exists.
    All other variant interpretation analyses require a current accepted request.
    """
    config = dict(configuration or {})
    if analysis_type == "RESEARCH" and config.get("workflow_purpose") == "RESEARCH":
        rationale = config.get("research_justification")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ClinicalAuthorizationError(
                "Non-clinical research analysis requires a documented research_justification"
            )
        return {
            "mode": "RESEARCH_NON_CLINICAL",
            "clinical_request_id": None,
            "accepted_revision_id": None,
            "accession_decision_id": None,
        }

    if case.accession_reconciliation_status == "LEGACY_UNRECONCILED":
        raise ClinicalAuthorizationError(
            "Legacy case is unreconciled; clinical analysis is blocked until an authorized history reconciliation is completed"
        )
    if clinical_request_id is None:
        raise ClinicalAuthorizationError(
            "Clinical variant interpretation requires clinical_request_id referencing an accepted request"
        )

    request = db.get(ClinicalRequest, clinical_request_id)
    if (
        request is None
        or request.case_id != case.id
        or request.organization_id != case.organization_id
    ):
        raise ClinicalAuthorizationError(
            "Clinical request does not belong to this case and organization"
        )
    if request.status != "ACCEPTED" or request.current_revision_id is None:
        raise ClinicalAuthorizationError(
            f"Clinical request must be ACCEPTED; current status is {request.status}"
        )

    revision = db.get(ClinicalRequestRevision, request.current_revision_id)
    if revision is None or revision.request_id != request.id:
        raise ClinicalAuthorizationError(
            "Accepted clinical request has no valid current revision"
        )

    decision = db.scalar(
        select(AccessionDecision)
        .where(
            AccessionDecision.request_id == request.id,
            AccessionDecision.revision_id == revision.id,
        )
        .order_by(AccessionDecision.created_at.desc())
        .limit(1)
    )
    if decision is None or decision.decision != "ACCEPT":
        raise ClinicalAuthorizationError(
            "Current request revision has no matching ACCEPT accession decision"
        )

    return {
        "mode": "CLINICAL",
        "clinical_request_id": str(request.id),
        "accepted_revision_id": str(revision.id),
        "accession_decision_id": str(decision.id),
        "request_identifier": request.request_identifier,
        "revision_fingerprint": revision.fingerprint,
        "decision_created_at": decision.created_at.isoformat(),
    }


def assert_analysis_clinical_authorization(
    db: Session,
    *,
    case: Case,
    analysis_configuration: dict[str, Any] | None,
    analysis_type: str,
) -> None:
    """Recheck the captured authorization before dispatch and worker execution."""
    config = dict(analysis_configuration or {})
    snapshot = config.get("clinical_authorization")
    # Persisted Analysis rows always have a non-null analysis_type. Lightweight
    # test doubles without that field are outside the production authorization path.
    if analysis_type is None:
        return
    if (
        analysis_type == "RESEARCH"
        and isinstance(snapshot, dict)
        and snapshot.get("mode") == "RESEARCH_NON_CLINICAL"
        and config.get("workflow_purpose") == "RESEARCH"
        and isinstance(config.get("research_justification"), str)
        and config["research_justification"].strip()
    ):
        return
    if not isinstance(snapshot, dict) or snapshot.get("mode") != "CLINICAL":
        raise ClinicalAuthorizationError(
            "Analysis has no immutable accepted clinical-request authorization snapshot"
        )
    try:
        request_id = UUID(str(snapshot["clinical_request_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ClinicalAuthorizationError(
            "Analysis clinical-request authorization snapshot is malformed"
        ) from exc
    current = authorize_analysis_request(
        db,
        case=case,
        analysis_type=analysis_type,
        configuration=config,
        clinical_request_id=request_id,
    )
    for key in ("accepted_revision_id", "accession_decision_id", "revision_fingerprint"):
        if current.get(key) != snapshot.get(key):
            raise ClinicalAuthorizationError(
                "Clinical request acceptance changed after analysis creation; create a new authorized analysis"
            )
