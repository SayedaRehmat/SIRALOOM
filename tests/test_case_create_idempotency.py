from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

import backend.app.api.v1.cases as cases_api
from backend.app.api.v1.cases import create
from backend.app.auth.principal import Principal
from backend.app.domain.schemas import CaseCreate
from backend.app.infrastructure.db.models import CaseAccessGrant


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
        language="en",
        clinical_context={},
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


def test_concurrent_duplicate_case_create_rejects_metadata_collision(monkeypatch):
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        case_identifier="CASE-2026-005",
        status="DRAFT",
        language="en",
        clinical_context={"indication": "existing indication"},
    )
    db = ConcurrentDuplicateSession(existing_case=existing)
    principal = Principal(
        user_id=uuid4(),
        organization_id=existing.organization_id,
        role="bioinformatician",
        subject="test-subject",
    )
    monkeypatch.setattr("backend.app.api.v1.cases.require_case_permission", lambda *_args: None)

    with pytest.raises(HTTPException) as error:
        create(
            CaseCreate(
                case_identifier="CASE-2026-005",
                clinical_context={"indication": "different indication"},
            ),
            db=db,
            principal=principal,
        )

    assert error.value.status_code == 409
    assert db.rollback_called is True
    assert db.committed is False


def test_existing_case_create_is_idempotent_for_matching_metadata(monkeypatch):
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        case_identifier="CASE-2026-003",
        status="DRAFT",
        language="en",
        clinical_context={"indication": "developmental delay"},
    )

    class _Db:
        def scalar(self, _statement):
            return existing

    monkeypatch.setattr("backend.app.api.v1.cases.require_case_permission", lambda *_args: None)
    result = create(
        CaseCreate(
            case_identifier="CASE-2026-003",
            clinical_context={"indication": "developmental delay"},
        ),
        db=_Db(),
        principal=_principal(),
    )

    assert result["case_id"] == str(existing.id)
    assert result["created"] is False


@pytest.mark.parametrize(
    ("language", "clinical_context"),
    [
        ("en", {"indication": "different indication"}),
        ("ar", {"indication": "developmental delay"}),
    ],
)
def test_existing_case_create_rejects_conflicting_metadata(monkeypatch, language, clinical_context):
    existing = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        case_identifier="CASE-2026-004",
        status="DRAFT",
        language="en",
        clinical_context={"indication": "developmental delay"},
    )

    class _Db:
        def scalar(self, _statement):
            return existing

    monkeypatch.setattr("backend.app.api.v1.cases.require_case_permission", lambda *_args: None)
    with pytest.raises(HTTPException) as error:
        create(
            CaseCreate(
                case_identifier="CASE-2026-004",
                language=language,
                clinical_context=clinical_context,
            ),
            db=_Db(),
            principal=_principal(),
        )

    assert error.value.status_code == 409
    assert "different clinical metadata" in error.value.detail


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


def test_case_creator_only_receives_review_grant_when_role_allows_review(monkeypatch):
    class _Db:
        def __init__(self):
            self.rows = []
            self.commits = 0

        def scalar(self, _statement):
            return None

        def add(self, row):
            self.rows.append(row)

        def flush(self):
            pass

        def commit(self):
            self.commits += 1

    class _Audit:
        def record(self, **_kwargs):
            pass

    db = _Db()
    monkeypatch.setattr(cases_api, "AuditService", lambda _db: _Audit())
    principal = _principal()

    result = create(CaseCreate(case_identifier="CASE-ASSIGNMENT-001"), db, principal)

    grant = next(row for row in db.rows if isinstance(row, CaseAccessGrant))
    assert result["created"] is True
    assert grant.can_read is True
    assert grant.can_write is True
    assert grant.can_review is False
    assert db.commits == 1
