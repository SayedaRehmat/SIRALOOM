from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain import profile_runtime_resources as runtime
from backend.app.domain.resource_execution import ResolvedResourceExecution
from backend.app.domain.resource_source_contract import ResourceExecutionContract
from backend.app.infrastructure.db.models import Analysis, Case


class FakeDB:
    def __init__(self, analysis, resources=None, *, organization_id=None):
        self.analysis = analysis
        self.resources = resources or {}
        self.organization_id = organization_id or uuid4()
        self.case = SimpleNamespace(
            id=analysis.case_id,
            organization_id=self.organization_id,
        )

    def get(self, model, object_id):
        if model is Analysis and object_id == self.analysis.id:
            return self.analysis
        if model is Case and object_id == self.analysis.case_id:
            return self.case
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
        case_id=uuid4(),
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


@pytest.mark.parametrize(
    ("resolver", "capability"),
    [
        ("resolve_profile_runtime_resource", "POPULATION"),
        ("resolve_profile_runtime_resources", "POPULATION_SECONDARY"),
    ],
)
def test_runtime_resolvers_reject_resource_from_another_organization(
    monkeypatch, resolver, capability
):
    resource_id = uuid4()
    execution = _resolved(resource_id)
    analysis = _analysis(resource_id, execution, capability=capability)
    organization_id = uuid4()
    foreign_resource = SimpleNamespace(
        id=resource_id,
        provider="GNOMAD",
        version="1",
        organization_id=uuid4(),
    )
    db = FakeDB(
        analysis,
        {resource_id: foreign_resource},
        organization_id=organization_id,
    )
    monkeypatch.setattr(
        runtime,
        "resolve_resource_execution",
        lambda *_args, **_kwargs: pytest.fail("foreign resource must not execute"),
    )

    with pytest.raises(
        runtime.ProfileRuntimeResourceError,
        match="outside the analysis organization",
    ):
        getattr(runtime, resolver)(
            db,
            analysis_id=analysis.id,
            capability=capability,
        )



def test_plural_resolver_returns_all_selected_secondary_resources(monkeypatch):
    resource_ids = [uuid4(), uuid4(), uuid4()]
    executions = [_resolved(rid, contract_hash=f"hash-{index}") for index, rid in enumerate(resource_ids)]
    resources = {
        rid: SimpleNamespace(id=rid, provider=provider, version="1")
        for rid, provider in zip(resource_ids, ("1000GENOMES", "TOPMED", "MIDDLE_EAST"))
    }
    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": "READY",
                "selected": [
                    {
                        "capability": "POPULATION_SECONDARY",
                        "required": False,
                        "resource_id": str(execution.resource_id),
                        "version": execution.resource_version,
                        "execution": execution.snapshot,
                    }
                    for execution in executions
                ],
            },
        },
    )
    db = FakeDB(analysis, resources)
    monkeypatch.setattr(runtime, "resolve_resource_execution", lambda db, resource: executions[resource_ids.index(resource.id)])

    resolved = runtime.resolve_profile_runtime_resources(
        db,
        analysis_id=analysis.id,
        capability="POPULATION_SECONDARY",
    )

    assert [item.resource.provider for item in resolved] == [
        "1000GENOMES", "TOPMED", "MIDDLE_EAST"
    ]

    selected_provider = runtime.resolve_profile_runtime_resources(
        db,
        analysis_id=analysis.id,
        capability="POPULATION_SECONDARY",
        provider_id="TOPMED",
    )
    assert [item.resource.provider for item in selected_provider] == ["TOPMED"]


def test_plural_resolver_rejects_one_stale_selected_secondary_resource(monkeypatch):
    resource_ids = [uuid4(), uuid4()]
    selected = [_resolved(resource_ids[0], contract_hash="hash-a"), _resolved(resource_ids[1], contract_hash="hash-b")]
    current = [_resolved(resource_ids[0], qualification_id=selected[0].qualification_id, contract_hash="hash-a"),
               _resolved(resource_ids[1], qualification_id=selected[1].qualification_id, contract_hash="hash-changed")]
    resources = {rid: SimpleNamespace(id=rid, provider="SECONDARY", version="1") for rid in resource_ids}
    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": "READY_WITH_LIMITATIONS",
                "selected": [
                    {"capability": "POPULATION_SECONDARY", "resource_id": str(ex.resource_id), "execution": ex.snapshot}
                    for ex in selected
                ],
            },
        },
    )
    db = FakeDB(analysis, resources)
    monkeypatch.setattr(runtime, "resolve_resource_execution", lambda db, resource: current[resource_ids.index(resource.id)])

    with pytest.raises(runtime.ProfileRuntimeResourceError, match="Preflight resource contract no longer matches runtime qualification"):
        runtime.resolve_profile_runtime_resources(db, analysis_id=analysis.id, capability="POPULATION_SECONDARY")


def test_plural_resolver_returns_empty_for_intentionally_absent_optional_capability():
    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {"status": "READY", "selected": [], "issues": []},
        },
    )
    db = FakeDB(analysis)

    assert runtime.resolve_profile_runtime_resources(
        db,
        analysis_id=analysis.id,
        capability="POPULATION_SECONDARY",
    ) == ()


def test_plural_resolver_raises_for_unavailable_optional_resource_that_was_configured():
    analysis = SimpleNamespace(
        id=uuid4(),
        case_id=uuid4(),
        configuration={
            "resource_profile_id": "WES_GRCh38_STANDARD",
            "resource_plan": {
                "status": "READY_WITH_LIMITATIONS",
                "selected": [],
                "issues": [{
                    "capability": "POPULATION_SECONDARY",
                    "required": False,
                    "code": "RESOURCE_UNAVAILABLE",
                    "message": "The configured optional secondary resource is unavailable.",
                }],
            },
        },
    )
    db = FakeDB(analysis)

    assert runtime.resolve_profile_runtime_resources(
        db,
        analysis_id=analysis.id,
        capability="POPULATION_SECONDARY",
    ) == ()
