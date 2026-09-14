from __future__ import annotations
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Report
from backend.app.reporting.service import REPORT_STATUS_FINAL, REPORT_STATUS_SUPERSEDED, final_report_eligibility

class ReportFinalizationError(ValueError):
    pass

def finalize_report(db: Session, *, report_id: UUID, approver_id: UUID, reason: str) -> Report:
    if not reason.strip(): raise ReportFinalizationError("Approval reason is required")
    report = db.get(Report, report_id)
    if report is None: raise ReportFinalizationError("Report not found")
    if report.status == REPORT_STATUS_FINAL: return report
    if report.status != "DRAFT": raise ReportFinalizationError(f"Report cannot be finalized from status {report.status}")
    eligible, errors = final_report_eligibility(db, analysis_id=report.analysis_id)
    if not eligible: raise ReportFinalizationError("; ".join(errors))
    if not report.artifact_id:
        raise ReportFinalizationError("Report has no immutable artifact to approve")
    prior = db.scalars(select(Report).where(Report.case_id == report.case_id, Report.report_type == report.report_type, Report.status == REPORT_STATUS_FINAL).order_by(Report.report_version.desc())).first()
    before = {"status": report.status, "approved_by": str(report.approved_by) if report.approved_by else None}
    report.status = REPORT_STATUS_FINAL; report.approved_by = approver_id; report.approved_at = datetime.now(timezone.utc)
    if prior and prior.id != report.id:
        prior.status = REPORT_STATUS_SUPERSEDED
        report.supersedes_report_id = prior.id
        AuditService(db).record(
            event_type="REPORT_SUPERSEDED",
            case_id=report.case_id,
            analysis_id=report.analysis_id,
            actor_type="SYSTEM",
            actor_id="reporting",
            subject_type="REPORT",
            subject_id=str(prior.id),
            operation="SUPERSEDE",
            before_state={"status": REPORT_STATUS_FINAL},
            after_state={"status": REPORT_STATUS_SUPERSEDED},
            reason="A newer report version was finalized.",
        )
    analysis = db.get(Analysis, report.analysis_id)
    if analysis and analysis.status == "REQUIRES_REVIEW": analysis.status = "SUCCEEDED"
    after = {"status": report.status, "approved_by": str(report.approved_by), "approved_at": report.approved_at.isoformat(), "supersedes_report_id": str(report.supersedes_report_id) if report.supersedes_report_id else None}
    AuditService(db).record(event_type="REPORT_APPROVED", case_id=report.case_id, analysis_id=report.analysis_id, actor_type="HUMAN", actor_id=str(approver_id), subject_type="REPORT", subject_id=str(report.id), operation="APPROVE", before_state=before, after_state=after, reason=reason.strip())
    db.flush(); return report
