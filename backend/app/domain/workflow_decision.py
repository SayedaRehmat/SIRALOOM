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


# Each workflow stage has an explicit interpretation for scientific limitations.
# This is intentionally stricter than one global "NO_DATA => continue" rule:
# some stages cannot safely produce a downstream result without their required
# input (for example an empty/invalid validation or normalization result), while
# absence of population/evidence data is a legitimate scientific limitation.
WORKFLOW_STEP_IDS: tuple[str, ...] = (
    "validate_input",
    "normalize",
    "annotate",
    "population",
    "build_evidence",
    "acmg_assessment",
    "review",
    "reportability",
    "report",
    "export_provenance",
)

# Resource recovery is deliberately stage-specific. A resource fallback can change
# the scientific inputs available to a stage; it is therefore safe to automate only
# before clinical classification/review gates. Later stages must stop or require
# human action rather than silently switching evidence context.
RESOURCE_RECOVERY_ALLOWED_STEPS: frozenset[str] = frozenset({
    "normalize",
    "annotate",
    "population",
})

RESOURCE_RECOVERY_REVIEW_STEPS: frozenset[str] = frozenset({
    "acmg_assessment",
    "review",
    "reportability",
})


def _decide_stage_resource_outcome(
    step_id: str,
    kind: OutcomeKind,
    *,
    code: str | None,
    message: str | None,
    fallback_available: bool,
    lab_action_required: bool,
) -> WorkflowDecision:
    """Apply the governed resource-recovery policy for a concrete workflow stage."""
    if step_id in RESOURCE_RECOVERY_ALLOWED_STEPS:
        return decide_workflow_outcome(
            kind,
            code=code,
            message=message,
            fallback_available=fallback_available,
            lab_action_required=lab_action_required,
        )

    if step_id in RESOURCE_RECOVERY_REVIEW_STEPS:
        return WorkflowDecision(
            WorkflowAction.REQUIRE_HUMAN_REVIEW,
            code or kind.value,
            message or "A resource condition occurred at a clinical decision gate; human review is required before continuing.",
            lab_action_required=True,
        )

    if lab_action_required:
        return WorkflowDecision(
            WorkflowAction.REQUEST_LAB_ACTION,
            code or kind.value,
            message or "A required resource condition needs explicit laboratory action before this workflow stage can continue.",
            lab_action_required=True,
        )

    return WorkflowDecision(
        WorkflowAction.WAIT_FOR_RESOURCE,
        code or kind.value,
        message or "The required resource is unavailable and this workflow stage does not permit automatic fallback.",
    )


# (step, outcome) -> action. The common decision contract remains the default
# for technical/resource outcomes; this matrix governs the two scientific
# limitation outcomes whose meaning depends on where they occur.
STEP_LIMITATION_ACTION: dict[tuple[str, OutcomeKind], WorkflowAction] = {
    ("validate_input", OutcomeKind.NO_DATA): WorkflowAction.BLOCK,
    ("normalize", OutcomeKind.NO_DATA): WorkflowAction.BLOCK,
    ("annotate", OutcomeKind.NO_DATA): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("population", OutcomeKind.NO_DATA): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("build_evidence", OutcomeKind.NO_DATA): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("acmg_assessment", OutcomeKind.NO_DATA): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("review", OutcomeKind.NO_DATA): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("reportability", OutcomeKind.NO_DATA): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("report", OutcomeKind.NO_DATA): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("export_provenance", OutcomeKind.NO_DATA): WorkflowAction.BLOCK,

    ("validate_input", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.BLOCK,
    ("normalize", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.BLOCK,
    ("annotate", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("population", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("build_evidence", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("acmg_assessment", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("review", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("reportability", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.REQUIRE_HUMAN_REVIEW,
    ("report", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.CONTINUE_WITH_LIMITATION,
    ("export_provenance", OutcomeKind.INSUFFICIENT_EVIDENCE): WorkflowAction.BLOCK,
}


def decide_step_outcome(
    step_id: str,
    outcome: OutcomeKind | str,
    *,
    code: str | None = None,
    message: str | None = None,
    retryable: bool = False,
    fallback_available: bool = False,
    lab_action_required: bool = False,
) -> WorkflowDecision:
    """Apply the outcome contract to one concrete workflow step.

    This function is side-effect free. Persistence, retries, resource switching,
    notifications and human-gate transitions remain in the owning workflow.
    Unknown steps/outcomes fail closed.
    """
    if step_id not in WORKFLOW_STEP_IDS:
        return WorkflowDecision(
            WorkflowAction.TERMINAL_FAILURE,
            code or "WORKFLOW_STEP_UNCLASSIFIED",
            message or f"Unclassified workflow step: {step_id}",
        )

    try:
        kind = outcome if isinstance(outcome, OutcomeKind) else OutcomeKind(str(outcome).upper())
    except ValueError:
        return WorkflowDecision(
            WorkflowAction.TERMINAL_FAILURE,
            code or "WORKFLOW_OUTCOME_UNCLASSIFIED",
            message or f"Unclassified workflow outcome: {outcome}",
        )

    if kind in {OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE}:
        action = STEP_LIMITATION_ACTION[(step_id, kind)]
        return WorkflowDecision(
            action,
            code or kind.value,
            message or "Scientific result is limited at this workflow stage; this is not automatically a technical failure.",
            lab_action_required=action is WorkflowAction.REQUEST_LAB_ACTION,
        )

    if kind in {OutcomeKind.RESOURCE_UNAVAILABLE, OutcomeKind.RESOURCE_REJECTED}:
        return _decide_stage_resource_outcome(
            step_id,
            kind,
            code=code,
            message=message,
            fallback_available=fallback_available,
            lab_action_required=lab_action_required,
        )

    return decide_workflow_outcome(
        kind,
        code=code,
        message=message,
        retryable=retryable,
        fallback_available=fallback_available,
        lab_action_required=lab_action_required,
    )
