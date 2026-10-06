from backend.app.domain.enums import StepStatus
from backend.app.domain.workflow_decision import WorkflowAction, WORKFLOW_STEP_IDS
from backend.app.domain.workflow_human_gate import (
    HumanGateDecision,
    next_workflow_step,
    resolve_human_gate,
)


def test_accepting_acmg_gate_releases_review_and_advances_to_review_step():
    transition = resolve_human_gate(
        "acmg_assessment",
        HumanGateDecision.ACCEPT,
    )

    assert transition.resulting_status is StepStatus.SUCCEEDED
    assert transition.workflow_action is WorkflowAction.CONTINUE
    assert transition.next_step == "review"


def test_requesting_more_evidence_keeps_same_step_in_review():
    transition = resolve_human_gate(
        "acmg_assessment",
        HumanGateDecision.REQUEST_MORE_EVIDENCE,
    )

    assert transition.resulting_status is StepStatus.REQUIRES_REVIEW
    assert transition.workflow_action is WorkflowAction.REQUIRE_HUMAN_REVIEW
    assert transition.next_step == "acmg_assessment"
    assert transition.requires_new_evidence is True


def test_reject_and_retry_requeues_only_the_same_step():
    transition = resolve_human_gate(
        "population",
        HumanGateDecision.REJECT_AND_RETRY,
    )

    assert transition.resulting_status is StepStatus.PENDING
    assert transition.workflow_action is WorkflowAction.RETRY
    assert transition.next_step == "population"


def test_human_gate_contract_covers_every_canonical_workflow_step():
    assert next_workflow_step("validate_input") == "normalize"
    assert next_workflow_step("export_provenance") is None

    for step_id in WORKFLOW_STEP_IDS:
        transition = resolve_human_gate(step_id, HumanGateDecision.ACCEPT)
        assert transition.resulting_status is StepStatus.SUCCEEDED
        assert transition.workflow_action is WorkflowAction.CONTINUE
