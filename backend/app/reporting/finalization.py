from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5
import tempfile

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.artifacts.firebase_store import FirebaseArtifactStore
from backend.app.infrastructure.artifacts.store import ArtifactStore
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, ConfirmationRecord, Report
from backend.app.reporting.service import (
    REPORT_STATUS_FINAL,
    REPORT_STATUS_SUPERSEDED,
    final_report_eligibility,
    render_pdf,
)


class ReportFinalizationError(ValueError):
    pass


def _verify_report_snapshot(db: Session, report: Report) -> None:
    """Reject sign-out when the draft no longer matches current approved decisions."""
    content = report.content_json or {}
    findings = content.get("findings") or []
    from backend.app.infrastructure.db.models import ACMGAssessment, Classification, ReportabilityDecision, SecondaryFindingDecision

    latest_cls_rows = list(
        db.scalars(
            select(Classification)
            .where(Classification.analysis_id == report.analysis_id)
            .order_by(Classification.variant_id, Classification.version.desc())
        )
    )
    latest_cls = {}
    for row in latest_cls_rows:
        latest_cls.setdefault(row.variant_id, row)

    snapshot_by_variant = {}
    for finding in findings:
        variant_id_raw = finding.get("variant_id")
        classification_id = finding.get("classification_id")
        classification_version = finding.get("classification_version")
        reportability = finding.get("reportability") or {}
        if not variant_id_raw or not classification_id or classification_version is None:
            raise ReportFinalizationError("Report snapshot is missing exact classification identity")
        variant_id = UUID(str(variant_id_raw))
        if variant_id in snapshot_by_variant:
            raise ReportFinalizationError(f"Report contains duplicate finding snapshot for variant {variant_id}")
        snapshot_by_variant[variant_id] = finding

        cls = db.scalar(
            select(Classification).where(
                Classification.id == UUID(str(classification_id)),
                Classification.analysis_id == report.analysis_id,
                Classification.variant_id == variant_id,
            )
        )
        if (
            cls is None
            or cls.version != int(classification_version)
            or cls.state != "FINAL"
            or cls.review_status != "APPROVED"
        ):
            raise ReportFinalizationError(
                f"Report snapshot classification for variant {variant_id} is stale or no longer approved"
            )
        if latest_cls.get(variant_id) is None or latest_cls[variant_id].id != cls.id:
            raise ReportFinalizationError(
                f"Report snapshot classification for variant {variant_id} is no longer the latest version"
            )

        snapshot_hash = finding.get("classification_snapshot_sha256")
        if not isinstance(snapshot_hash, str):
            raise ReportFinalizationError(
                f"Report snapshot is missing ACMG classification identity for variant {variant_id}"
            )
        classification_payload = {
            "id": str(cls.id),
            "version": cls.version,
            "result": cls.result,
            "state": cls.state,
            "review_status": cls.review_status,
            "review_version": cls.review_version,
            "framework_name": cls.framework_name,
            "framework_version": cls.framework_version,
            "specification_provider": cls.specification_provider,
            "specification_id": cls.specification_id,
            "specification_version": cls.specification_version,
            "criterion_ids": [str(x) for x in (cls.criterion_ids or [])],
            "metadata_json": cls.metadata_json or {},
        }
        current_hash = hashlib.sha256(
            json.dumps(classification_payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()
        if current_hash != snapshot_hash:
            raise ReportFinalizationError(
                f"Report snapshot ACMG classification for variant {variant_id} changed after draft generation"
            )

        assessment_snapshot = finding.get("acmg_assessment_snapshot")
        if not isinstance(assessment_snapshot, list):
            raise ReportFinalizationError(
                f"Report snapshot is missing ACMG assessment identity for variant {variant_id}"
            )
        expected_ids = {str(x) for x in (cls.criterion_ids or [])}
        actual_ids = {str(x.get("assessment_id")) for x in assessment_snapshot if isinstance(x, dict)}
        if actual_ids != expected_ids or len(actual_ids) != len(assessment_snapshot):
            raise ReportFinalizationError(
                f"Report snapshot ACMG assessment set for variant {variant_id} no longer matches classification"
            )
        for item in assessment_snapshot:
            assessment_id = item.get("assessment_id")
            try:
                assessment_uuid = UUID(str(assessment_id))
            except (ValueError, TypeError) as exc:
                raise ReportFinalizationError(
                    f"Report snapshot contains invalid ACMG assessment identity for variant {variant_id}"
                ) from exc
            assessment = db.scalar(
                select(ACMGAssessment).where(
                    ACMGAssessment.id == assessment_uuid,
                    ACMGAssessment.analysis_id == report.analysis_id,
                    ACMGAssessment.variant_id == variant_id,
                )
            )
            if assessment is None:
                raise ReportFinalizationError(
                    f"Report snapshot ACMG assessment {assessment_id} is missing"
                )
            current_item = {
                "assessment_id": str(assessment.id),
                "criterion": assessment.criterion,
                "review_version": assessment.review_version,
                "state": assessment.state,
                "framework_name": assessment.framework_name,
                "framework_version": assessment.framework_version,
                "specification_provider": assessment.specification_provider,
                "specification_id": assessment.specification_id,
                "specification_version": assessment.specification_version,
                "automated_assessment": assessment.automated_assessment or {},
                "reviewed_assessment": assessment.reviewed_assessment,
                "final_assessment": assessment.final_assessment,
            }
            if current_item != item:
                raise ReportFinalizationError(
                    f"Report snapshot ACMG assessment {assessment_id} changed after draft generation"
                )

        decision_id = reportability.get("decision_id")
        decision_version = reportability.get("version")
        if not decision_id or decision_version is None:
            raise ReportFinalizationError(
                f"Report snapshot is missing exact reportability identity for variant {variant_id}"
            )
        decision = db.scalar(
            select(ReportabilityDecision).where(
                ReportabilityDecision.id == UUID(str(decision_id)),
                ReportabilityDecision.analysis_id == report.analysis_id,
                ReportabilityDecision.variant_id == variant_id,
            )
        )
        latest_decision = db.scalar(
            select(ReportabilityDecision)
            .where(
                ReportabilityDecision.analysis_id == report.analysis_id,
                ReportabilityDecision.variant_id == variant_id,
            )
            .order_by(ReportabilityDecision.version.desc())
        )
        if (
            decision is None
            or decision.version != int(decision_version)
            or decision.status != "FINAL"
            or latest_decision is None
            or latest_decision.id != decision.id
        ):
            raise ReportFinalizationError(
                f"Report snapshot reportability decision for variant {variant_id} is stale or not final"
            )

        confirmation_context = finding.get("confirmation_context")
        if not isinstance(confirmation_context, dict):
            raise ReportFinalizationError(
                f"Report snapshot is missing confirmation identity for variant {variant_id}"
            )
        confirmation_id_raw = confirmation_context.get("record_id")
        confirmation_version = confirmation_context.get("version")
        latest_confirmation = db.scalar(
            select(ConfirmationRecord)
            .where(
                ConfirmationRecord.analysis_id == report.analysis_id,
                ConfirmationRecord.variant_id == variant_id,
            )
            .order_by(ConfirmationRecord.version.desc())
        )
        if confirmation_id_raw is None:
            if confirmation_version is not None or latest_confirmation is not None:
                raise ReportFinalizationError(
                    f"Report snapshot confirmation for variant {variant_id} is stale"
                )
        else:
            if confirmation_version is None:
                raise ReportFinalizationError(
                    f"Report snapshot is missing confirmation version for variant {variant_id}"
                )
            try:
                confirmation_id = UUID(str(confirmation_id_raw))
            except (ValueError, TypeError) as exc:
                raise ReportFinalizationError(
                    f"Report snapshot contains invalid confirmation identity for variant {variant_id}"
                ) from exc
            confirmation = db.scalar(
                select(ConfirmationRecord).where(
                    ConfirmationRecord.id == confirmation_id,
                    ConfirmationRecord.analysis_id == report.analysis_id,
                    ConfirmationRecord.variant_id == variant_id,
                )
            )
            if (
                confirmation is None
                or confirmation.version != int(confirmation_version)
                or latest_confirmation is None
                or latest_confirmation.id != confirmation.id
            ):
                raise ReportFinalizationError(
                    f"Report snapshot confirmation for variant {variant_id} is stale or no longer latest"
                )

    secondary_findings = content.get("secondary_findings") or []
    secondary_snapshot_variants = set()
    for finding in secondary_findings:
        decision_id = finding.get("decision_id")
        version = finding.get("version")
        variant_id_raw = finding.get("variant_id")
        if not decision_id or version is None or not variant_id_raw:
            raise ReportFinalizationError("Report snapshot is missing exact secondary finding decision identity")
        try:
            variant_id = UUID(str(variant_id_raw))
            if variant_id in secondary_snapshot_variants:
                raise ReportFinalizationError(f"Report contains duplicate secondary finding snapshot for variant {variant_id}")
            secondary_snapshot_variants.add(variant_id)
            decision_uuid = UUID(str(decision_id))
        except (ValueError, TypeError) as exc:
            raise ReportFinalizationError("Report snapshot contains invalid secondary finding identity") from exc
        decision = db.scalar(
            select(SecondaryFindingDecision).where(
                SecondaryFindingDecision.id == decision_uuid,
                SecondaryFindingDecision.analysis_id == report.analysis_id,
                SecondaryFindingDecision.variant_id == variant_id,
            )
        )
        latest_secondary = db.scalar(
            select(SecondaryFindingDecision)
            .where(
                SecondaryFindingDecision.analysis_id == report.analysis_id,
                SecondaryFindingDecision.variant_id == variant_id,
            )
            .order_by(SecondaryFindingDecision.version.desc())
        )
        if (
            decision is None
            or decision.version != int(version)
            or decision.status != "FINAL"
            or decision.disposition != "REPORT"
            or latest_secondary is None
            or latest_secondary.id != decision.id
        ):
            raise ReportFinalizationError(
                f"Report snapshot secondary finding for variant {variant_id} is stale or no longer reportable"
            )

    latest_secondary_rows = list(
        db.scalars(
            select(SecondaryFindingDecision)
            .where(SecondaryFindingDecision.analysis_id == report.analysis_id)
            .order_by(SecondaryFindingDecision.variant_id, SecondaryFindingDecision.version.desc())
        )
    )
    latest_secondary = {}
    for row in latest_secondary_rows:
        latest_secondary.setdefault(row.variant_id, row)
    expected_secondary_reportable = {
        variant_id
        for variant_id, row in latest_secondary.items()
        if row.status == "FINAL" and row.disposition == "REPORT"
    }
    if expected_secondary_reportable != secondary_snapshot_variants:
        raise ReportFinalizationError(
            "Report snapshot no longer matches the current finalized secondary-finding set"
        )

    expected_reportable = {
        variant_id
        for variant_id, cls in latest_cls.items()
        if cls.state == "FINAL"
        and cls.review_status == "APPROVED"
        and (
            (decision := db.scalar(
                select(ReportabilityDecision)
                .where(
                    ReportabilityDecision.analysis_id == report.analysis_id,
                    ReportabilityDecision.variant_id == variant_id,
                )
                .order_by(ReportabilityDecision.version.desc())
            ))
            is not None
            and decision.status == "FINAL"
            and decision.disposition == "REPORT"
        )
    }
    if expected_reportable != set(snapshot_by_variant):
        raise ReportFinalizationError(
            "Report snapshot no longer matches the current finalized reportability set"
        )



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
    # The signed artifact belongs deterministically to this report version.
    # A worker crash after storage upload but before the surrounding DB
    # transaction commits must not create a second artifact on retry.
    signed_artifact_id = uuid5(report.id, "siraloom:signed-report-pdf")
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
            artifact_id=signed_artifact_id,
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

    # Final report ordering is case/report-type scoped clinical history.
    # Lock the case before inspecting the finalized chain so two different
    # report versions cannot finalize concurrently and invert supersession.
    case_lock = db.get(Case, report.case_id, with_for_update=True)
    if case_lock is None:
        raise ReportFinalizationError("Report case not found")
    db.refresh(case_lock, with_for_update=True)

    if report.status == REPORT_STATUS_FINAL:
        return report
    if report.status != "DRAFT":
        raise ReportFinalizationError(f"Report cannot be finalized from status {report.status}")

    eligible, errors = final_report_eligibility(db, analysis_id=report.analysis_id)
    if not eligible:
        raise ReportFinalizationError("; ".join(errors))
    if not report.artifact_id:
        raise ReportFinalizationError("Report has no immutable draft artifact to approve")

    _verify_report_snapshot(db, report)

    prior = db.scalars(
        select(Report)
        .where(
            Report.case_id == report.case_id,
            Report.report_type == report.report_type,
            Report.status == REPORT_STATUS_FINAL,
        )
        .order_by(Report.report_version.desc())
    ).first()

    if prior is not None and prior.report_version > report.report_version:
        raise ReportFinalizationError(
            f"Report version {report.report_version} cannot be finalized after "
            f"newer finalized version {prior.report_version}."
        )

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
