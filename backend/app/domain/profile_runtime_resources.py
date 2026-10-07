"""Resolve the exact resource selected by analysis preflight for runtime adapters.

This module is deliberately separate from the workflow implementation so runtime
adapters can consume the immutable preflight selection without re-running profile
selection or falling back to another resource.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    ResolvedResourceExecution,
    resolve_resource_execution,
)
from backend.app.infrastructure.db.models import Analysis, Resource


class ProfileRuntimeResourceError(RuntimeError):
    """Raised when a profile-selected runtime resource cannot be consumed exactly."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProfileRuntimeResource:
    capability: str
    resource: Resource
    execution: ResolvedResourceExecution


def resolve_profile_runtime_resources(
    db: Session,
    *,
    analysis_id: UUID,
    capability: str,
) -> tuple[ProfileRuntimeResource, ...]:
    """Return every exact qualified resource selected during analysis preflight.

    This plural form is required for additive capabilities such as secondary
    population context. It applies the same immutable-plan checks as the
    singular resolver to every selected resource and never substitutes a
    different provider when one selected resource becomes stale or unavailable.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ProfileRuntimeResourceError(
            "ANALYSIS_NOT_FOUND",
            f"Analysis {analysis_id} was not found.",
        )

    configuration = dict(analysis.configuration or {})
    if not configuration.get("resource_profile_id"):
        raise ProfileRuntimeResourceError(
            "RESOURCE_PROFILE_REQUIRED",
            "This runtime resolver requires a governed analysis resource profile.",
        )

    plan = dict(configuration.get("resource_plan") or {})
    if plan.get("status") not in {"READY", "READY_WITH_LIMITATIONS"}:
        raise ProfileRuntimeResourceError(
            "RESOURCE_PLAN_NOT_READY",
            f"Analysis resource plan is not runnable: {plan.get('status')!r}.",
        )

    selected = [
        dict(item)
        for item in (plan.get("selected") or [])
        if str(item.get("capability")) == capability
    ]
    if not selected:
        raise ProfileRuntimeResourceError(
            "RESOURCE_NOT_SELECTED",
            f"Preflight selected no resources for capability {capability!r}.",
        )

    resolved: list[ProfileRuntimeResource] = []
    for snapshot in selected:
        resource_id = snapshot.get("resource_id")
        if not resource_id:
            raise ProfileRuntimeResourceError(
                "RESOURCE_PLAN_INVALID",
                f"Preflight snapshot for {capability!r} has no resource ID.",
            )

        try:
            resource_uuid = UUID(str(resource_id))
        except (TypeError, ValueError) as exc:
            raise ProfileRuntimeResourceError(
                "RESOURCE_PLAN_INVALID",
                f"Preflight resource ID for {capability!r} is not a UUID: {resource_id!r}.",
            ) from exc

        resource = db.get(Resource, resource_uuid)
        if resource is None:
            raise ProfileRuntimeResourceError(
                "RESOURCE_NOT_FOUND",
                f"Preflight-selected resource {resource_id} no longer exists.",
            )

        try:
            execution = resolve_resource_execution(db, resource=resource)
        except ResourceExecutionError as exc:
            raise ProfileRuntimeResourceError(
                "RESOURCE_EXECUTION_CONTRACT_INVALID",
                str(exc),
            ) from exc

        expected_execution = dict(snapshot.get("execution") or {})
        expected = {
            "resource_id": str(expected_execution.get("resource_id")),
            "resource_version": expected_execution.get("resource_version"),
            "qualification_id": str(expected_execution.get("qualification_id")),
            "qualification_version": expected_execution.get("qualification_version"),
            "contract_hash": expected_execution.get("contract_hash"),
        }
        actual = {
            "resource_id": str(execution.resource_id),
            "resource_version": execution.resource_version,
            "qualification_id": str(execution.qualification_id),
            "qualification_version": execution.qualification_version,
            "contract_hash": execution.contract_hash,
        }
        if actual != expected:
            raise ProfileRuntimeResourceError(
                "RESOURCE_PLAN_STALE",
                f"Preflight resource contract no longer matches runtime qualification: expected={expected}, actual={actual}.",
            )

        resolved.append(ProfileRuntimeResource(
            capability=capability,
            resource=resource,
            execution=execution,
        ))

    return tuple(resolved)


def resolve_profile_runtime_resource(
    db: Session,
    *,
    analysis_id: UUID,
    capability: str,
) -> ProfileRuntimeResource:
    """Return the exact qualified resource selected during analysis preflight.

    No provider fallback is permitted here. The resource ID, release version,
    qualification identity/version and execution-contract hash must all match
    the persisted preflight snapshot. A changed or quarantined resource therefore
    causes a deterministic stale-plan failure rather than silently switching data.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ProfileRuntimeResourceError(
            "ANALYSIS_NOT_FOUND",
            f"Analysis {analysis_id} was not found.",
        )

    configuration = dict(analysis.configuration or {})
    if not configuration.get("resource_profile_id"):
        raise ProfileRuntimeResourceError(
            "RESOURCE_PROFILE_REQUIRED",
            "This runtime resolver requires a governed analysis resource profile.",
        )

    plan = dict(configuration.get("resource_plan") or {})
    if plan.get("status") not in {"READY", "READY_WITH_LIMITATIONS"}:
        raise ProfileRuntimeResourceError(
            "RESOURCE_PLAN_NOT_READY",
            f"Analysis resource plan is not runnable: {plan.get('status')!r}.",
        )

    selected = [
        dict(item)
        for item in (plan.get("selected") or [])
        if str(item.get("capability")) == capability
    ]
    if len(selected) != 1:
        raise ProfileRuntimeResourceError(
            "RESOURCE_NOT_SELECTED",
            f"Preflight selected {len(selected)} resources for capability {capability!r}; exactly one is required.",
        )

    snapshot = selected[0]
    resource_id = snapshot.get("resource_id")
    if not resource_id:
        raise ProfileRuntimeResourceError(
            "RESOURCE_PLAN_INVALID",
            f"Preflight snapshot for {capability!r} has no resource ID.",
        )

    try:
        resource_uuid = UUID(str(resource_id))
    except (TypeError, ValueError) as exc:
        raise ProfileRuntimeResourceError(
            "RESOURCE_PLAN_INVALID",
            f"Preflight resource ID for {capability!r} is not a UUID: {resource_id!r}.",
        ) from exc

    resource = db.get(Resource, resource_uuid)
    if resource is None:
        raise ProfileRuntimeResourceError(
            "RESOURCE_NOT_FOUND",
            f"Preflight-selected resource {resource_id} no longer exists.",
        )

    try:
        execution = resolve_resource_execution(db, resource=resource)
    except ResourceExecutionError as exc:
        raise ProfileRuntimeResourceError(
            "RESOURCE_EXECUTION_CONTRACT_INVALID",
            str(exc),
        ) from exc

    expected_execution = dict(snapshot.get("execution") or {})
    expected = {
        "resource_id": str(expected_execution.get("resource_id")),
        "resource_version": expected_execution.get("resource_version"),
        "qualification_id": str(expected_execution.get("qualification_id")),
        "qualification_version": expected_execution.get("qualification_version"),
        "contract_hash": expected_execution.get("contract_hash"),
    }
    actual = {
        "resource_id": str(execution.resource_id),
        "resource_version": execution.resource_version,
        "qualification_id": str(execution.qualification_id),
        "qualification_version": execution.qualification_version,
        "contract_hash": execution.contract_hash,
    }
    if actual != expected:
        raise ProfileRuntimeResourceError(
            "RESOURCE_PLAN_STALE",
            f"Preflight resource contract no longer matches runtime qualification: expected={expected}, actual={actual}.",
        )

    return ProfileRuntimeResource(
        capability=capability,
        resource=resource,
        execution=execution,
    )
