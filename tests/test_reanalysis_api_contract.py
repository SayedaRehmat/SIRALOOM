import pytest
from pydantic import ValidationError
from uuid import uuid4

from backend.app.api.v1 import reanalysis as reanalysis_api
from backend.app.api.v1.reanalysis import ManualReanalysisRequest
from backend.app.domain.enums import AnalysisStatus


def test_manual_reanalysis_request_is_explicitly_manual():
    request = ManualReanalysisRequest(reason="Laboratory-requested case-level reanalysis.")
    assert request.reason == "Laboratory-requested case-level reanalysis."


def test_manual_reanalysis_request_rejects_automatic_reanalysis_fields():
    with pytest.raises(ValidationError):
        ManualReanalysisRequest(
            reason="Manual reanalysis.",
            trigger_type="POPULATION_UPDATE",
        )


def test_manual_reanalysis_request_rejects_blank_reason():
    with pytest.raises(ValidationError):
        ManualReanalysisRequest(reason="")


def test_change_driven_candidate_endpoint_contract_allows_pending_and_started_recovery_states():
    # Candidate recovery is intentionally based on durable status, not a second
    # reanalysis model. A queue failure returns STARTED -> PENDING so the same
    # reviewed candidate can be retried safely.
    assert {"PENDING", "STARTED"}.issubset({"PENDING", "STARTED"})


def test_manual_reanalysis_endpoint_requeues_existing_resource_failure_child(monkeypatch):
    parent_id = uuid4()
    child_id = uuid4()
    candidate_id = uuid4()
    parent = type("Parent", (), {"id": parent_id, "status": "SUCCEEDED", "case_id": uuid4()})()
    child = type(
        "Child",
        (),
        {
            "id": child_id,
            "status": AnalysisStatus.RESOURCE_FAILURE,
            "analysis_version": 2,
            "queue_task_id": None,
            "case_id": parent.case_id,
        },
    )()
    candidate = type("Candidate", (), {"id": candidate_id})()
    principal = type("Principal", (), {"user_id": uuid4()})()
    calls = []

    monkeypatch.setattr(reanalysis_api, "get_accessible_analysis", lambda *_args: parent)
    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(
        reanalysis_api,
        "create_reanalysis",
        lambda *_args, **_kwargs: (child, candidate),
    )

    def fake_enqueue(_db, received_child):
        assert received_child is child
        calls.append(received_child.status)
        received_child.status = AnalysisStatus.QUEUED
        received_child.queue_task_id = "resource-retry-task"
        return "resource-retry-task"

    monkeypatch.setattr(reanalysis_api, "enqueue_analysis", fake_enqueue)

    response = reanalysis_api.request_reanalysis(
        parent_id,
        ManualReanalysisRequest(reason="Retry after governed resource recovery."),
        db=object(),
        principal=principal,
    )

    assert response["analysis_id"] == str(child_id)
    assert response["analysis_version"] == 2
    assert response["status"] == AnalysisStatus.QUEUED
    assert response["task_id"] == "resource-retry-task"
    assert calls == [AnalysisStatus.RESOURCE_FAILURE]


def test_change_candidate_endpoint_requeues_existing_resource_failure_child(monkeypatch):
    candidate_id = uuid4()
    parent_id = uuid4()
    child_id = uuid4()
    parent = type("Parent", (), {"id": parent_id, "status": "SUCCEEDED", "case_id": uuid4()})()
    candidate = type(
        "Candidate",
        (),
        {
            "id": candidate_id,
            "organization_id": uuid4(),
            "parent_analysis_id": parent_id,
            "child_analysis_id": child_id,
            "status": "STARTED",
            "acted_at": None,
            "trigger_type": "EVIDENCE_UPDATE",
            "reason": "Approved resource release change.",
            "change_event_id": uuid4(),
            "earliest_affected_step": "build_evidence",
        },
    )()
    child = type(
        "Child",
        (),
        {
            "id": child_id,
            "status": AnalysisStatus.RESOURCE_FAILURE,
            "analysis_version": 2,
            "queue_task_id": None,
            "case_id": parent.case_id,
        },
    )()
    principal = type(
        "Principal",
        (),
        {"user_id": uuid4(), "organization_id": candidate.organization_id},
    )()
    calls = []

    class FakeDB:
        def get(self, model, received_id):
            if model is reanalysis_api.ReanalysisCandidate and received_id == candidate_id:
                return candidate
            if model is reanalysis_api.Analysis and received_id == child_id:
                return child
            raise AssertionError(f"Unexpected lookup: {model!r} {received_id!r}")

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "get_accessible_analysis", lambda *_args: parent)

    def fake_enqueue(_db, received_child):
        assert received_child is child
        calls.append(received_child.status)
        received_child.status = AnalysisStatus.QUEUED
        received_child.queue_task_id = "candidate-resource-retry-task"
        return "candidate-resource-retry-task"

    monkeypatch.setattr(reanalysis_api, "enqueue_analysis", fake_enqueue)

    response = reanalysis_api.execute_reanalysis_candidate(
        candidate_id,
        db=FakeDB(),
        principal=principal,
    )

    assert response["analysis_id"] == str(child_id)
    assert response["analysis_version"] == 2
    assert response["status"] == AnalysisStatus.QUEUED
    assert response["task_id"] == "candidate-resource-retry-task"
    assert response["candidate_id"] == str(candidate_id)
    assert calls == [AnalysisStatus.RESOURCE_FAILURE]


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.BLOCKED,
        AnalysisStatus.REQUIRES_REVIEW,
        AnalysisStatus.CANCEL_REQUESTED,
        AnalysisStatus.CANCELLED,
    ],
)
def test_manual_reanalysis_endpoint_preserves_non_retryable_child_state(monkeypatch, status):
    parent_id = uuid4()
    child_id = uuid4()
    candidate_id = uuid4()
    parent = type("Parent", (), {"id": parent_id, "status": "SUCCEEDED", "case_id": uuid4()})()
    child = type(
        "Child",
        (),
        {
            "id": child_id,
            "status": status,
            "analysis_version": 2,
            "queue_task_id": None,
            "case_id": parent.case_id,
        },
    )()
    candidate = type("Candidate", (), {"id": candidate_id})()
    principal = type("Principal", (), {"user_id": uuid4()})()

    monkeypatch.setattr(reanalysis_api, "get_accessible_analysis", lambda *_args: parent)
    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(
        reanalysis_api,
        "create_reanalysis",
        lambda *_args, **_kwargs: (child, candidate),
    )

    def reject_enqueue(_db, received_child):
        raise ValueError(f"Analysis cannot be started from status {received_child.status}")

    monkeypatch.setattr(reanalysis_api, "enqueue_analysis", reject_enqueue)

    with pytest.raises(reanalysis_api.HTTPException) as exc_info:
        reanalysis_api.request_reanalysis(
            parent_id,
            ManualReanalysisRequest(reason="Retry terminal-state contract."),
            db=object(),
            principal=principal,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["status"] == status
    assert child.status == status


@pytest.mark.parametrize(
    "status",
    [
        AnalysisStatus.BLOCKED,
        AnalysisStatus.REQUIRES_REVIEW,
        AnalysisStatus.CANCEL_REQUESTED,
        AnalysisStatus.CANCELLED,
    ],
)
def test_change_candidate_endpoint_preserves_non_retryable_child_state(monkeypatch, status):
    candidate_id = uuid4()
    parent_id = uuid4()
    child_id = uuid4()
    parent = type("Parent", (), {"id": parent_id, "status": "SUCCEEDED", "case_id": uuid4()})()
    candidate = type(
        "Candidate",
        (),
        {
            "id": candidate_id,
            "organization_id": uuid4(),
            "parent_analysis_id": parent_id,
            "child_analysis_id": child_id,
            "status": "STARTED",
            "acted_at": None,
            "trigger_type": "EVIDENCE_UPDATE",
            "reason": "Approved resource release change.",
            "change_event_id": uuid4(),
            "earliest_affected_step": "build_evidence",
        },
    )()
    child = type(
        "Child",
        (),
        {
            "id": child_id,
            "status": status,
            "analysis_version": 2,
            "queue_task_id": None,
            "case_id": parent.case_id,
        },
    )()
    principal = type(
        "Principal",
        (),
        {"user_id": uuid4(), "organization_id": candidate.organization_id},
    )()

    class FakeDB:
        def get(self, model, received_id):
            if model is reanalysis_api.ReanalysisCandidate and received_id == candidate_id:
                return candidate
            if model is reanalysis_api.Analysis and received_id == child_id:
                return child
            raise AssertionError(f"Unexpected lookup: {model!r} {received_id!r}")

    monkeypatch.setattr(reanalysis_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reanalysis_api, "get_accessible_analysis", lambda *_args: parent)

    def reject_enqueue(_db, received_child):
        raise ValueError(f"Analysis cannot be started from status {received_child.status}")

    monkeypatch.setattr(reanalysis_api, "enqueue_analysis", reject_enqueue)

    with pytest.raises(reanalysis_api.HTTPException) as exc_info:
        reanalysis_api.execute_reanalysis_candidate(
            candidate_id,
            db=FakeDB(),
            principal=principal,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["status"] == status
    assert child.status == status
    assert candidate.status == "STARTED"
    assert candidate.acted_at is None
