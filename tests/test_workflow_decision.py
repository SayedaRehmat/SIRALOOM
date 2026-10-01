from backend.app.domain.workflow_decision import (
    OutcomeKind,
    WorkflowAction,
    decide_workflow_outcome,
)


def test_no_acmg_evidence_is_a_limitation_not_pipeline_failure():
    decision = decide_workflow_outcome(
        OutcomeKind.NO_DATA,
        code="ACMG_NO_CRITERIA",
        message="No applicable ACMG criteria were established.",
    )
    assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION


def test_insufficient_evidence_is_not_a_technical_failure():
    decision = decide_workflow_outcome(OutcomeKind.INSUFFICIENT_EVIDENCE)
    assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION


def test_transient_failure_retries_only_when_marked_retryable():
    decision = decide_workflow_outcome(OutcomeKind.RETRYABLE_FAILURE, retryable=True)
    assert decision.action is WorkflowAction.RETRY
    assert decision.retryable is True


def test_rejected_resource_can_fallback_to_organization_active_resource():
    decision = decide_workflow_outcome(
        OutcomeKind.RESOURCE_REJECTED,
        fallback_available=True,
    )
    assert decision.action is WorkflowAction.FALLBACK_TO_ACTIVE_RESOURCE
    assert decision.fallback_allowed is True


def test_missing_resource_without_fallback_can_request_lab_action():
    decision = decide_workflow_outcome(
        OutcomeKind.RESOURCE_UNAVAILABLE,
        lab_action_required=True,
    )
    assert decision.action is WorkflowAction.REQUEST_LAB_ACTION
    assert decision.lab_action_required is True


def test_missing_resource_without_safe_recovery_waits():
    decision = decide_workflow_outcome(OutcomeKind.RESOURCE_UNAVAILABLE)
    assert decision.action is WorkflowAction.WAIT_FOR_RESOURCE


def test_invalid_input_blocks_without_retry():
    decision = decide_workflow_outcome(OutcomeKind.INPUT_INVALID, retryable=True)
    assert decision.action is WorkflowAction.BLOCK
    assert decision.retryable is False


def test_human_review_is_explicit():
    decision = decide_workflow_outcome(OutcomeKind.HUMAN_REVIEW)
    assert decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW


def test_unknown_outcome_is_terminal_and_visible():
    decision = decide_workflow_outcome("A_NEW_UNCLASSIFIED_STATE")
    assert decision.action is WorkflowAction.TERMINAL_FAILURE
    assert decision.code == "WORKFLOW_OUTCOME_UNCLASSIFIED"
