import pytest
from uuid import uuid4

from backend.app.reporting.finalization import ReportFinalizationError, finalize_report
from backend.app.reporting.service import REPORT_STATUS_FINAL
from backend.app.infrastructure.db.models import Report


def test_older_report_cannot_finalize_after_newer_report_is_final():
    from tests.test_reporting_signout import seed_finalizable_report

    db, reviewer, analysis, report = seed_finalizable_report()
    newer = Report(
        id=uuid4(),
        case_id=report.case_id,
        analysis_id=analysis.id,
        report_version=2,
        language=report.language,
        report_type=report.report_type,
        status=REPORT_STATUS_FINAL,
        artifact_id=report.artifact_id,
        content_json=dict(report.content_json),
        approved_by=reviewer.id,
    )
    db.add(newer)
    db.commit()

    with pytest.raises(ReportFinalizationError, match="newer finalized version 2"):
        finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Attempt to finalize stale report",
        )
