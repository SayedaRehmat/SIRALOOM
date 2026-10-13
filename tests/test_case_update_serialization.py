from types import SimpleNamespace
from uuid import uuid4

from backend.app.api.v1 import cases as cases_api
from backend.app.auth.principal import Principal
from backend.app.domain.case_workspace import CaseUpdate
from backend.app.infrastructure.db.models import Case


class CaseUpdateSession:
    def __init__(self, case):
        self.case = case
        self.get_calls = []
        self.committed = False

    def get(self, model, identity, **kwargs):
        self.get_calls.append((model, identity, kwargs))
        return self.case

    def commit(self):
        self.committed = True


class NoopAudit:
    def __init__(self, db):
        self.db = db

    def record(self, **kwargs):
        return uuid4()


def test_case_update_locks_row_before_mutating_clinical_metadata(monkeypatch):
    organization_id = uuid4()
    case_id = uuid4()
    case = SimpleNamespace(
        id=case_id,
        organization_id=organization_id,
        case_identifier="CASE-LOCK-1",
        status="OPEN",
        language="en",
        clinical_context={"phenotype": ["HP:0001250"]},
        updated_at=None,
    )
    db = CaseUpdateSession(case)
    monkeypatch.setattr(cases_api, "AuditService", NoopAudit)
    monkeypatch.setattr(cases_api, "_case_payload", lambda session, row: {"case_id": str(row.id)})

    result = cases_api.update_case(
        case_id=case_id,
        payload=CaseUpdate(language="ar"),
        db=db,
        principal=Principal(
            user_id=uuid4(),
            organization_id=organization_id,
            role="organization_admin",
            subject="verified-subject",
        ),
    )

    assert db.get_calls == [(Case, case_id, {"with_for_update": True})]
    assert case.language == "ar"
    assert case.clinical_context == {"phenotype": ["HP:0001250"]}
    assert db.committed is True
    assert result == {"case_id": str(case_id)}
