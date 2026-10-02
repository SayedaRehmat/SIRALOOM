"""Persistence for immutable workflow outcome decisions."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.app.domain.workflow_decision import (
    OutcomeKind,
    WorkflowDecision,
)
from backend.app.infrastructure.db.models import WorkflowDecisionRecord


def record_workflow_decision(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    attempt: int,
    outcome: OutcomeKind | str,
    decision: WorkflowDecision,
    resource_id: UUID | None = None,
    fallback_resource_id: UUID | None = None,
    metadata: dict | None = None,
) -> WorkflowDecisionRecord:
    """Append one immutable decision record before the owning workflow acts on it."""
    outcome_value = outcome.value if isinstance(outcome, OutcomeKind) else str(outcome)
    record = WorkflowDecisionRecord(
        id=uuid4(),
        analysis_id=analysis_id,
        step_id=step_id,
        attempt=max(0, int(attempt)),
        outcome_kind=outcome_value,
        action=decision.action.value,
        code=decision.code,
        message=decision.message,
        retryable=decision.retryable,
        fallback_allowed=decision.fallback_allowed,
        lab_action_required=decision.lab_action_required,
        resource_id=resource_id,
        fallback_resource_id=fallback_resource_id,
        metadata_json=dict(metadata or {}),
    )
    db.add(record)
    db.flush()
    return record
