from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app.api.v1.cases import create
from backend.app.auth.principal import Principal
from backend.app.domain.schemas import CaseCreate


class ConcurrentDuplicateSession:
    """Models the losing transaction after a concurrent unique-key insert."""

    def __init__(self, existing_case=None):
        self.existing_case = existing_case
        self.scalar_calls = 0
        self.rollback_called = False
        self.committed = False

    def scalar(self, statement):
        self.scalar_calls += 1
        if self.scalar_calls == 1:
            return None
        return self.existing_case

    def add(self, value):
        pass

    def flush(self):
        raise IntegrityError("INSERT INTO cases", {}, Exception("unique constraint"))

    def rollback(self):
        self.rollback_called = True

    def commit(self):
        self.committed = True


def _principal() -> Principal:
    return Principal(
        user_id=uuid4(),
        organization_id=uuid4(),
        role="bioinformatician",
        subject="test-subject",
    )


def test_concurrent_duplicate_case_create_returns_existing_case(monkeypatch):
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        case_identifier="CASE-2026-001",
        status="DRAFT",
    )
    db = ConcurrentDuplicateSession(existing_case=existing)
    principal = Principal(
        user_id=uuid4(),
        organization_id=existing.organization_id,
        role="bioinformatician",
        subject="test-subject",
    )
    monkeypatch.setattr("backend.app.api.v1.cases.require_case_permission", lambda *_args: None)

    result = create(
        CaseCreate(case_identifier="CASE-2026-001"),
        db=db,
        principal=principal,
    )

    assert result == {
        "case_id": str(existing.id),
        "case_identifier": "CASE-2026-001",
        "status": "DRAFT",
        "created": False,
    }
    assert db.rollback_called is True
    assert db.committed is False
    assert db.scalar_calls == 2


def test_unrelated_integrity_error_is_not_misreported_as_duplicate_case():
    db = ConcurrentDuplicateSession(existing_case=None)

    with pytest.raises(IntegrityError):
        create(
            CaseCreate(case_identifier="CASE-2026-002"),
            db=db,
            principal=_principal(),
        )

    assert db.rollback_called is True
    assert db.scalar_calls == 2
