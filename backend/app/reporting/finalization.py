from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Report
from backend.app.reporting.service import (
    REPORT_STATUS_FINAL,
    REPORT_STATUS_SUPERSEDED,
    final_report_eligibility,
    render_pdf,
)


class ReportFinalizationError(ValueError):
    pass


def _artifact_store():
    return FirebaseArtifactStore(settings.firebase_storage_bucket) if settings.firebase_storage_enabled else ArtifactStore(settings.artifact_root)


def _persist_pdf_artifact(
    db: Session,
    *,
    report: Report,
    content: dict,
    filename: str,
) -> Artifact:
    pdf = render_pdf(content)
    analysis = db.get(Analysis, report.analysis_id)
    if analysis is None:
        raise ReportFinalizationError("Report analysis not found")
    store = _artifact_store()
    with tempfile.NamedTemporaryFile(prefix="siraloom-signed-report-", suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf)
        path = Path(tmp.name)
    try:
        return store.put_file(
            db=db,
            case_id=report.case_id,
            analysis_id=report.analysis_id,
            source_path=path,
            filename=filename,
            artifact_type="REPORT_PDF",
            media_type="application/pdf",
            genome_build=analysis.reference_build,
            metadata={
                "rendered_format": "PDF",
                "report_schema_version": content["report_schema_version"],
                "report_state": "FINAL",
                "report_id": str(report.id),
                "report_version": report.report_version,
                "signed": True,
            },
            validation_status="VALID",
        )
    finally:
        path.unlink(missing_ok=True)


def finalize_report(db: Session, *, report_id: UUID, approver_id: UUID, reason: str) -> Report:
    if not reason.strip():
        raise ReportFinalizationError("Approval reason is required")
    # Serialize concurrent sign-out attempts for the same report. PostgreSQL
    # must lock the draft row before eligibility evaluation or signed-artifact
    # creation; otherwise two workers can both observe DRAFT and emit distinct
    # signed artifacts for the same report version.
    report = db.get(Report, report_id, with_for_update=True)
    if report is None:
        raise ReportFinalizationError("Report not found")
    if report.status == REPORT_STATUS_FINAL:
        return report
    if report.status != "DRAFT":
        raise ReportFinalizationError(f"Report cannot be finalized from status {report.status}")

    eligible, errors = final_report_eligibility(db, analysis_id=report.analysis_id)
    if not eligible:
        raise ReportFinalizationError("; ".join(errors))
    if not report.artifact_id:
        raise ReportFinalizationError("Report has no immutable draft artifact to approve")

    prior = db.scalars(
        select(Report)
        .where(
            Report.case_id == report.case_id,
            Report.report_type == report.report_type,
            Report.status == REPORT_STATUS_FINAL,
        )
        .order_by(Report.report_version.desc())
    ).first()

    before = {
        "status": report.status,
        "approved_by": str(report.approved_by) if report.approved_by else None,
        "artifact_id": str(report.artifact_id),
    }

    analysis = db.get(Analysis, report.analysis_id)
    if analysis is None:
        raise ReportFinalizationError("Report analysis not found")
    case = db.get(Case, report.case_id)
    signed_content = {
        "report_schema_version": "1.1.0",
        "report_version": report.report_version,
        "report_status": "DRAFT",
        "report_type": report.report_type,
        "language": report.language,
        "case_id": str(report.case_id),
        "case_identifier": case.case_identifier if case else str(report.case_id),
        "analysis_id": str(report.analysis_id),
        "reference_build": analysis.reference_build,
        "findings": [],
        "methodology": "SIRALOOM Variant interpretation report.",
        "limitations": "Clinical use requires laboratory-specific validation and qualified sign-out.",
        "references": [],
        **dict(report.content_json or {}),
    }
    signed_result = dict(signed_content.get("final_result") or {})
    signed_result["status"] = "FINAL"
    signed_result["release_state"] = "CLINICALLY_RELEASED"
    signed_result["signed_out_by"] = str(approver_id)
    signed_result["signed_out_at"] = datetime.now(timezone.utc).isoformat()
    signed_result["signout_reason"] = reason.strip()
    signed_content["report_status"] = "FINAL"
    signed_content["final_result"] = signed_result

    signed_artifact = _persist_pdf_artifact(
        db,
        report=report,
        content=signed_content,
        filename=f"report_v{report.report_version}_signed.pdf",
    )

    report.status = REPORT_STATUS_FINAL
    report.approved_by = approver_id
    report.approved_at = datetime.now(timezone.utc)
    report.signed_artifact_id = signed_artifact.id
    report.signed_sha256 = signed_artifact.sha256
    report.signout_reason = reason.strip()
    report.content_json = signed_content

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

    after = {
        "status": report.status,
        "approved_by": str(report.approved_by),
        "approved_at": report.approved_at.isoformat(),
        "supersedes_report_id": str(report.supersedes_report_id) if report.supersedes_report_id else None,
        "draft_artifact_id": str(report.artifact_id),
        "signed_artifact_id": str(signed_artifact.id),
        "signed_sha256": signed_artifact.sha256,
    }
    AuditService(db).record(
        event_type="REPORT_APPROVED",
        case_id=report.case_id,
        analysis_id=report.analysis_id,
        actor_type="HUMAN",
        actor_id=str(approver_id),
        subject_type="REPORT",
        subject_id=str(report.id),
        operation="APPROVE",
        before_state=before,
        after_state=after,
        reason=reason.strip(),
        output_artifacts=[
            {"artifact_id": str(report.artifact_id)},
            {"artifact_id": str(signed_artifact.id), "sha256": signed_artifact.sha256},
        ],
        payload={
            "signed_report": True,
            "signed_artifact_id": str(signed_artifact.id),
            "signed_sha256": signed_artifact.sha256,
        },
    )
    db.flush()
    return report
