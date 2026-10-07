"""Durable human-gate transition contract for the laboratory workflow.

A workflow step that requires human action is a durable pause, not a terminal
failure. This module contains only the deterministic state transition policy;
persistence, authorization, audit, and queue publication remain in the
application/API layers.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from backend.app.domain.enums import StepStatus
from backend.app.domain.workflow_decision import WorkflowAction, WORKFLOW_STEP_IDS


class HumanGateDecision(StrEnum):
    """Decisions a reviewer can record against a durable workflow gate."""

    ACCEPT = "ACCEPT"
    OVERRIDE = "OVERRIDE"
    REQUEST_MORE_EVIDENCE = "REQUEST_MORE_EVIDENCE"
    REJECT_AND_RETRY = "REJECT_AND_RETRY"


@dataclass(frozen=True)
class HumanGateTransition:
    """Deterministic result of resolving one workflow human gate."""

    step_id: str
    decision: HumanGateDecision
    resulting_status: StepStatus
    workflow_action: WorkflowAction
    next_step: str
    requires_new_evidence: bool = False


def next_workflow_step(step_id: str) -> str | None:
    """Return the next canonical step, or ``None`` for the terminal step."""
    if step_id not in WORKFLOW_STEP_IDS:
        raise ValueError(f"Unknown workflow step: {step_id}")
    index = WORKFLOW_STEP_IDS.index(step_id)
    if index + 1 >= len(WORKFLOW_STEP_IDS):
        return None
    return WORKFLOW_STEP_IDS[index + 1]


def resolve_human_gate(
    step_id: str,
    decision: HumanGateDecision | str,
    *,
    current_status: StepStatus | str = StepStatus.REQUIRES_REVIEW,
) -> HumanGateTransition:
    """Resolve a human gate without losing the reason the gate existed.

    ``ACCEPT`` and ``OVERRIDE`` release the step to the canonical downstream
    step. ``REQUEST_MORE_EVIDENCE`` keeps the gate open; the worker must not
    rerun blindly. ``REJECT_AND_RETRY`` explicitly sends the same step back to
    the durable queue and is intended only when the reviewer has changed the
    inputs/context needed for a meaningful retry.
    """
    if step_id not in WORKFLOW_STEP_IDS:
        raise ValueError(f"Unknown workflow step: {step_id}")

    try:
        status = current_status if isinstance(current_status, StepStatus) else StepStatus(str(current_status).upper())
    except ValueError as exc:
        raise ValueError(f"Unknown workflow step status: {current_status}") from exc

    if status is not StepStatus.REQUIRES_REVIEW:
        raise ValueError(
            f"Workflow step {step_id!r} is not waiting for human review; current status is {status.value}."
        )

    try:
        gate_decision = decision if isinstance(decision, HumanGateDecision) else HumanGateDecision(str(decision).upper())
    except ValueError as exc:
        raise ValueError(f"Unknown human-gate decision: {decision}") from exc

    downstream = next_workflow_step(step_id)
    if downstream is None:
        downstream = "analysis_complete"

    if gate_decision in {HumanGateDecision.ACCEPT, HumanGateDecision.OVERRIDE}:
        return HumanGateTransition(
            step_id=step_id,
            decision=gate_decision,
            resulting_status=StepStatus.SUCCEEDED,
            workflow_action=WorkflowAction.CONTINUE,
            next_step=downstream,
        )

    if gate_decision is HumanGateDecision.REQUEST_MORE_EVIDENCE:
        return HumanGateTransition(
            step_id=step_id,
            decision=gate_decision,
            resulting_status=StepStatus.REQUIRES_REVIEW,
            workflow_action=WorkflowAction.REQUIRE_HUMAN_REVIEW,
            next_step=step_id,
            requires_new_evidence=True,
        )

    return HumanGateTransition(
        step_id=step_id,
        decision=gate_decision,
        resulting_status=StepStatus.PENDING,
        workflow_action=WorkflowAction.RETRY,
        next_step=step_id,
    )
