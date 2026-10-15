"""Integrity checks for immutable, signed report artifacts."""

from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import Artifact, Report


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
