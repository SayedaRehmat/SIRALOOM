from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from backend.app.api.v1 import reports as reports_api
from backend.app.auth.principal import Principal
from backend.app.domain.schemas import ReportCreate
from backend.app.infrastructure.artifacts import compensation as compensation_api
from backend.app.infrastructure.db.models import Artifact


class _Database:
    def __init__(self, case):
        self.case = case
        self.rollbacks = 0

    def get(self, model, *_args, **_kwargs):
        return self.case

    def refresh(self, *_args, **_kwargs):
        pass

    def scalar(self, *_args, **_kwargs):
        return 0

    def add(self, *_args, **_kwargs):
        pass

    def flush(self):
        pass

    def commit(self):
        raise IntegrityError("insert report", {}, RuntimeError("unique conflict"))

    def rollback(self):
        self.rollbacks += 1


class _Store:
    def __init__(self):
        self.deleted = []

    def put_file(self, *, case_id, analysis_id, filename, **_kwargs):
        self.artifact = Artifact(
            id=uuid4(),
            case_id=case_id,
            analysis_id=analysis_id,
            artifact_type="REPORT_PDF",
            filename=filename,
            size_bytes=3,
            sha256="a" * 64,
            storage_uri="file:///artifact/draft-report.pdf",
            validation_status="VALID",
            metadata_json={},
        )
        return self.artifact

    def delete(self, storage_uri):
        self.deleted.append(storage_uri)


class _VerificationSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, *_args):
        return None


def test_report_route_removes_draft_bytes_after_confirmed_commit_rollback(monkeypatch):
    case_id = uuid4()
    analysis_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id, reference_build="GRCh38")
    db = _Database(case)
    store = _Store()
    monkeypatch.setattr(reports_api, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reports_api, "final_report_eligibility", lambda *_args, **_kwargs: (True, []))
    monkeypatch.setattr(reports_api, "build_report_content", lambda *_args, **_kwargs: {"report_schema_version": "1"})
    monkeypatch.setattr(reports_api, "render_pdf", lambda _content: b"pdf")
    monkeypatch.setattr(reports_api, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(reports_api, "AuditService", lambda _db: SimpleNamespace(record=lambda **_kwargs: None))
    monkeypatch.setattr(compensation_api, "SessionLocal", _VerificationSession)

    with pytest.raises(HTTPException) as error:
        reports_api.create_report(
            analysis_id,
            ReportCreate(),
            db,
            Principal(user_id=uuid4(), organization_id=case.organization_id, role="lab_scientist", subject="test"),
        )

    assert error.value.status_code == 409
    assert db.rollbacks == 1
    assert store.deleted == ["file:///artifact/draft-report.pdf"]
