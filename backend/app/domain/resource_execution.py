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
from backend.app.infrastructure.db.models import Resource, ResourceQualification


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
