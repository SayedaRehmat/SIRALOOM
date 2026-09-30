from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.resources import ResourceRegistryError, register_resource_version


class FakeDB:
    def __init__(self):
        self.rows = []

    def scalar(self, query):
        return None

    def scalars(self, query):
        class Result:
            def all(self_inner):
                return []
        return Result()

    def add(self, row):
        self.rows.append(row)

    def flush(self):
        return None


def test_reference_package_is_an_allowed_resource_type():
    db = FakeDB()
    resource, created = register_resource_version(
        db,
        name="GRCh38 reference package",
        provider="SIRALOOM_REFERENCE",
        resource_type="reference_package",
        version="GRCh38-test-1",
        genome_build="GRCh38",
        access_method="LOCAL",
        license_text=None,
        checksum="a" * 64,
        location="/references/GRCh38",
        population_definition=None,
        metadata_json={"schema_version": "1.0"},
    )
    assert created is True
    assert resource.resource_type == "REFERENCE_PACKAGE"


def test_unknown_resource_type_is_rejected():
    with pytest.raises(ResourceRegistryError, match="unsupported resource_type"):
        register_resource_version(
            FakeDB(),
            name="Bad",
            provider="Test",
            resource_type="NOT_A_RESOURCE",
            version="1",
            genome_build=None,
            access_method="LOCAL",
            license_text=None,
            checksum="a" * 64,
            location="/tmp",
            population_definition=None,
        )
