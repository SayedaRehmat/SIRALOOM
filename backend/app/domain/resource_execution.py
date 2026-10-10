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


def _assert_profile_bound_resource_execution(
    db: Session,
    *,
    analysis_id: UUID,
    step_id: str,
    resolved: ResolvedResourceExecution,
) -> None:
    """Fail closed unless a profile-bound analysis executes its exact selection.

    Runtime stage code may discover legacy resources for backward compatibility,
    but a laboratory/profile-bound analysis has an immutable preflight plan. This
    guard prevents any stage from consuming a resource that was not selected in
    that plan, or from consuming the selected resource under a changed execution
    qualification/contract.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise ResourceExecutionError(
            f"Analysis {analysis_id} was not found while validating resource binding."
        )

    configuration = dict(analysis.configuration or {})
    if not configuration.get("resource_profile_id"):
        return

    plan = dict(configuration.get("resource_plan") or {})
    if plan.get("status") not in {"READY", "READY_WITH_LIMITATIONS"}:
        raise ResourceExecutionError(
            f"Profile-bound analysis {analysis_id} has a non-runnable resource plan: {plan.get('status')!r}."
        )

    allowed_capabilities = {
        "normalize": {"REFERENCE_PACKAGE"},
        "annotate": {"ANNOTATION_ENGINE"},
        "population": {"POPULATION", "POPULATION_SECONDARY"},
        "build_evidence": {
            "CLINICAL_DATABASE",
            "GENE_DISEASE",
            "PHENOTYPE_ONTOLOGY",
            "COMPUTATIONAL_PREDICTOR",
            "SPLICING_PREDICTOR",
            "FUNCTIONAL_EVIDENCE",
            "LITERATURE_PROVIDER",
            "INTERNAL_LAB_EVIDENCE",
        },
        "acmg_assessment": {"ACMG_RULE_SPECIFICATION"},
    }
    capabilities_for_step = allowed_capabilities.get(step_id)
    if capabilities_for_step is None:
        raise ResourceExecutionError(
            f"Profile-bound resource execution is not permitted for workflow step {step_id!r}."
        )

    selected = [
        dict(item)
        for item in (plan.get("selected") or [])
        if str(item.get("resource_id")) == str(resolved.resource_id)
    ]
    if len(selected) != 1:
        raise ResourceExecutionError(
            f"Resource {resolved.resource_id} was not selected exactly once by the immutable "
            f"resource plan for analysis {analysis_id}."
        )

    snapshot = selected[0]
    capability = str(snapshot.get("capability") or "")
    if capability not in capabilities_for_step:
        raise ResourceExecutionError(
            f"Resource {resolved.resource_id} is bound to capability {capability!r}, "
            f"which is not executable by workflow step {step_id!r}."
        )

    expected_execution = dict(snapshot.get("execution") or {})
    expected = {
        "resource_id": str(expected_execution.get("resource_id")),
        "resource_version": expected_execution.get("resource_version"),
        "qualification_id": str(expected_execution.get("qualification_id")),
        "qualification_version": expected_execution.get("qualification_version"),
        "contract_hash": expected_execution.get("contract_hash"),
    }
    actual = {
        "resource_id": str(resolved.resource_id),
        "resource_version": resolved.resource_version,
        "qualification_id": str(resolved.qualification_id),
        "qualification_version": resolved.qualification_version,
        "contract_hash": resolved.contract_hash,
    }
    if actual != expected:
        raise ResourceExecutionError(
            f"Runtime resource qualification differs from the immutable preflight plan: "
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

    _assert_profile_bound_resource_execution(
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
