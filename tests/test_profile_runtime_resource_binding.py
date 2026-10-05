from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    ResolvedResourceExecution,
    _validate_profile_runtime_binding,
)
from backend.app.domain.resource_source_contract import ResourceExecutionContract


class FakeDB:
    def __init__(self, analysis):
        self.analysis = analysis

    def get(self, model, analysis_id):
        return self.analysis


def _resolved(*, resource_id=None, qualification_id=None, version="1", qualification_version="1", contract_hash="hash-a"):
    return ResolvedResourceExecution(
        resource_id=resource_id or uuid4(),
        resource_version=version,
        qualification_id=qualification_id or uuid4(),
        qualification_version=qualification_version,
        contract=ResourceExecutionContract(
            provider_id="GeneBe",
            provider_version="api-public-v1",
            access_method="API",
            endpoint="https://example.test/variants",
            location=None,
            dataset=None,
            execution_scope="SIRALOOM_MANAGED",
            toolchain={},
        ),
        contract_hash=contract_hash,
    )


def _analysis(*, selected, status="READY"):
    return SimpleNamespace(
        id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": status,
                "selected": selected,
            },
        },
    )


def _selected(resolved, *, capability="ANNOTATION_ENGINE"):
    return {
        "capability": capability,
        "required": True,
        "resource_id": str(resolved.resource_id),
        "version": resolved.resource_version,
        "execution": resolved.snapshot,
    }


def test_profile_runtime_binding_accepts_exact_preflight_selection():
    resolved = _resolved()
    analysis = _analysis(selected=[_selected(resolved)])

    _validate_profile_runtime_binding(
        FakeDB(analysis),
        analysis_id=analysis.id,
        step_id="annotate",
        resolved=resolved,
    )


def test_profile_runtime_binding_rejects_resource_not_selected_by_preflight():
    selected = _resolved()
    consumed = _resolved()
    analysis = _analysis(selected=[_selected(selected)])

    with pytest.raises(ResourceExecutionError, match="RESOURCE_NOT_SELECTED"):
        _validate_profile_runtime_binding(
            FakeDB(analysis),
            analysis_id=analysis.id,
            step_id="annotate",
            resolved=consumed,
        )


def test_profile_runtime_binding_rejects_stale_qualification_or_contract():
    resolved = _resolved()
    selected = _selected(resolved)
    stale = _resolved(
        resource_id=resolved.resource_id,
        qualification_id=uuid4(),
        contract_hash="hash-b",
    )
    analysis = _analysis(selected=[selected])

    with pytest.raises(ResourceExecutionError, match="RESOURCE_PLAN_STALE"):
        _validate_profile_runtime_binding(
            FakeDB(analysis),
            analysis_id=analysis.id,
            step_id="annotate",
            resolved=stale,
        )


def test_profile_runtime_binding_enforces_stage_capability():
    resolved = _resolved()
    analysis = _analysis(selected=[_selected(resolved, capability="POPULATION")])

    with pytest.raises(ResourceExecutionError, match="RESOURCE_CAPABILITY_MISMATCH"):
        _validate_profile_runtime_binding(
            FakeDB(analysis),
            analysis_id=analysis.id,
            step_id="annotate",
            resolved=resolved,
        )


def test_profile_runtime_binding_blocks_non_ready_plan():
    resolved = _resolved()
    analysis = _analysis(selected=[_selected(resolved)], status="BLOCKED")

    with pytest.raises(ResourceExecutionError, match="RESOURCE_PLAN_NOT_READY"):
        _validate_profile_runtime_binding(
            FakeDB(analysis),
            analysis_id=analysis.id,
            step_id="annotate",
            resolved=resolved,
        )


def test_legacy_analysis_without_profile_keeps_existing_execution_path():
    resolved = _resolved()
    analysis = SimpleNamespace(id=uuid4(), configuration={})

    _validate_profile_runtime_binding(
        FakeDB(analysis),
        analysis_id=analysis.id,
        step_id="annotate",
        resolved=resolved,
    )
