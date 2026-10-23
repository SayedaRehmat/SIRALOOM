from uuid import uuid5

import pytest
from sqlalchemy import select

from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.report_integrity import has_valid_signed_artifact
from backend.app.infrastructure.db.models import (
    Artifact,
    AuditEvent,
    Classification,
    ReportabilityDecision,
)
from backend.app.reporting import finalization
from backend.app.reporting.service import build_report_content
from backend.app.review.service import approve_classification
from tests.test_reporting_signout import seed_finalizable_report


def test_reviewer_approval_to_signed_report_recovers_after_filesystem_write(
    monkeypatch, tmp_path
):
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
    monkeypatch.setattr(
        "backend.app.config.settings.artifact_root",
        str(tmp_path / "artifacts"),
    )
    monkeypatch.setattr(finalization, "render_pdf", lambda _content: b"%PDF-signed-review%")
    real_persist_pdf_artifact = finalization._persist_pdf_artifact
    worker_loss = {"artifact": None}

    def lose_worker_after_filesystem_write(*args, **kwargs):
        artifact = real_persist_pdf_artifact(*args, **kwargs)
        worker_loss["artifact"] = artifact
        raise SystemExit(87)

    monkeypatch.setattr(
        finalization, "_persist_pdf_artifact", lose_worker_after_filesystem_write
    )
    with pytest.raises(SystemExit, match="87"):
        finalization.finalize_report(
            db,
            report_id=report.id,
            approver_id=reviewer.id,
            reason="Approved for release",
        )

    orphan_path = local_path_from_uri(worker_loss["artifact"].storage_uri)
    assert orphan_path is not None and orphan_path.is_file()
    assert orphan_path.read_bytes() == b"%PDF-signed-review%"
    db.rollback()
    db.refresh(report)
    assert report.status == "DRAFT"
    assert report.signed_artifact_id is None
    assert db.get(Artifact, signed_artifact_id) is None

    monkeypatch.setattr(finalization, "_persist_pdf_artifact", real_persist_pdf_artifact)
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
    assert signed.signed_sha256 == worker_loss["artifact"].sha256
    assert orphan_path.read_bytes() == b"%PDF-signed-review%"
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
    assert len(
        db.scalars(
            select(Artifact).where(
                Artifact.id == signed_artifact_id,
                Artifact.analysis_id == analysis.id,
            )
        ).all()
    ) == 1
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
    db.close()
