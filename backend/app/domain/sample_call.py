"""Read sample-specific call evidence persisted on normalized analysis partitions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import AnalysisPartition


def get_analysis_sample_call(
    db: Session,
    analysis_id: UUID,
    variant_id: UUID,
) -> dict | None:
    """Return the normalized-input call associated with one analysis/variant."""
    return get_analysis_sample_calls(db, analysis_id).get(variant_id)


def get_analysis_sample_calls(db: Session, analysis_id: UUID) -> dict[UUID, dict]:
    """Load calls for one analysis in one query, keyed by canonical variant row ID."""
    result: dict[UUID, dict] = {}
    partitions = db.scalars(
        select(AnalysisPartition)
        .where(
            AnalysisPartition.analysis_id == analysis_id,
            AnalysisPartition.step_id == "normalize",
        )
        .order_by(AnalysisPartition.ordinal)
    ).all()
    for partition in partitions:
        calls = (partition.metadata_json or {}).get("sample_calls")
        if not isinstance(calls, list):
            continue
        for call in calls:
            if not isinstance(call, dict):
                continue
            try:
                variant_id = UUID(str(call.get("variant_id")))
            except (TypeError, ValueError):
                continue
            result.setdefault(variant_id, call)
    return result
