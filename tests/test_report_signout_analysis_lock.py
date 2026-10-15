"""Ensure sign-out validates decisions while holding their shared analysis lock."""

from uuid import uuid4

import pytest

from backend.app.infrastructure.db.models import Analysis, Artifact, Case
from backend.app.reporting import finalization
from backend.app.reporting.finalization import ReportFinalizationError
from tests.test_reporting_signout import seed_finalizable_report


def test_report_finalization_locks_analysis_before_eligibility_validation(monkeypatch):
    db, _reviewer, analysis, report = seed_finalizable_report()
    events = []
    real_get = db.get
    real_eligibility = finalization.final_report_eligibility

    def observed_get(entity, ident, **kwargs):
        if entity is Analysis and ident == analysis.id and kwargs.get("with_for_update"):
            events.append("analysis_locked")
        return real_get(entity, ident, **kwargs)

    def observed_eligibility(session, *, analysis_id):
        events.append("eligibility_checked")
        return real_eligibility(session, analysis_id=analysis_id)

    monkeypatch.setattr(db, "get", observed_get)
    monkeypatch.setattr(finalization, "final_report_eligibility", observed_eligibility)
    monkeypatch.setattr(finalization, "_verify_report_snapshot", lambda *_args: None)
    monkeypatch.setattr(
        finalization,
        "_persist_pdf_artifact",
        lambda _db, *, report, **_kwargs: real_get(Artifact, report.artifact_id),
    )

    finalized = finalization.finalize_report(
        db,
        report_id=report.id,
        approver_id=_reviewer.id,
        reason="Authorized sign-out after current review.",
    )

    assert finalized.status == "FINAL"
    assert events.index("analysis_locked") < events.index("eligibility_checked")
    db.close()


def test_report_finalization_rejects_analysis_from_another_case():
    db, reviewer, _analysis, report = seed_finalizable_report()
    unrelated_case = Case(
        id=uuid4(),
        organization_id=reviewer.organization_id,
        case_identifier="UNRELATED-REPORT-CASE",
        status="ACTIVE",
        clinical_context={},
        language="en",
        created_by=reviewer.id,
    )
    db.add(unrelated_case)
    db.flush()
    report.case_id = unrelated_case.id
    db.commit()

    with pytest.raises(ReportFinalizationError, match="Report analysis not found"):
        finalization.finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Reject mismatched report lineage.",
        )
    db.close()
