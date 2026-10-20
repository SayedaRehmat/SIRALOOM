from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from backend.app.api.v1 import cases as cases_api
from backend.app.auth.principal import Principal
from backend.app.domain.case_workspace import SpecimenCreate


class DuplicateSpecimenSession:
    def __init__(self, case, existing):
        self.case = case
        self.existing = existing
        self.added = []
        self.scalar_calls = 0
        self.rolled_back = False

    def get(self, model, identity):
        return self.case

    def add(self, item):
        self.added.append(item)

    def scalar(self, statement):
        self.scalar_calls += 1
        return self.existing

    def commit(self):
        raise IntegrityError("INSERT INTO specimens", {}, RuntimeError("unique violation"))

    def rollback(self):
        self.rolled_back = True


class NoopAudit:
    def __init__(self, db):
        self.db = db

    def record(self, **kwargs):
        return uuid4()


def test_duplicate_specimen_identity_is_a_conflict_not_a_server_error(monkeypatch):
    organization_id = uuid4()
    case_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    existing = SimpleNamespace(id=uuid4(), specimen_identifier="S-001")
    db = DuplicateSpecimenSession(case, existing)
    monkeypatch.setattr(cases_api, "AuditService", NoopAudit)
    monkeypatch.setattr(cases_api, "require_case_permission", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        cases_api.create_specimen(
            case_id=case_id,
            payload=SpecimenCreate(specimen_identifier="S-001", specimen_type="blood"),
            db=db,
            principal=Principal(
                user_id=uuid4(),
                organization_id=organization_id,
                role="organization_admin",
                subject="verified-subject",
            ),
        )

    assert error.value.status_code == 409
    assert error.value.detail == "A specimen with this identifier already exists in the case"
    assert db.rolled_back is True
    assert db.scalar_calls == 1
