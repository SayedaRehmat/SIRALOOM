from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException


@pytest.mark.parametrize("endpoint", ["qualify_resource", "activate_resource"])
def test_tenant_operator_cannot_mutate_shared_global_resource(monkeypatch, endpoint):
    from backend.app.api.v1 import resources

    resource = SimpleNamespace(id=uuid4(), organization_id=None)
    principal = SimpleNamespace(role="lab_director", organization_id=uuid4())

    class DB:
        def get(self, model, resource_id):
            assert model is resources.Resource
            assert resource_id == resource.id
            return resource

    with pytest.raises(HTTPException) as exc:
        getattr(resources, endpoint)(resource.id, {}, DB(), principal)
    assert exc.value.status_code == 404


def test_platform_administrator_can_access_global_resource_lifecycle():
    from backend.app.api.v1.resources import _require_resource_lifecycle_access

    resource = SimpleNamespace(organization_id=None)
    principal = SimpleNamespace(role="platform_admin", organization_id=uuid4())

    assert _require_resource_lifecycle_access(resource, principal) is resource
