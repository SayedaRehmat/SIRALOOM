import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.domain.enums import AnalysisStatus
from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.report_integrity import has_valid_signed_artifact
from backend.app.infrastructure.db.models import (
    AnalysisDispatch,
    Artifact,
    AuditEvent,
    Report,
)
from tests.test_reporting_signout import seed_finalizable_report


def test_final_report_signout_creates_durable_workflow_resume(monkeypatch, tmp_path):
    """The production sign-out route must persist a resume intent after FINAL."""
    from backend.app.api.v1 import reports as reports_api
    from backend.app.infrastructure.queue import celery_app
    from backend.app.reporting import finalization

    db, reviewer, analysis, report = seed_finalizable_report()
    analysis.status = AnalysisStatus.REQUIRES_REVIEW
    analysis.completed_at = None
    analysis.queue_task_id = None
    db.commit()

    monkeypatch.setattr(
        "backend.app.config.settings.artifact_root",
        str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(finalization, "render_pdf", lambda _content: b"%PDF-test-signout%")
    monkeypatch.setattr(
        reports_api,
        "get_accessible_report",
        lambda report_id, session, _principal, *_args: session.get(Report, report_id),
    )
    monkeypatch.setattr(reports_api, "require_role", lambda *_args, **_kwargs: None)

    published = []
    monkeypatch.setattr(
        celery_app,
        "publish_analysis_dispatch",
        lambda dispatch_id: published.append(str(dispatch_id)) or str(dispatch_id),
    )
    principal = type(
        "Principal",
        (),
        {"user_id": reviewer.id, "organization_id": reviewer.organization_id},
    )()

    result = reports_api.finalize(
        report.id,
        reports_api.ClassificationReviewRequest(
            expected_version=1,
            reason="Final clinical report reviewed and authorized for sign-out."
        ),
        db,
        principal,
    )

    db.refresh(analysis)
    db.refresh(report)
    dispatches = list(db.scalars(
        select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis.id)
    ))

    assert result["status"] == "FINAL"
    assert result["workflow_resume_queued"] is True
    assert report.status == "FINAL"
    assert report.approved_by == reviewer.id
    assert report.signed_artifact_id is not None
    assert report.signed_sha256
    assert analysis.status == AnalysisStatus.QUEUED
    assert len(dispatches) == 1
    assert dispatches[0].status == "PENDING"
    assert analysis.queue_task_id == str(dispatches[0].id)
    assert published == [str(dispatches[0].id)]
    db.close()


def test_signout_recovers_after_filesystem_write_before_database_commit(
    monkeypatch, tmp_path
):
    """A retry repairs the DB link after a worker dies with a signed file on disk."""
    from backend.app.reporting import finalization

    db, reviewer, _analysis, report = seed_finalizable_report()
    monkeypatch.setattr(
        "backend.app.config.settings.artifact_root",
        str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(finalization, "render_pdf", lambda _content: b"%PDF-filesystem-replay%")
    real_persist_pdf_artifact = finalization._persist_pdf_artifact
    worker_loss = {"artifact": None}

    def lose_worker_after_artifact_flush(*args, **kwargs):
        artifact = real_persist_pdf_artifact(*args, **kwargs)
        worker_loss["artifact"] = artifact
        raise SystemExit(87)

    monkeypatch.setattr(
        finalization, "_persist_pdf_artifact", lose_worker_after_artifact_flush
    )
    with pytest.raises(SystemExit, match="87"):
        finalization.finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Authorized laboratory sign-out",
        )

    orphan_path = local_path_from_uri(worker_loss["artifact"].storage_uri)
    assert orphan_path is not None and orphan_path.is_file()
    assert db.get(Artifact, worker_loss["artifact"].id) is not None
    db.rollback()
    db.refresh(report)
    assert report.status == "DRAFT"
    assert report.signed_artifact_id is None
    assert db.get(Artifact, worker_loss["artifact"].id) is None
    # The filesystem write cannot participate in the SQL transaction. A real
    # process loss leaves an orphan until this deterministic retry reuses it.
    assert orphan_path.is_file()

    monkeypatch.setattr(
        finalization, "_persist_pdf_artifact", real_persist_pdf_artifact
    )
    signed = finalization.finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Authorized laboratory sign-out",
    )
    db.commit()

    assert signed.status == "FINAL"
    assert signed.signed_artifact_id == worker_loss["artifact"].id
    assert signed.signed_sha256 == worker_loss["artifact"].sha256
    assert has_valid_signed_artifact(db, signed)
    assert db.scalar(select(func.count(Artifact.id)).where(
        Artifact.id == signed.signed_artifact_id,
    )) == 1
    assert db.scalar(select(func.count(AuditEvent.id)).where(
        AuditEvent.analysis_id == signed.analysis_id,
        AuditEvent.event_type == "REPORT_APPROVED",
    )) == 1
    assert orphan_path.read_bytes() == b"%PDF-filesystem-replay%"
    db.close()



def test_repeated_signout_after_analysis_succeeded_is_idempotent(monkeypatch, tmp_path):
    """A lost response followed by a retry must not turn a final report into HTTP 409."""
    from backend.app.api.v1 import reports as reports_api
    from backend.app.reporting import finalization

    db, reviewer, analysis, report = seed_finalizable_report()
    analysis.status = AnalysisStatus.SUCCEEDED
    db.commit()

    monkeypatch.setattr(
        "backend.app.config.settings.artifact_root",
        str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(finalization, "render_pdf", lambda _content: b"%PDF-test-signout%")
    monkeypatch.setattr(
        reports_api,
        "get_accessible_report",
        lambda report_id, session, _principal, *_args: session.get(Report, report_id),
    )
    monkeypatch.setattr(reports_api, "require_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        reports_api,
        "artifact_store_for_organization",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a committed sign-out retry must not resolve storage")
        ),
    )

    # Simulate the original request having committed successfully while its
    # response was lost, then the client retrying the same finalize endpoint.
    signed = finalization.finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Initial authorized sign-out",
    )
    db.commit()
    signed_artifact_id = signed.signed_artifact_id
    signed_sha256 = signed.signed_sha256
    artifact_count_before_retry = len(list(db.scalars(select(Artifact))))

    principal = type(
        "Principal",
        (),
        {"user_id": reviewer.id, "organization_id": reviewer.organization_id},
    )()
    result = reports_api.finalize(
        report.id,
        reports_api.ClassificationReviewRequest(
            expected_version=1,
            reason="Retry after a lost response",
        ),
        db,
        principal,
    )

    db.refresh(analysis)
    db.refresh(report)
    assert result["status"] == "FINAL"
    assert result["workflow_resume_queued"] is False
    assert report.status == "FINAL"
    assert report.signed_artifact_id == signed_artifact_id
    assert report.signed_sha256 == signed_sha256
    assert analysis.status == AnalysisStatus.SUCCEEDED
    assert len(list(db.scalars(select(Artifact)))) == artifact_count_before_retry
    assert list(db.scalars(select(AnalysisDispatch).where(AnalysisDispatch.analysis_id == analysis.id))) == []
    db.close()


def test_stale_report_version_cannot_be_signed_out(monkeypatch):
    from backend.app.api.v1 import reports as reports_api
    from backend.app.infrastructure.db.models import AuditEvent

    db, reviewer, _analysis, report = seed_finalizable_report()
    monkeypatch.setattr(
        reports_api,
        "get_accessible_report",
        lambda report_id, session, _principal, *_args: session.get(Report, report_id),
    )
    monkeypatch.setattr(reports_api, "require_role", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        reports_api,
        "artifact_store_for_organization",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stale sign-out must be rejected before resolving storage")
        ),
    )
    principal = type(
        "Principal",
        (),
        {"user_id": reviewer.id, "organization_id": reviewer.organization_id},
    )()

    with pytest.raises(HTTPException) as error:
        reports_api.finalize(
            report.id,
            reports_api.ClassificationReviewRequest(
                expected_version=report.report_version + 1,
                reason="Stale approval must not sign out this report version.",
            ),
            db,
            principal,
        )

    db.refresh(report)
    assert error.value.status_code == 409
    assert "Refresh the report" in error.value.detail
    assert report.status == "DRAFT"
    assert report.signed_artifact_id is None
    assert db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.event_type == "REPORT_APPROVED",
            AuditEvent.analysis_id == report.analysis_id,
        )
    ) is None
    db.close()
