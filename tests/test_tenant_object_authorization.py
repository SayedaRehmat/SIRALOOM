from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.auth.authorization import (
    get_accessible_analysis,
    get_accessible_artifact,
    get_accessible_case,
    get_accessible_report,
)
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Report


class TenantObjectSession:
    def __init__(self, rows):
        self.rows = rows

    def get(self, model, _object_id):
        return self.rows.get(model)


@pytest.mark.parametrize("object_kind", ["case", "analysis", "artifact", "report"])
@pytest.mark.parametrize("same_tenant", [True, False])
def test_shared_object_accessors_enforce_case_tenant_boundary(object_kind, same_tenant):
    tenant_id = uuid4()
    other_tenant_id = uuid4()
    case_id = uuid4()
    object_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=tenant_id if same_tenant else other_tenant_id)
    analysis = SimpleNamespace(id=object_id, case_id=case_id)
    artifact = SimpleNamespace(id=object_id, case_id=case_id)
    report = SimpleNamespace(id=object_id, case_id=case_id)
    db = TenantObjectSession({
        Case: case,
        Analysis: analysis,
        Artifact: artifact,
        Report: report,
    })
    principal = Principal(
        user_id=uuid4(), organization_id=tenant_id,
        role="read_only", subject="verified-subject",
    )
    accessors = {
        "case": (get_accessible_case, case),
        "analysis": (get_accessible_analysis, analysis),
        "artifact": (get_accessible_artifact, artifact),
        "report": (get_accessible_report, report),
    }
    accessor, expected = accessors[object_kind]

    if same_tenant:
        assert accessor(object_id, db=db, principal=principal) is expected
    else:
        with pytest.raises(HTTPException) as error:
            accessor(object_id, db=db, principal=principal)
        assert error.value.status_code == 404
