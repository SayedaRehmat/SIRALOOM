from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from backend.app.api.v1.reports import get_export
from backend.app.auth.principal import Principal
from backend.app.infrastructure.db.models import Case, CaseExport
from backend.app.reporting import export_task


def test_export_failure_persists_and_audits_only_safe_diagnostics(monkeypatch):
    export_id = uuid4()
    case = type("CaseRow", (), {"organization_id": uuid4()})()
    export = type(
        "Export",
        (),
        {
            "id": export_id,
            "case_id": uuid4(),
            "status": "RUNNING",
            "artifact_id": None,
        },
    )()
    events = []

    class FakeDB:
        def get(self, model, requested_id, **kwargs):
            if model is CaseExport:
                assert requested_id == export_id
                return export
            if model is Case:
                return case
            raise AssertionError(f"Unexpected model lookup: {model}")

        def commit(self):
            events.append(("commit", export.error_message))

        def rollback(self):
            events.append(("rollback", None))

        def close(self):
            pass

    class FakeAudit:
        def __init__(self, db):
            pass

        def record(self, **kwargs):
            events.append(("audit", kwargs))

    class FakeError(RuntimeError):
        pass

    monkeypatch.setattr(export_task, "SessionLocal", FakeDB)
    monkeypatch.setattr(export_task, "AuditService", FakeAudit)
    monkeypatch.setattr(
        export_task,
        "artifact_store_for_organization",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            FakeError("secret-token /srv/private/sample.vcf https://internal-store")
        ),
    )
    export_task.run_case_export(export_id)

    assert export.status == "FAILED"
    assert export.error_code == "CASE_EXPORT_FAILED"
    assert export.error_message == "Case export failed. Contact a laboratory administrator."
    audit = next(payload for kind, payload in events if kind == "audit")
    assert audit["reason"] == "Case export failed."
    assert audit["payload"] == {"error_type": "FakeError"}
    audit_index = next(index for index, (kind, payload) in enumerate(events) if kind == "audit")
    failure_rollback_index = max(
        index for index, (kind, _payload) in enumerate(events) if kind == "rollback"
    )
    terminal_commit_index = next(
        index
        for index, (kind, _payload) in enumerate(events)
        if index > failure_rollback_index and kind == "commit"
    )
    assert audit_index < terminal_commit_index
    assert all(
        "secret-token" not in str(value)
        and "/srv/private" not in str(value)
        and "internal-store" not in str(value)
        for _, value in events
    )


def test_export_status_never_returns_persisted_raw_failure_text(monkeypatch):
    export_id, case_id, organization_id, user_id = (uuid4() for _ in range(4))
    export = type(
        "Export",
        (),
        {
            "id": export_id,
            "case_id": case_id,
            "status": "FAILED",
            "artifact_id": None,
            "error_code": "CASE_EXPORT_FAILED",
            "error_message": "legacy-secret /srv/private/sample.vcf",
            "created_at": datetime.now(timezone.utc),
            "completed_at": datetime.now(timezone.utc),
        },
    )()
    case = type("CaseRow", (), {"organization_id": organization_id})()

    class FakeDB:
        def get(self, model, requested_id):
            return export if requested_id == export_id else case

    from backend.app.api.v1 import reports
    monkeypatch.setattr(reports, "require_case_permission", lambda *_args: None)
    result = get_export(
        export_id,
        db=FakeDB(),
        principal=Principal(user_id, organization_id, "read_only", str(user_id)),
    )

    assert result["error_message"] == "Case export failed. Contact a laboratory administrator."
    assert "legacy-secret" not in result["error_message"]
