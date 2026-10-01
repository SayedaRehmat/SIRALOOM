"""Common decision contract for resilient laboratory workflow steps.

This module classifies workflow outcomes without conflating scientific limitations
with technical failures. It is intentionally side-effect free: persistence,
notifications, retries, and resource switching belong to the workflow layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class WorkflowAction(StrEnum):
    CONTINUE = "CONTINUE"
    CONTINUE_WITH_LIMITATION = "CONTINUE_WITH_LIMITATION"
    RETRY = "RETRY"
    FALLBACK_TO_ACTIVE_RESOURCE = "FALLBACK_TO_ACTIVE_RESOURCE"
    WAIT_FOR_RESOURCE = "WAIT_FOR_RESOURCE"
    REQUEST_LAB_ACTION = "REQUEST_LAB_ACTION"
    REQUIRE_HUMAN_REVIEW = "REQUIRE_HUMAN_REVIEW"
    BLOCK = "BLOCK"
    TERMINAL_FAILURE = "TERMINAL_FAILURE"


class OutcomeKind(StrEnum):
    SUCCESS = "SUCCESS"
    NO_DATA = "NO_DATA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    RESOURCE_REJECTED = "RESOURCE_REJECTED"
    RESOURCE_INVALID = "RESOURCE_INVALID"
    INPUT_INVALID = "INPUT_INVALID"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    UNEXPECTED = "UNEXPECTED"


@dataclass(frozen=True)
class WorkflowDecision:
    action: WorkflowAction
    code: str
    message: str
    retryable: bool = False
    fallback_allowed: bool = False
    lab_action_required: bool = False


def decide_workflow_outcome(
    outcome: OutcomeKind | str,
    *,
    code: str | None = None,
    message: str | None = None,
    retryable: bool = False,
    fallback_available: bool = False,
    lab_action_required: bool = False,
) -> WorkflowDecision:
    """Map a classified step outcome to one explicit next action.

    Unknown outcomes are terminal by default. A caller must explicitly classify
    a new condition before the platform is allowed to continue automatically.
    """
    try:
        kind = outcome if isinstance(outcome, OutcomeKind) else OutcomeKind(str(outcome).upper())
    except ValueError:
        return WorkflowDecision(
            WorkflowAction.TERMINAL_FAILURE,
            code or "WORKFLOW_OUTCOME_UNCLASSIFIED",
            message or f"Unclassified workflow outcome: {outcome}",
        )

    default_code = {
        OutcomeKind.SUCCESS: "STEP_SUCCEEDED",
        OutcomeKind.NO_DATA: "NO_DATA",
        OutcomeKind.INSUFFICIENT_EVIDENCE: "INSUFFICIENT_EVIDENCE",
        OutcomeKind.RETRYABLE_FAILURE: "RETRYABLE_FAILURE",
        OutcomeKind.RESOURCE_UNAVAILABLE: "RESOURCE_UNAVAILABLE",
        OutcomeKind.RESOURCE_REJECTED: "RESOURCE_REJECTED",
        OutcomeKind.RESOURCE_INVALID: "RESOURCE_INVALID",
        OutcomeKind.INPUT_INVALID: "INPUT_INVALID",
        OutcomeKind.HUMAN_REVIEW: "HUMAN_REVIEW_REQUIRED",
        OutcomeKind.UNEXPECTED: "WORKFLOW_UNEXPECTED_OUTCOME",
    }[kind]

    if kind is OutcomeKind.SUCCESS:
        return WorkflowDecision(WorkflowAction.CONTINUE, code or default_code, message or "Step completed successfully.")
    if kind in {OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE}:
        return WorkflowDecision(
            WorkflowAction.CONTINUE_WITH_LIMITATION,
            code or default_code,
            message or "Step completed without sufficient result data; this is not a technical failure.",
        )
    if kind is OutcomeKind.RETRYABLE_FAILURE and retryable:
        return WorkflowDecision(
            WorkflowAction.RETRY,
            code or default_code,
            message or "Step failed transiently and may be retried under the workflow retry policy.",
            retryable=True,
        )
    if kind in {OutcomeKind.RESOURCE_UNAVAILABLE, OutcomeKind.RESOURCE_REJECTED}:
        if fallback_available:
            return WorkflowDecision(
                WorkflowAction.FALLBACK_TO_ACTIVE_RESOURCE,
                code or default_code,
                message or "The requested resource is unavailable or rejected; use the organization's approved active resource.",
                fallback_allowed=True,
            )
        if lab_action_required:
            return WorkflowDecision(
                WorkflowAction.REQUEST_LAB_ACTION,
                code or default_code,
                message or "A governed resource is required and no safe fallback is available.",
                lab_action_required=True,
            )
        return WorkflowDecision(
            WorkflowAction.WAIT_FOR_RESOURCE,
            code or default_code,
            message or "The required resource is unavailable and no safe automatic fallback exists.",
        )
    if kind is OutcomeKind.RESOURCE_INVALID:
        return WorkflowDecision(
            WorkflowAction.REQUEST_LAB_ACTION,
            code or default_code,
            message or "The resource failed validation and requires laboratory action before use.",
            lab_action_required=True,
        )
    if kind is OutcomeKind.INPUT_INVALID:
        return WorkflowDecision(
            WorkflowAction.BLOCK,
            code or default_code,
            message or "Input validation failed; the analysis must not continue.",
        )
    if kind is OutcomeKind.HUMAN_REVIEW:
        return WorkflowDecision(
            WorkflowAction.REQUIRE_HUMAN_REVIEW,
            code or default_code,
            message or "Human review is required before this workflow can continue.",
        )
    return WorkflowDecision(
        WorkflowAction.TERMINAL_FAILURE,
        code or default_code,
        message or "The workflow encountered an unexpected condition with no governed recovery path.",
    )
