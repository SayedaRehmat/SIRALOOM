from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    Notification,
    OrganizationMembership,
    ReanalysisCandidate,
    ReanalysisChangeEvent,
)


_CASE_TRIGGER_STEPS = {
    "PHENOTYPE_UPDATE": "build_evidence",
    "CLINICAL_CONTEXT_UPDATE": "build_evidence",
}


def create_case_change_candidates(
    db: Session,
    *,
    case: Case,
    trigger_type: str,
    reason: str,
    metadata: dict | None = None,
) -> list[ReanalysisCandidate]:
    """Create durable reanalysis candidates for completed analyses affected by a case change.

    The event/candidate pair is idempotent for the exact case change. The helper
    deliberately does not enqueue a child analysis: the laboratory must review
    and explicitly execute the candidate through the reanalysis workflow.
    """
    trigger_type = trigger_type.upper()
    earliest_step = _CASE_TRIGGER_STEPS.get(trigger_type)
    if earliest_step is None:
        raise ValueError(f"Unsupported case-change trigger: {trigger_type}")

    parents = db.scalars(
        select(Analysis).where(
            Analysis.case_id == case.id,
            Analysis.status == "SUCCEEDED",
        ).order_by(Analysis.created_at.desc())
    ).all()
    if not parents:
        return []

    payload = metadata or {}
    material = json.dumps(
        {
            "organization_id": str(case.organization_id),
            "case_id": str(case.id),
            "trigger_type": trigger_type,
            "reason": reason,
            "metadata": payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()

    event = db.scalar(
        select(ReanalysisChangeEvent).where(
            ReanalysisChangeEvent.change_fingerprint == fingerprint
        )
    )
    if event is None:
        event = ReanalysisChangeEvent(
            id=uuid4(),
            change_fingerprint=fingerprint,
            organization_id=case.organization_id,
            resource_id=None,
            trigger_type=trigger_type,
            resource_kind="CASE",
            resource_name=str(case.id),
            previous_version=None,
            new_version=None,
            previous_checksum=None,
            new_checksum=None,
            metadata_json={
                "case_id": str(case.id),
                "case_identifier": case.case_identifier,
                **payload,
            },
        )
        try:
            with db.begin_nested():
                db.add(event)
                db.flush()
        except IntegrityError:
            event = db.scalar(
                select(ReanalysisChangeEvent).where(
                    ReanalysisChangeEvent.change_fingerprint == fingerprint
                )
            )
            if event is None:
                raise

    candidates: list[ReanalysisCandidate] = []
    users = db.scalars(
        select(OrganizationMembership.user_id).where(
            OrganizationMembership.organization_id == case.organization_id,
            OrganizationMembership.status == "ACTIVE",
        )
    ).all()

    for parent in parents:
        candidate = db.scalar(
            select(ReanalysisCandidate).where(
                ReanalysisCandidate.parent_analysis_id == parent.id,
                ReanalysisCandidate.change_event_id == event.id,
            )
        )
        if candidate:
            candidates.append(candidate)
            continue

        candidate = ReanalysisCandidate(
            id=uuid4(),
            organization_id=case.organization_id,
            case_id=case.id,
            parent_analysis_id=parent.id,
            change_event_id=event.id,
            trigger_type=trigger_type,
            earliest_affected_step=earliest_step,
            reason=reason,
            status="PENDING",
        )
        created = False
        try:
            with db.begin_nested():
                db.add(candidate)
                db.flush()
            created = True
        except IntegrityError:
            candidate = db.scalar(
                select(ReanalysisCandidate).where(
                    ReanalysisCandidate.parent_analysis_id == parent.id,
                    ReanalysisCandidate.change_event_id == event.id,
                )
            )
            if candidate is None:
                raise

        if created:
            for user_id in users:
                db.add(Notification(
                    id=uuid4(),
                    organization_id=case.organization_id,
                    user_id=user_id,
                    notification_type="REANALYSIS_CANDIDATE",
                    status="UNREAD",
                    title="Case reanalysis may be required",
                    body=reason,
                    case_id=case.id,
                    analysis_id=parent.id,
                    candidate_id=candidate.id,
                    metadata_json={
                        "trigger_type": trigger_type,
                        "earliest_affected_step": earliest_step,
                        "change_event_id": str(event.id),
                        **payload,
                    },
                ))
        candidates.append(candidate)

    return candidates
