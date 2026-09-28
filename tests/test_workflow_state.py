from backend.app.domain.enums import AnalysisStatus, StepStatus


def test_resource_failure_is_a_first_class_workflow_state():
    assert AnalysisStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"
    assert StepStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"
\n\ndef test_celery_worker_recovery_contract_is_configured():\n    from backend.app.infrastructure.queue.celery_app import run_analysis_task\n\n    assert run_analysis_task.acks_late is True\n    assert run_analysis_task.reject_on_worker_lost is True\n\n\ndef test_worker_recovery_preserves_explicit_retry_state_contract():\n    from backend.app.domain.enums import StepStatus\n\n    assert StepStatus.RETRYING.value == "RETRYING"\n    assert StepStatus.RUNNING.value == "RUNNING"\n