from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.workflows.variant import ResourceConsumptionError, _require_registered_resource


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get(self, _model, resource_id):
        return self.rows.get(resource_id)


def _resource(*, resource_id, resource_type="POPULATION", genome_build="GRCh38", provider="GeneBe", status="ACTIVE"):
    return SimpleNamespace(
        id=resource_id,
        resource_type=resource_type,
        genome_build=genome_build,
        provider=provider,
        status=status,
    )


def test_registered_population_resource_is_consumed_by_id():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id)

    result = _require_registered_resource(
        FakeDB({resource_id: resource}),
        resource_id=resource_id,
        expected_type="POPULATION",
        expected_build="GRCh38",
        expected_provider="GeneBe",
    )

    assert result is resource


@pytest.mark.parametrize(
    ("resource_id", "expected_type", "expected_build", "expected_provider", "resource", "code"),
    [
        (None, "POPULATION", "GRCh38", "GeneBe", None, "RESOURCE_REQUIRED"),
        (uuid4(), "POPULATION", "GRCh38", "GeneBe", None, "RESOURCE_NOT_FOUND"),
        (uuid4(), "POPULATION", "GRCh38", "GeneBe", "wrong-type", "RESOURCE_TYPE_MISMATCH"),
    ],
)
def test_resource_selection_fails_closed(resource_id, expected_type, expected_build, expected_provider, resource, code):
    if resource == "wrong-type":
        resource = _resource(resource_id=resource_id, resource_type="ANNOTATION")
    db = FakeDB({resource_id: resource}) if resource_id and resource is not None else FakeDB({})

    with pytest.raises(ResourceConsumptionError) as exc:
        _require_registered_resource(
            db,
            resource_id=resource_id,
            expected_type=expected_type,
            expected_build=expected_build,
            expected_provider=expected_provider,
        )

    assert exc.value.code == code


def test_superseded_pinned_resource_remains_reproducible():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id, status="SUPERSEDED")

    result = _require_registered_resource(
        FakeDB({resource_id: resource}),
        resource_id=resource_id,
        expected_type="POPULATION",
        expected_build="GRCh38",
        expected_provider="GeneBe",
    )

    assert result.status == "SUPERSEDED"


def test_build_and_provider_mismatch_are_rejected():
    resource_id = uuid4()
    db = FakeDB({
        resource_id: _resource(
            resource_id=resource_id,
            genome_build="GRCh37",
            provider="OtherProvider",
        )
    })

    with pytest.raises(ResourceConsumptionError) as exc:
        _require_registered_resource(
            db,
            resource_id=resource_id,
            expected_type="POPULATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
        )

    assert exc.value.code == "RESOURCE_BUILD_MISMATCH"
