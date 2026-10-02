from backend.app.domain.workflow_decision import (
    OutcomeKind,
    WorkflowAction,
    decide_workflow_outcome,
    decide_step_outcome,
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



def test_every_step_has_explicit_scientific_limitation_policy():
    from backend.app.domain.workflow_decision import WORKFLOW_STEP_IDS, STEP_LIMITATION_ACTION

    assert len(WORKFLOW_STEP_IDS) == 10
    for step_id in WORKFLOW_STEP_IDS:
        assert (step_id, OutcomeKind.NO_DATA) in STEP_LIMITATION_ACTION
        assert (step_id, OutcomeKind.INSUFFICIENT_EVIDENCE) in STEP_LIMITATION_ACTION


def test_population_evidence_and_acmg_limitations_do_not_fail_pipeline():
    for step_id in ("population", "build_evidence"):
        for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
            decision = decide_step_outcome(step_id, outcome)
            assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION

    for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
        decision = decide_step_outcome("acmg_assessment", outcome)
        assert decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW


def test_annotation_limitation_continues_to_downstream_interpretation():
    for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
        decision = decide_step_outcome("annotate", outcome)
        assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION


def test_validation_and_normalization_limitation_blocks_unsafe_downstream_processing():
    for step_id in ("validate_input", "normalize"):
        for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
            decision = decide_step_outcome(step_id, outcome)
            assert decision.action is WorkflowAction.BLOCK


def test_human_gates_do_not_auto_continue_on_limitation():
    for step_id in ("review", "reportability"):
        for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
            decision = decide_step_outcome(step_id, outcome)
            assert decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW


def test_report_can_be_generated_with_a_scientific_limitation():
    for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
        decision = decide_step_outcome("report", outcome)
        assert decision.action is WorkflowAction.CONTINUE_WITH_LIMITATION


def test_provenance_requires_an_actual_provenance_result():
    for outcome in (OutcomeKind.NO_DATA, OutcomeKind.INSUFFICIENT_EVIDENCE):
        decision = decide_step_outcome("export_provenance", outcome)
        assert decision.action is WorkflowAction.BLOCK


def test_input_invalid_blocks_at_every_workflow_step():
    from backend.app.domain.workflow_decision import WORKFLOW_STEP_IDS

    for step_id in WORKFLOW_STEP_IDS:
        decision = decide_step_outcome(step_id, OutcomeKind.INPUT_INVALID, retryable=True)
        assert decision.action is WorkflowAction.BLOCK
        assert decision.retryable is False


def test_resource_invalid_requires_lab_action_at_every_workflow_step():
    from backend.app.domain.workflow_decision import WORKFLOW_STEP_IDS

    for step_id in WORKFLOW_STEP_IDS:
        decision = decide_step_outcome(step_id, OutcomeKind.RESOURCE_INVALID)
        assert decision.action is WorkflowAction.REQUEST_LAB_ACTION
        assert decision.lab_action_required is True


def test_retryable_failure_retries_at_every_workflow_step_when_explicitly_retryable():
    from backend.app.domain.workflow_decision import WORKFLOW_STEP_IDS

    for step_id in WORKFLOW_STEP_IDS:
        decision = decide_step_outcome(
            step_id, OutcomeKind.RETRYABLE_FAILURE, retryable=True
        )
        assert decision.action is WorkflowAction.RETRY


def test_unclassified_step_fails_closed():
    decision = decide_step_outcome("future_step", OutcomeKind.NO_DATA)
    assert decision.action is WorkflowAction.TERMINAL_FAILURE
    assert decision.code == "WORKFLOW_STEP_UNCLASSIFIED"


def test_resource_fallback_is_allowed_only_before_clinical_decision_gates():
    from backend.app.domain.workflow_decision import RESOURCE_RECOVERY_ALLOWED_STEPS

    for step_id in ("normalize", "annotate", "population"):
        decision = decide_step_outcome(
            step_id,
            OutcomeKind.RESOURCE_UNAVAILABLE,
            fallback_available=True,
        )
        assert step_id in RESOURCE_RECOVERY_ALLOWED_STEPS
        assert decision.action is WorkflowAction.FALLBACK_TO_ACTIVE_RESOURCE
        assert decision.fallback_allowed is True


def test_acmg_resource_failure_requires_human_review_even_with_fallback():
    decision = decide_step_outcome(
        "acmg_assessment",
        OutcomeKind.RESOURCE_UNAVAILABLE,
        fallback_available=True,
    )
    assert decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW
    assert decision.fallback_allowed is False
    assert decision.lab_action_required is True


def test_review_and_reportability_resource_failure_cannot_auto_fallback():
    for step_id in ("review", "reportability"):
        decision = decide_step_outcome(
            step_id,
            OutcomeKind.RESOURCE_REJECTED,
            fallback_available=True,
        )
        assert decision.action is WorkflowAction.REQUIRE_HUMAN_REVIEW
        assert decision.fallback_allowed is False


def test_non_resource_consuming_terminal_stages_wait_without_fallback():
    for step_id in ("validate_input", "build_evidence", "report", "export_provenance"):
        decision = decide_step_outcome(
            step_id,
            OutcomeKind.RESOURCE_UNAVAILABLE,
            fallback_available=True,
        )
        assert decision.action is WorkflowAction.WAIT_FOR_RESOURCE
        assert decision.fallback_allowed is False


def test_stage_specific_resource_policy_preserves_explicit_lab_action():
    decision = decide_step_outcome(
        "normalize",
        OutcomeKind.RESOURCE_INVALID,
        lab_action_required=True,
    )
    assert decision.action is WorkflowAction.REQUEST_LAB_ACTION
    assert decision.lab_action_required is True
    assert decision.fallback_allowed is False
