from uuid import uuid4

from sqlalchemy import select

from backend.app.domain.enums import AnalysisStatus
from backend.app.infrastructure.db.models import Analysis, AnalysisDispatch, Report
from tests.test_reporting_signout import seed_finalizable_report


def test_final_report_signout_creates_durable_workflow_resume(monkeypatch, tmp_path):
    """The production sign-out route must persist a resume intent after FINAL."""
    from backend.app.api.v1 import reports as reports_api
    from backend.app.infrastructure.queue import celery_app

    db, reviewer, analysis, report = seed_finalizable_report()
    analysis.status = AnalysisStatus.REQUIRES_REVIEW
    analysis.completed_at = None
    analysis.queue_task_id = None
    db.commit()

    monkeypatch.setattr(
        "backend.app.reporting.finalization.settings.artifact_root",
        str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(
        reports_api,
        "get_accessible_report",
        lambda report_id, session, _principal: session.get(Report, report_id),
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
        {"user_id": reviewer.id, "organization_id": analysis.case_id},
    )()

    result = reports_api.finalize(
        report.id,
        reports_api.ClassificationReviewRequest(
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
    assert dispatches[0].status == "PUBLISHED"
    assert analysis.queue_task_id == str(dispatches[0].task_id)
    assert published == [str(dispatches[0].id)]
    db.close()
