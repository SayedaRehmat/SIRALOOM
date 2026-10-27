from types import SimpleNamespace
from uuid import uuid4, uuid5

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from backend.app.api.v1 import reports as reports_api
from backend.app.auth.principal import Principal
from backend.app.domain.report_integrity import (
    REPORT_CONTENT_INTEGRITY_VERSION,
    report_content_sha256,
)
from backend.app.domain.schemas import ReportCreate
from backend.app.infrastructure.artifacts import compensation as compensation_api
from backend.app.infrastructure.db.models import Analysis, Artifact, Case


class _Database:
    def __init__(self, case, analysis):
        self.case = case
        self.analysis = analysis
        self.rollbacks = 0
        self.lock_events = []

    def get(self, model, *_args, **kwargs):
        if model is Analysis:
            if kwargs.get("with_for_update"):
                self.lock_events.append("analysis_locked")
            return self.analysis
        if model is Case:
            if kwargs.get("with_for_update"):
                self.lock_events.append("case_locked")
            return self.case
        return None

    def refresh(self, row, **kwargs):
        assert kwargs.get("with_for_update") is True
        self.lock_events.append("analysis_refreshed" if row is self.analysis else "case_refreshed")

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
            metadata_json=_kwargs.get("metadata", {}),
        )
        return self.artifact

    def delete(self, storage_uri):
        self.deleted.append(storage_uri)

    def uri_for_artifact(self, *, case_id, artifact_id, filename):
        return f"file:///artifact/{case_id}/{artifact_id}/{filename}"


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
    user_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id, reference_build="GRCh38")
    db = _Database(case, analysis)
    store = _Store()
    audit_events = []
    monkeypatch.setattr(reports_api, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reports_api, "require_case_permission", lambda *_args: db.lock_events.append("write_permission_rechecked"))
    monkeypatch.setattr(reports_api, "final_report_eligibility", lambda *_args, **_kwargs: (True, []))
    monkeypatch.setattr(reports_api, "build_report_content", lambda *_args, **_kwargs: {"report_schema_version": "1"})
    monkeypatch.setattr(reports_api, "render_pdf", lambda _content: b"pdf")
    monkeypatch.setattr(reports_api, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(
        reports_api,
        "AuditService",
        lambda _db: SimpleNamespace(record=lambda **kwargs: audit_events.append(kwargs)),
    )
    monkeypatch.setattr(compensation_api, "SessionLocal", _VerificationSession)

    with pytest.raises(HTTPException) as error:
        reports_api.create_report(
            analysis_id,
            ReportCreate(),
            db,
            Principal(user_id=user_id, organization_id=case.organization_id, role="lab_scientist", subject="test"),
        )

    assert error.value.status_code == 409
    assert db.lock_events == [
        "analysis_locked",
        "analysis_refreshed",
        "case_locked",
        "case_refreshed",
        "write_permission_rechecked",
    ]
    assert db.rollbacks == 1
    assert store.deleted == ["file:///artifact/draft-report.pdf"]
    assert audit_events[0]["event_type"] == "REPORT_GENERATED"
    assert audit_events[0]["actor_type"] == "HUMAN"
    assert audit_events[0]["actor_id"] == str(user_id)
    assert store.artifact.metadata_json["report_content_integrity"] == REPORT_CONTENT_INTEGRITY_VERSION
    assert store.artifact.metadata_json["report_content_sha256"] == report_content_sha256(
        {"report_schema_version": "1", "report_version": 1}
    )


def test_report_route_removes_draft_bytes_after_audit_flush_failure(monkeypatch):
    case_id = uuid4()
    analysis_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=uuid4())
    analysis = SimpleNamespace(id=analysis_id, case_id=case_id, reference_build="GRCh38")
    db = _Database(case, analysis)
    store = _Store()
    monkeypatch.setattr(reports_api, "get_accessible_analysis", lambda *_args: analysis)
    monkeypatch.setattr(reports_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reports_api, "require_case_permission", lambda *_args: db.lock_events.append("write_permission_rechecked"))
    monkeypatch.setattr(reports_api, "final_report_eligibility", lambda *_args, **_kwargs: (True, []))
    monkeypatch.setattr(reports_api, "build_report_content", lambda *_args, **_kwargs: {"report_schema_version": "1"})
    monkeypatch.setattr(reports_api, "render_pdf", lambda _content: b"pdf")
    monkeypatch.setattr(reports_api, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(
        reports_api,
        "AuditService",
        lambda _db: SimpleNamespace(
            record=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("audit flush failed"))
        ),
    )
    monkeypatch.setattr(compensation_api, "SessionLocal", _VerificationSession)

    with pytest.raises(RuntimeError, match="audit flush failed"):
        reports_api.create_report(
            analysis_id,
            ReportCreate(),
            db,
            Principal(user_id=uuid4(), organization_id=case.organization_id, role="lab_scientist", subject="test"),
        )

    assert db.rollbacks == 1
    assert store.deleted == ["file:///artifact/draft-report.pdf"]


def test_signout_route_compensates_signed_pdf_when_finalization_fails(monkeypatch):
    case_id = uuid4()
    report_id = uuid4()
    organization_id = uuid4()
    case = SimpleNamespace(id=case_id, organization_id=organization_id)
    report = SimpleNamespace(id=report_id, case_id=case_id, report_version=3, status="DRAFT")

    class Database:
        def __init__(self):
            self.rollbacks = 0

        def get(self, model, *_args, **_kwargs):
            return case if model is reports_api.Case else None

        def rollback(self):
            self.rollbacks += 1

    db = Database()
    store = _Store()
    monkeypatch.setattr(reports_api, "get_accessible_report", lambda *_args: report)
    monkeypatch.setattr(reports_api, "require_role", lambda *_args: None)
    monkeypatch.setattr(reports_api, "artifact_store_for_organization", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(
        reports_api,
        "finalize_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit flush failed")),
    )
    monkeypatch.setattr(compensation_api, "SessionLocal", _VerificationSession)

    with pytest.raises(RuntimeError, match="audit flush failed"):
        reports_api.finalize(
            report_id,
            SimpleNamespace(expected_version=report.report_version, reason="Reviewed"),
            db,
            Principal(user_id=uuid4(), organization_id=organization_id, role="lab_director", subject="test"),
        )

    assert db.rollbacks == 1
    assert store.deleted == [
        f"file:///artifact/{case_id}/{uuid5(report_id, 'siraloom:signed-report-pdf')}/report_v3_signed.pdf"
    ]
