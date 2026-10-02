"""Governed change-management impact detection for resource adoption.

A new laboratory release never rewrites historical analyses. This module identifies
analyses that actually executed against the replaced resource and creates durable
PENDING_REANALYSIS impact records. Reanalysis remains a separate governed action.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    Analysis,
    AuditEvent,
    Case,
    Resource,
    ResourceChangeImpact,
    ResourceExecutionRecord,
)


@dataclass(frozen=True)
class ResourceChangeImpactResult:
    adoption_event_id: UUID
    previous_resource_id: UUID
    adopted_resource_id: UUID
    impacted_analysis_ids: tuple[UUID, ...]
    created_impact_ids: tuple[UUID, ...]


def identify_resource_change_impacts(
    db: Session,
    *,
    adoption_event_id: UUID,
) -> ResourceChangeImpactResult:
    """Identify historical analyses affected by one APPROVED adoption event.

    Only completed/known executions against the exact previous resource are
    considered. The laboratory organization is derived from the analysis case,
    so a release change cannot create cross-tenant impacts. Existing impact rows
    make the operation idempotent.
    """
    event = db.get(AuditEvent, adoption_event_id)
    if event is None:
        raise ValueError("adoption audit event not found")
    if event.event_type != "RESOURCE_ADOPTION_DECISION" or event.operation != "APPROVED":
        raise ValueError("adoption event must be an approved resource adoption")

    versions = event.resource_versions or {}
    previous = versions.get("previous")
    resulting = versions.get("resulting")
    requested = versions.get("requested")
    if not isinstance(previous, dict) or not previous.get("resource_id"):
        return ResourceChangeImpactResult(
            adoption_event_id=adoption_event_id,
            previous_resource_id=UUID(str(requested["resource_id"])),
            adopted_resource_id=UUID(str(requested["resource_id"])),
            impacted_analysis_ids=(),
            created_impact_ids=(),
        )
    if not isinstance(resulting, dict) or not resulting.get("resource_id"):
        raise ValueError("approved adoption event has no resulting binding")

    previous_id = UUID(str(previous["resource_id"]))
    adopted_id = UUID(str(resulting["resource_id"]))
    if previous_id == adopted_id:
        return ResourceChangeImpactResult(
            adoption_event_id=adoption_event_id,
            previous_resource_id=previous_id,
            adopted_resource_id=adopted_id,
            impacted_analysis_ids=(),
            created_impact_ids=(),
        )

    previous_resource = db.get(Resource, previous_id)
    adopted_resource = db.get(Resource, adopted_id)
    if previous_resource is None or adopted_resource is None:
        raise ValueError("adoption event references an unknown resource release")

    organization_id = UUID(str(event.workflow["organization_id"])) if isinstance(event.workflow, dict) and event.workflow.get("organization_id") else None
    if organization_id is None:
        raise ValueError("adoption event is missing organization identity")

    rows = db.execute(
        select(ResourceExecutionRecord, Analysis, Case)
        .join(Analysis, Analysis.id == ResourceExecutionRecord.analysis_id)
        .join(Case, Case.id == Analysis.case_id)
        .where(
            ResourceExecutionRecord.resource_id == previous_id,
            Case.organization_id == organization_id,
        )
    ).all()

    impacted: list[UUID] = []
    created: list[UUID] = []
    for execution, analysis, case in rows:
        if analysis.id not in impacted:
            impacted.append(analysis.id)

        existing = db.scalar(select(ResourceChangeImpact).where(
            ResourceChangeImpact.adoption_event_id == adoption_event_id,
            ResourceChangeImpact.analysis_id == analysis.id,
        ))
        if existing is not None:
            continue

        impact = ResourceChangeImpact(
            id=uuid4(),
            organization_id=case.organization_id,
            adoption_event_id=adoption_event_id,
            analysis_id=analysis.id,
            previous_resource_id=previous_id,
            previous_resource_version=previous_resource.version,
            adopted_resource_id=adopted_id,
            adopted_resource_version=adopted_resource.version,
            status="PENDING_REANALYSIS",
            reason="Historical analysis executed with a resource release replaced by an approved laboratory adoption.",
        )
        db.add(impact)
        db.flush()
        created.append(impact.id)

    return ResourceChangeImpactResult(
        adoption_event_id=adoption_event_id,
        previous_resource_id=previous_id,
        adopted_resource_id=adopted_id,
        impacted_analysis_ids=tuple(impacted),
        created_impact_ids=tuple(created),
    )
