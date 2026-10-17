from uuid import uuid4, uuid5

import pytest
from sqlalchemy import select

from backend.app.domain.report_integrity import has_valid_signed_artifact
from backend.app.infrastructure.db.models import Artifact, AuditEvent, Classification, ReportabilityDecision
from backend.app.reporting import finalization
from backend.app.reporting.service import build_report_content
from backend.app.review.service import approve_classification
from tests.test_reporting_signout import seed_finalizable_report


def test_reviewer_approval_to_signed_report_failure_recovery_and_retry(monkeypatch):
    db, reviewer, analysis, report = seed_finalizable_report()
    current = db.scalar(
        select(Classification).where(Classification.analysis_id == analysis.id)
    )
    decision = db.scalar(
        select(ReportabilityDecision).where(
            ReportabilityDecision.analysis_id == analysis.id
        )
    )
    current.review_status = "IN_REVIEW"
    current.review_version = 0
    db.commit()

    approved = approve_classification(
        db,
        analysis_id=analysis.id,
        variant_id=current.variant_id,
        reviewer=reviewer,
        expected_version=0,
        reason="Independent review completed",
    )
    decision.classification_id = approved.id
    decision.review_version = approved.review_version
    decision.status = "FINAL"
    report.content_json = build_report_content(
        db, analysis, "en", report_type=report.report_type
    )
    db.commit()

    signed_artifact_id = uuid5(report.id, "siraloom:signed-report-pdf")

    def fail_signout(*_args, **_kwargs):
        raise OSError("injected signed artifact storage failure")

    monkeypatch.setattr(finalization, "_persist_pdf_artifact", fail_signout)
    with pytest.raises(OSError, match="injected signed artifact storage failure"):
        finalization.finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Approved for release",
        )
    db.rollback()
    db.refresh(report)
    assert report.status == "DRAFT"
    assert report.signed_artifact_id is None
    assert db.get(Artifact, signed_artifact_id) is None

    def persist_signed_artifact(session, *, report, content, filename):
        artifact = Artifact(
            id=signed_artifact_id,
            case_id=report.case_id,
            analysis_id=report.analysis_id,
            artifact_type="REPORT_PDF",
            filename=filename,
            media_type="application/pdf",
            size_bytes=3,
            sha256="b" * 64,
            storage_uri=f"file:///signed/{signed_artifact_id}.pdf",
            validation_status="VALID",
            metadata_json={
                "report_id": str(report.id),
                "report_version": report.report_version,
                "report_state": "FINAL",
                "signed": True,
            },
        )
        session.add(artifact)
        session.flush()
        return artifact

    monkeypatch.setattr(finalization, "_persist_pdf_artifact", persist_signed_artifact)
    signed = finalization.finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Approved for release",
    )
    db.commit()

    assert signed.status == "FINAL"
    assert signed.approved_by == reviewer.id
    assert signed.signed_artifact_id == signed_artifact_id
    assert has_valid_signed_artifact(db, signed)
    assert signed.content_json["findings"][0]["classification_id"] == str(approved.id)
    assert db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.event_type == "CLASSIFICATION_APPROVED",
            AuditEvent.analysis_id == analysis.id,
        )
    ) is not None
    assert db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.event_type == "REPORT_APPROVED",
            AuditEvent.analysis_id == analysis.id,
        )
    ) is not None

    retried = finalization.finalize_report(
        db,
        report_id=report.id,
        approver_id=reviewer.id,
        reason="Approved for release",
    )
    assert retried.signed_artifact_id == signed_artifact_id
    assert len(
        db.scalars(
            select(Artifact).where(
                Artifact.id == signed_artifact_id,
                Artifact.analysis_id == analysis.id,
            )
        ).all()
    ) == 1
