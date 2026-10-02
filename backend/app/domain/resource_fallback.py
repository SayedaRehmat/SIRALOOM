"""Resolve governed scientific resources with an explicit organization-approved fallback.

This module never changes an organization's binding. It only resolves an existing
binding for the same scientific resource identity when the requested version
cannot be consumed, and returns the decision that the owning workflow must
persist before execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.variant_identity import normalize_build
from backend.app.domain.workflow_decision import (
    OutcomeKind,
    WorkflowDecision,
    decide_workflow_outcome,
)
from backend.app.infrastructure.db.models import (
    OrganizationResourceBinding,
    Resource,
    ResourceQualification,
)


class ResourceFallbackError(RuntimeError):
    """Raised when a fallback binding exists but fails safety validation."""


@dataclass(frozen=True)
class ResourceResolution:
    resource: Resource | None
    requested_resource_id: UUID | None
    fallback_resource_id: UUID | None
    decision: WorkflowDecision
    used_fallback: bool


def _resource_identity_key(
    *,
    name: str,
    provider: str,
    resource_type: str,
    genome_build: str | None,
) -> str:
    return "|".join(
        [name, provider, resource_type, genome_build or "UNSPECIFIED"]
    )


def _is_requested_resource_consumable(
    resource: Resource,
    *,
    expected_type: str,
    expected_build: str,
    expected_provider: str | None,
) -> bool:
    if resource.resource_type != expected_type:
        return False
    if resource.genome_build and normalize_build(resource.genome_build) != normalize_build(expected_build):
        return False
    if expected_provider and resource.provider != expected_provider:
        return False
    # ACTIVE and explicitly pinned SUPERSEDED versions are consumable. A
    # candidate/qualified/rejected/quarantined version is not a workflow input.
    return resource.status in {"ACTIVE", "SUPERSEDED"}


def _find_approved_active_binding(
    db: Session,
    *,
    organization_id: UUID,
    name: str,
    provider: str,
    resource_type: str,
    genome_build: str | None,
) -> Resource | None:
    identity_key = _resource_identity_key(
        name=name,
        provider=provider,
        resource_type=resource_type,
        genome_build=genome_build,
    )
    binding = db.scalar(
        select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == organization_id,
            OrganizationResourceBinding.identity_key == identity_key,
        )
    )
    if binding is None:
        return None

    resource = db.get(Resource, binding.resource_id)
    if resource is None:
        return None

    if resource.organization_id not in {None, organization_id}:
        return None

    if (
        resource.name != name
        or resource.provider != provider
        or resource.resource_type != resource_type
        or normalize_build(resource.genome_build or genome_build or "") != normalize_build(genome_build or resource.genome_build or "")
    ):
        return None

    # Approval creates the organization binding only after a successful
    # qualification. Re-check that qualification here so a later quarantine
    # or data corruption cannot turn the binding into an execution path.
    qualified = db.scalar(
        select(ResourceQualification.id).where(
            ResourceQualification.resource_id == resource.id,
            ResourceQualification.status == "QUALIFIED",
        ).limit(1)
    )
    if qualified is None:
        return None

    # Organization approval is the active adoption boundary. The resource
    # registry's global status may be QUALIFIED because the version is lab-
    # specific rather than globally ACTIVE. SUPERSEDED remains usable for
    # reproducibility; rejected/quarantined/candidate versions do not.
    if resource.status not in {"ACTIVE", "QUALIFIED", "SUPERSEDED"}:
        return None

    return resource


def resolve_resource_with_fallback(
    db: Session,
    *,
    organization_id: UUID,
    requested_resource_id: object,
    expected_type: str,
    expected_build: str,
    expected_provider: str,
    fallback_outcome: OutcomeKind = OutcomeKind.RESOURCE_UNAVAILABLE,
    lab_action_required_without_fallback: bool = False,
) -> ResourceResolution:
    """Resolve a requested resource or the lab's approved active replacement.

    The requested resource remains the analysis' requested identity. A fallback
    is only an already-approved organization binding for the exact same
    scientific identity (name/provider/type/build). This function never creates,
    approves, activates, supersedes, or mutates a resource binding.
    """
    requested_id: UUID | None = None
    try:
        if requested_resource_id:
            requested_id = UUID(str(requested_resource_id))
    except (TypeError, ValueError):
        requested_id = None

    requested = db.get(Resource, requested_id) if requested_id else None
    if requested is not None and _is_requested_resource_consumable(
        requested,
        expected_type=expected_type,
        expected_build=expected_build,
        expected_provider=expected_provider,
    ):
        return ResourceResolution(
            resource=requested,
            requested_resource_id=requested.id,
            fallback_resource_id=None,
            decision=WorkflowDecision(
                action=__import__("backend.app.domain.workflow_decision", fromlist=["WorkflowAction"]).WorkflowAction.CONTINUE,
                code="RESOURCE_SELECTED",
                message="Requested governed resource is consumable.",
            ),
            used_fallback=False,
        )

    if requested is not None:
        identity = requested
        name = identity.name
        provider = identity.provider
        resource_type = identity.resource_type
        genome_build = identity.genome_build or expected_build
    else:
        # A missing row cannot be safely mapped to an alternate resource unless
        # the caller supplied enough identity information elsewhere. For this
        # first executor boundary, absence of the requested registry row is a
        # governed wait/lab-action condition, not an inferred substitution.
        decision = decide_workflow_outcome(
            fallback_outcome,
            fallback_available=False,
            lab_action_required=lab_action_required_without_fallback,
            code="RESOURCE_NOT_FOUND",
            message="The requested governed resource version was not found; no safe fallback identity can be inferred.",
        )
        return ResourceResolution(
            resource=None,
            requested_resource_id=requested_id,
            fallback_resource_id=None,
            decision=decision,
            used_fallback=False,
        )

    fallback = _find_approved_active_binding(
        db,
        organization_id=organization_id,
        name=name,
        provider=provider,
        resource_type=resource_type,
        genome_build=genome_build,
    )
    decision = decide_workflow_outcome(
        fallback_outcome,
        fallback_available=fallback is not None,
        lab_action_required=lab_action_required_without_fallback,
        code="RESOURCE_FALLBACK_AVAILABLE" if fallback is not None else "RESOURCE_UNAVAILABLE",
        message=(
            "Requested resource is not consumable; use the organization's approved active resource binding."
            if fallback is not None
            else "Requested resource is not consumable and no safe approved active fallback exists."
        ),
    )
    return ResourceResolution(
        resource=fallback,
        requested_resource_id=requested_id,
        fallback_resource_id=fallback.id if fallback is not None else None,
        decision=decision,
        used_fallback=fallback is not None,
    )
