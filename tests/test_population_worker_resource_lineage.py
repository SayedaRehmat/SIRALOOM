from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.workflows.variant import (
    ResourceConsumptionError,
    _require_population_resource_rows,
)


class _ResourceSession:
    def __init__(self, resources):
        self.resources = resources

    def scalars(self, _statement):
        return SimpleNamespace(all=lambda: self.resources)


def _observation(*, analysis_id, resource_id):
    return SimpleNamespace(analysis_id=analysis_id, resource_id=resource_id)


@pytest.mark.parametrize("resource_id", [None, uuid4()])
def test_worker_population_lineage_rejects_missing_source_resource(resource_id):
    analysis_id = uuid4()
    db = _ResourceSession([])

    with pytest.raises(ResourceConsumptionError) as error:
        _require_population_resource_rows(
            db,
            analysis_id=analysis_id,
            organization_id=uuid4(),
            observations=[_observation(analysis_id=analysis_id, resource_id=resource_id)],
        )

    assert error.value.code == "POPULATION_RESOURCE_MISSING"


def test_worker_population_lineage_rejects_resource_owned_by_another_tenant():
    analysis_id = uuid4()
    organization_id = uuid4()
    resource_id = uuid4()
    foreign_resource = SimpleNamespace(id=resource_id, organization_id=uuid4())

    with pytest.raises(ResourceConsumptionError) as error:
        _require_population_resource_rows(
            _ResourceSession([foreign_resource]),
            analysis_id=analysis_id,
            organization_id=organization_id,
            observations=[_observation(analysis_id=analysis_id, resource_id=resource_id)],
        )

    assert error.value.code == "POPULATION_RESOURCE_TENANT_MISMATCH"


@pytest.mark.parametrize("resource_owner", ["organization", "global"])
def test_worker_population_lineage_accepts_owned_or_shared_resource(resource_owner):
    analysis_id = uuid4()
    organization_id = uuid4()
    resource_id = uuid4()
    resource = SimpleNamespace(
        id=resource_id,
        organization_id=organization_id if resource_owner == "organization" else None,
    )

    result = _require_population_resource_rows(
        _ResourceSession([resource]),
        analysis_id=analysis_id,
        organization_id=organization_id,
        observations=[_observation(analysis_id=analysis_id, resource_id=resource_id)],
    )

    assert result == {resource_id: resource}


def test_worker_population_lineage_rejects_observation_from_another_analysis():
    with pytest.raises(ResourceConsumptionError) as error:
        _require_population_resource_rows(
            _ResourceSession([]),
            analysis_id=uuid4(),
            organization_id=uuid4(),
            observations=[_observation(analysis_id=uuid4(), resource_id=uuid4())],
        )

    assert error.value.code == "POPULATION_ANALYSIS_LINEAGE_INVALID"
