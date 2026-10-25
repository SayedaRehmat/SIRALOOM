from __future__ import annotations

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    Artifact,
    TechnicalQCObservation,
)


def validate_qc_source_artifact(artifact: Artifact, analysis: Analysis) -> None:
    """Only validated VCF inputs/outputs can substantiate a VCF QC observation."""
    if (
        artifact.case_id != analysis.case_id
        or (artifact.analysis_id is not None and artifact.analysis_id != analysis.id)
        or artifact.artifact_type not in {"VCF", "NORMALIZED_VCF"}
        or artifact.validation_status not in {"VALID", "VALIDATED"}
        or not isinstance(artifact.sha256, str)
        or len(artifact.sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in artifact.sha256)
    ):
        raise ValueError("QC source artifact must be a validated VCF linked to this analysis")


def qc_observation_snapshot(
    db: Session,
    analysis: Analysis,
    observations: list[TechnicalQCObservation] | None = None,
) -> list[dict]:
    """Return immutable identities and values for the QC observations consumed."""
    rows = observations
    if rows is None:
        rows = list(db.scalars(
            select(TechnicalQCObservation)
            .where(TechnicalQCObservation.analysis_id == analysis.id)
            .order_by(TechnicalQCObservation.created_at, TechnicalQCObservation.id)
        ))

    snapshot = []
    for row in rows:
        artifact_snapshot = None
        if row.artifact_id is not None:
            artifact = db.get(Artifact, row.artifact_id)
            if artifact is None:
                raise ValueError("QC observation artifact does not belong to this analysis")
            validate_qc_source_artifact(artifact, analysis)
            artifact_snapshot = {
                "artifact_id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "sha256": artifact.sha256,
            }
        created_at = row.created_at
        if created_at is not None and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        elif created_at is not None:
            created_at = created_at.astimezone(timezone.utc)
        snapshot.append({
            "observation_id": str(row.id),
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
            "metric_unit": row.metric_unit,
            "status": row.status,
            "source": row.source,
            "source_version": row.source_version,
            "metadata": row.metadata_json or {},
            "created_at": created_at.isoformat() if created_at else None,
            "artifact": artifact_snapshot,
        })
    return snapshot
