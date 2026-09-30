from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.workflows.variant import ResourceConsumptionError, _require_registered_resource


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    def get(self, _model, resource_id):
        return self.rows.get(resource_id)


def _resource(
    *,
    resource_id,
    resource_type="ANNOTATION",
    genome_build="GRCh38",
    provider="GeneBe",
    status="ACTIVE",
):
    return SimpleNamespace(
        id=resource_id,
        resource_type=resource_type,
        genome_build=genome_build,
        provider=provider,
        status=status,
    )


def test_annotation_resource_must_be_registered_and_provider_build_compatible():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id)

    result = _require_registered_resource(
        FakeDB({resource_id: resource}),
        resource_id=resource_id,
        expected_type="ANNOTATION",
        expected_build="GRCh38",
        expected_provider="GeneBe",
    )

    assert result is resource


@pytest.mark.parametrize(
    ("resource_id", "resource", "code"),
    [
        (None, None, "RESOURCE_REQUIRED"),
        (uuid4(), None, "RESOURCE_NOT_FOUND"),
    ],
)
def test_annotation_resource_selection_fails_closed(resource_id, resource, code):
    rows = {resource_id: resource} if resource is not None else {}
    with pytest.raises(ResourceConsumptionError) as exc:
        _require_registered_resource(
            FakeDB(rows),
            resource_id=resource_id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
        )
    assert exc.value.code == code


def test_annotation_resource_rejects_wrong_provider():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id, provider="OtherProvider")

    with pytest.raises(ResourceConsumptionError) as exc:
        _require_registered_resource(
            FakeDB({resource_id: resource}),
            resource_id=resource_id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
        )

    assert exc.value.code == "RESOURCE_PROVIDER_MISMATCH"


def test_annotation_resource_rejects_build_mismatch():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id, genome_build="GRCh37")

    with pytest.raises(ResourceConsumptionError) as exc:
        _require_registered_resource(
            FakeDB({resource_id: resource}),
            resource_id=resource_id,
            expected_type="ANNOTATION",
            expected_build="GRCh38",
            expected_provider="GeneBe",
        )

    assert exc.value.code == "RESOURCE_BUILD_MISMATCH"


def test_annotation_resource_allows_explicitly_pinned_superseded_version():
    resource_id = uuid4()
    resource = _resource(resource_id=resource_id, status="SUPERSEDED")

    result = _require_registered_resource(
        FakeDB({resource_id: resource}),
        resource_id=resource_id,
        expected_type="ANNOTATION",
        expected_build="GRCh38",
        expected_provider="GeneBe",
    )

    assert result.status == "SUPERSEDED"
