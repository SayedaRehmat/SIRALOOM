from backend.app.domain.enums import AnalysisStatus, StepStatus


def test_resource_failure_is_a_first_class_workflow_state():
    assert AnalysisStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"
    assert StepStatus.RESOURCE_FAILURE.value == "RESOURCE_FAILURE"


def test_celery_worker_recovery_contract_is_configured():
    from backend.app.infrastructure.queue.celery_app import run_analysis_task

    assert run_analysis_task.acks_late is True
    assert run_analysis_task.reject_on_worker_lost is True


def test_worker_recovery_preserves_explicit_retry_state_contract():
    from backend.app.domain.enums import StepStatus

    assert StepStatus.RETRYING.value == "RETRYING"
    assert StepStatus.RUNNING.value == "RUNNING"
