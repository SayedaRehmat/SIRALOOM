"""Integrity checks for immutable, signed report artifacts."""

import hashlib
import json

from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Artifact, Report

REPORT_CONTENT_INTEGRITY_VERSION = "sha256-canonical-json-v1"


def report_content_sha256(content: dict) -> str:
    """Hash a report JSON snapshot using a stable serialization contract."""
    canonical = json.dumps(
        content,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def has_valid_signed_artifact(db: Session, report: Report) -> bool:
    """Return whether a final report has its exact durable signed PDF lineage."""
    signed_artifact_id = report.signed_artifact_id
    if signed_artifact_id is None:
        return False

    artifact = db.get(Artifact, signed_artifact_id)
    if artifact is None:
        return False

    metadata = dict(artifact.metadata_json or {})
    return bool(
        artifact.case_id == report.case_id
        and artifact.analysis_id == report.analysis_id
        and artifact.artifact_type == "REPORT_PDF"
        and artifact.validation_status == "VALID"
        and report.signed_sha256
        and artifact.sha256 == report.signed_sha256
        and metadata.get("report_id") == str(report.id)
        and metadata.get("report_version") == report.report_version
        and metadata.get("signed") is True
    )


def has_valid_draft_artifact(db: Session, report: Report) -> bool:
    """Return whether a report's draft PDF belongs to that exact case/analysis.

    Older draft artifacts may not carry report_id metadata, so the immutable
    case, analysis, type, validation state, and any available report metadata
    are checked. New artifacts carry the explicit report identity as well.
    """
    artifact_id = getattr(report, "artifact_id", None)
    if artifact_id is None:
        # Every persisted report exposed to reviewers must have its immutable
        # draft PDF. Treat a missing link as broken lineage, including legacy
        # rows, so list/read endpoints cannot present an unusable draft as valid.
        return False

    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        return False

    metadata = dict(artifact.metadata_json or {})
    integrity_version = metadata.get("report_content_integrity")
    content_integrity_valid = integrity_version is None or (
        integrity_version == REPORT_CONTENT_INTEGRITY_VERSION
        and isinstance(metadata.get("report_content_sha256"), str)
        and metadata["report_content_sha256"] == report_content_sha256(report.content_json or {})
    )
    return bool(
        artifact.case_id == report.case_id
        and artifact.analysis_id == report.analysis_id
        and artifact.artifact_type == "REPORT_PDF"
        and artifact.validation_status == "VALID"
        and (
            metadata.get("report_id") is None
            or metadata.get("report_id") == str(report.id)
        )
        and (
            metadata.get("report_version") is None
            or metadata.get("report_version") == report.report_version
        )
        and (
            metadata.get("report_state") is None
            or metadata.get("report_state") == "DRAFT"
        )
        and content_integrity_valid
    )
