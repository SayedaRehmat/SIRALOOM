"""Resolve and snapshot the exact governed runtime contract for resource execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.resource_source_contract import (
    ResourceExecutionContract,
    ResourceSourceContractError,
    validate_execution_contract,
)
from backend.app.infrastructure.db.models import Analysis, Resource, ResourceQualification


class ResourceExecutionError(RuntimeError):
    """Raised when a governed resource cannot be executed exactly as qualified."""


@dataclass(frozen=True)
class ResolvedResourceExecution:
    resource_id: UUID
    resource_version: str
    qualification_id: UUID
    qualification_version: str
    contract: ResourceExecutionContract
    contract_hash: str

    @property
    def snapshot(self) -> dict[str, object]:
        return {
            "resource_id": str(self.resource_id),
            "resource_version": self.resource_version,
            "qualification_id": str(self.qualification_id),
            "qualification_version": self.qualification_version,
            "execution_contract": self.contract.as_dict(),
            "contract_hash": self.contract_hash,
        }


def resolve_resource_execution(
    db: Session,
    *,
    resource: Resource,
) -> ResolvedResourceExecution:
    """Return only the contract that was actually qualified for this resource.

    Runtime adapters must consume this object rather than reconstructing endpoint,
    provider version, dataset, or local location from application settings.
    """
    qualification = db.scalar(
        select(ResourceQualification)
        .where(
            ResourceQualification.resource_id == resource.id,
            ResourceQualification.status == "QUALIFIED",
        )
        .order_by(
            ResourceQualification.qualified_at.desc(),
            ResourceQualification.created_at.desc(),
        )
        .limit(1)
    )
    if qualification is None:
        raise ResourceExecutionError(
            f"Resource {resource.id} has no successful technical qualification."
        )

    checks = dict(qualification.checks_json or {})
    raw_contract = dict(checks.get("execution_contract") or {})
    try:
        contract = validate_execution_contract(
            raw_contract,
            resource_provider=resource.provider,
            resource_access_method=resource.access_method,
            resource_location=resource.location,
            resource_organization_id=resource.organization_id,
        )
    except ResourceSourceContractError as exc:
        raise ResourceExecutionError(
            f"Qualified execution contract for resource {resource.id} is invalid: {exc}"
        ) from exc

    canonical = json.dumps(
        contract.as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    contract_hash = hashlib.sha256(canonical).hexdigest()
    return ResolvedResourceExecution(
        resource_id=resource.id,
        resource_version=resource.version,
        qualification_id=qualification.id,
        qualification_version=qualification.qualification_version,
        contract=contract,
        contract_hash=contract_hash,
    )


_STEP_REQUIRED_CAPABILITY = {
    "normalize": "REFERENCE_PACKAGE",
    "annotate": "ANNOTATION_ENGINE",
    "population": "POPULATION",
    "acmg_assessment": "ACMG_RULE_SPECIFICATION",
}


def _validate_profile_runtime_binding(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    resolved: ResolvedResourceExecution,
) -> None:
    """Fail closed if a profile-governed analysis is about to consume another resource.

    Preflight persists an immutable resource-plan snapshot in Analysis.configuration.
    The workflow may still resolve a concrete Resource through a legacy adapter path;
    this boundary is therefore the final runtime guard. It verifies resource identity,
    qualification identity/version, and the qualified execution-contract hash before
    a ResourceExecutionRecord is created.

    Analyses without a resource profile retain the established legacy execution path.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ResourceExecutionError(
            f"Analysis {analysis_id} was not found while binding resource execution."
        )

    configuration = dict(analysis.configuration or {})
    profile_id = configuration.get("resource_profile_id")
    if not profile_id:
        return

    plan = dict(configuration.get("resource_plan") or {})
    status = plan.get("status")
    if status not in {"READY", "READY_WITH_LIMITATIONS"}:
        raise ResourceExecutionError(
            f"RESOURCE_PLAN_NOT_READY: analysis {analysis_id} has resource plan status {status!r}."
        )

    selected = list(plan.get("selected") or [])
    selected_by_id = {
        str(item.get("resource_id")): item
        for item in selected
        if item.get("resource_id")
    }
    selected_item = selected_by_id.get(str(resolved.resource_id))
    if selected_item is None:
        raise ResourceExecutionError(
            f"RESOURCE_NOT_SELECTED: resource {resolved.resource_id} is not part of "
            f"analysis profile {profile_id!r} preflight plan."
        )

    required_capability = _STEP_REQUIRED_CAPABILITY.get(step_id)
    if required_capability and selected_item.get("capability") != required_capability:
        raise ResourceExecutionError(
            f"RESOURCE_CAPABILITY_MISMATCH: step {step_id!r} requires {required_capability!r}, "
            f"but preflight selected capability {selected_item.get('capability')!r} for resource "
            f"{resolved.resource_id}."
        )

    snapshot = dict(selected_item.get("execution") or {})
    expected = {
        "resource_id": str(resolved.resource_id),
        "resource_version": resolved.resource_version,
        "qualification_id": str(resolved.qualification_id),
        "qualification_version": resolved.qualification_version,
        "contract_hash": resolved.contract_hash,
    }
    actual = {
        "resource_id": str(snapshot.get("resource_id")),
        "resource_version": snapshot.get("resource_version"),
        "qualification_id": str(snapshot.get("qualification_id")),
        "qualification_version": snapshot.get("qualification_version"),
        "contract_hash": snapshot.get("contract_hash"),
    }
    if actual != expected:
        raise ResourceExecutionError(
            "RESOURCE_PLAN_STALE: the qualified runtime contract no longer matches "
            f"the preflight snapshot for resource {resolved.resource_id}; "
            f"expected={expected}, actual={actual}."
        )


def start_resource_execution(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    attempt: int,
    resolved: ResolvedResourceExecution,
    requested_resource_id: UUID | None,
    fallback_resource_id: UUID | None,
    batch_key: str | None = None,
    metadata: dict | None = None,
):
    from datetime import datetime, timezone
    from uuid import uuid4
    from backend.app.infrastructure.db.models import ResourceExecutionRecord

    _validate_profile_runtime_binding(
        db,
        analysis_id=analysis_id,
        step_id=step_id,
        resolved=resolved,
    )

    contract = resolved.contract
    row = ResourceExecutionRecord(
        id=uuid4(),
        analysis_id=analysis_id,
        step_id=step_id,
        attempt=attempt,
        batch_key=batch_key,
        resource_id=resolved.resource_id,
        requested_resource_id=requested_resource_id,
        fallback_resource_id=fallback_resource_id,
        qualification_id=resolved.qualification_id,
        qualification_version=resolved.qualification_version,
        resource_version=resolved.resource_version,
        provider_id=contract.provider_id,
        provider_version=contract.provider_version,
        access_method=contract.access_method,
        endpoint=contract.endpoint,
        location=contract.location,
        dataset=contract.dataset,
        contract_hash=resolved.contract_hash,
        contract_json=contract.as_dict(),
        status="STARTED",
        metadata_json=metadata or {},
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def complete_resource_execution(
    db: Session,
    row,
    *,
    status: str,
    request_fingerprint: str | None = None,
    response_sha256: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
):
    from datetime import datetime, timezone

    row.status = status
    row.request_fingerprint = request_fingerprint
    row.response_sha256 = response_sha256
    row.error_code = error_code
    row.error_message = error_message
    row.completed_at = datetime.now(timezone.utc)
    db.add(row)
    db.flush()
