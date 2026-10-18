from types import SimpleNamespace
from uuid import uuid4

from backend.app.domain.resource_execution_plan import _bound_resources


def test_bound_resource_plan_excludes_resources_owned_by_another_organization():
    organization_id = uuid4()
    foreign_organization_id = uuid4()
    own_resource = SimpleNamespace(id=uuid4(), organization_id=organization_id)
    global_resource = SimpleNamespace(id=uuid4(), organization_id=None)
    foreign_resource = SimpleNamespace(id=uuid4(), organization_id=foreign_organization_id)
    bindings = [
        SimpleNamespace(resource_id=own_resource.id),
        SimpleNamespace(resource_id=global_resource.id),
        SimpleNamespace(resource_id=foreign_resource.id),
        SimpleNamespace(resource_id=uuid4()),
    ]

    class FakeDB:
        def scalars(self, _query):
            return SimpleNamespace(all=lambda: bindings)

        def get(self, _model, resource_id):
            return {
                own_resource.id: own_resource,
                global_resource.id: global_resource,
                foreign_resource.id: foreign_resource,
            }.get(resource_id)

    assert _bound_resources(FakeDB(), organization_id) == [
        own_resource,
        global_resource,
    ]
