from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    _assert_profile_bound_resource_execution,
)


class _DB:
    def __init__(self, analysis):
        self.analysis = analysis

    def get(self, model, analysis_id):
        return self.analysis


def _resolved(resource_id, *, version="1", qualification_id=None, qualification_version="1", contract_hash="hash"):
    return SimpleNamespace(
        resource_id=resource_id,
        resource_version=version,
        qualification_id=qualification_id or uuid4(),
        qualification_version=qualification_version,
        contract_hash=contract_hash,
    )


def _analysis(selected):
    return SimpleNamespace(
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": "READY",
                "selected": selected,
            },
        }
    )


def _selection(resource_id, capability, resolved):
    return {
        "resource_id": str(resource_id),
        "capability": capability,
        "execution": {
            "resource_id": str(resolved.resource_id),
            "resource_version": resolved.resource_version,
            "qualification_id": str(resolved.qualification_id),
            "qualification_version": resolved.qualification_version,
            "contract_hash": resolved.contract_hash,
        },
    }


def test_profile_bound_worker_must_execute_the_exact_preflight_reference():
    resource_id = uuid4()
    resolved = _resolved(resource_id)
    db = _DB(_analysis([_selection(resource_id, "REFERENCE_PACKAGE", resolved)]))

    _assert_profile_bound_resource_execution(
        db,
        analysis_id=uuid4(),
        step_id="normalize",
        resolved=resolved,
    )


def test_profile_bound_worker_rejects_resource_not_selected_by_preflight():
    selected_id = uuid4()
    runtime_id = uuid4()
    selected = _resolved(selected_id)
    runtime = _resolved(runtime_id)
    db = _DB(_analysis([_selection(selected_id, "REFERENCE_PACKAGE", selected)]))

    with pytest.raises(ResourceExecutionError, match="was not selected exactly once"):
        _assert_profile_bound_resource_execution(
            db,
            analysis_id=uuid4(),
            step_id="normalize",
            resolved=runtime,
        )


def test_profile_bound_worker_rejects_cross_stage_resource_use():
    resource_id = uuid4()
    resolved = _resolved(resource_id)
    db = _DB(_analysis([_selection(resource_id, "REFERENCE_PACKAGE", resolved)]))

    with pytest.raises(ResourceExecutionError, match="not executable by workflow step 'annotate'"):
        _assert_profile_bound_resource_execution(
            db,
            analysis_id=uuid4(),
            step_id="annotate",
            resolved=resolved,
        )


def test_profile_bound_worker_rejects_qualification_drift():
    resource_id = uuid4()
    planned = _resolved(resource_id, contract_hash="qualified-contract")
    runtime = _resolved(
        resource_id,
        qualification_id=planned.qualification_id,
        contract_hash="different-contract",
    )
    db = _DB(_analysis([_selection(resource_id, "REFERENCE_PACKAGE", planned)]))

    with pytest.raises(ResourceExecutionError, match="differs from the immutable preflight plan"):
        _assert_profile_bound_resource_execution(
            db,
            analysis_id=uuid4(),
            step_id="normalize",
            resolved=runtime,
        )
