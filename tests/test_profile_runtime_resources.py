from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain import profile_runtime_resources as runtime
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.domain.resource_execution import ResolvedResourceExecution


class FakeDB:
    def __init__(self, analysis, resources=None):
        self.analysis = analysis
        self.resources = resources or {}

    def get(self, model, object_id):
        if object_id == self.analysis.id:
            return self.analysis
        return self.resources.get(object_id)


def _resolved(resource_id, *, version="1", qualification_id=None, qualification_version="1", contract_hash="hash-a"):
    return ResolvedResourceExecution(
        resource_id=resource_id,
        resource_version=version,
        qualification_id=qualification_id or uuid4(),
        qualification_version=qualification_version,
        contract=ResourceExecutionContract(
            provider_id="gnomAD",
            provider_version="graphql",
            access_method="API",
            endpoint="https://example.test/graphql",
            location=None,
            dataset="gnomad_r4",
            execution_scope="SIRALOOM_MANAGED",
            toolchain={},
        ),
        contract_hash=contract_hash,
    )


def _analysis(resource_id, execution, *, capability="POPULATION"):
    return SimpleNamespace(
        id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": "READY",
                "selected": [{
                    "capability": capability,
                    "required": True,
                    "resource_id": str(resource_id),
                    "version": execution.resource_version,
                    "execution": execution.snapshot,
                }],
            },
        },
    )


def test_resolver_returns_exact_preflight_population_resource(monkeypatch):
    resource_id = uuid4()
    qualification_id = uuid4()
    execution = _resolved(resource_id, qualification_id=qualification_id)
    resource = SimpleNamespace(id=resource_id, provider="GNOMAD", version="1")
    analysis = _analysis(resource_id, execution)
    db = FakeDB(analysis, {resource_id: resource})
    monkeypatch.setattr(runtime, "resolve_resource_execution", lambda db, resource: execution)

    resolved = runtime.resolve_profile_runtime_resource(
        db,
        analysis_id=analysis.id,
        capability="POPULATION",
    )

    assert resolved.resource is resource
    assert resolved.execution is execution


def test_resolver_rejects_missing_selected_resource():
    resource_id = uuid4()
    execution = _resolved(resource_id)
    analysis = _analysis(resource_id, execution)
    db = FakeDB(analysis)

    with pytest.raises(runtime.ProfileRuntimeResourceError, match="Preflight-selected resource .* no longer exists"):
        runtime.resolve_profile_runtime_resource(
            db,
            analysis_id=analysis.id,
            capability="POPULATION",
        )


def test_resolver_rejects_stale_execution_contract(monkeypatch):
    resource_id = uuid4()
    selected_execution = _resolved(resource_id, contract_hash="hash-a")
    current_execution = _resolved(
        resource_id,
        qualification_id=selected_execution.qualification_id,
        contract_hash="hash-b",
    )
    resource = SimpleNamespace(id=resource_id, provider="GNOMAD", version="1")
    analysis = _analysis(resource_id, selected_execution)
    db = FakeDB(analysis, {resource_id: resource})
    monkeypatch.setattr(runtime, "resolve_resource_execution", lambda db, resource: current_execution)

    with pytest.raises(runtime.ProfileRuntimeResourceError, match="Preflight resource contract no longer matches runtime qualification"):
        runtime.resolve_profile_runtime_resource(
            db,
            analysis_id=analysis.id,
            capability="POPULATION",
        )
