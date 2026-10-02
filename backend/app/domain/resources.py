from __future__ import annotations

import re
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    OrganizationResourceBinding,
    Resource,
    ResourceApproval,
    ResourceApprovalAction,
    ResourceQualification,
    AuditEvent,
)

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_TYPES = frozenset({
    "REFERENCE", "REFERENCE_PACKAGE", "POPULATION", "ANNOTATION",
    "EVIDENCE", "ACMG_RULE",
})
RESOURCE_STATUSES = frozenset({
    "CANDIDATE", "QUALIFIED", "ACTIVE", "SUPERSEDED", "REJECTED", "QUARANTINED",
})


class ResourceRegistryError(ValueError):
    pass


def _normalize_checksum(checksum: str | None) -> str | None:
    if checksum is None or not checksum.strip():
        return None
    value = checksum.strip().lower()
    if not _SHA256_RE.fullmatch(value):
        raise ResourceRegistryError("checksum must be a 64-character SHA-256 hex digest")
    return value


def _validate_status(status: str) -> str:
    value = status.strip().upper()
    if value not in RESOURCE_STATUSES:
        raise ResourceRegistryError(
            f"unsupported resource status '{status}'; expected one of {sorted(RESOURCE_STATUSES)}"
        )
    return value


def register_resource_version(
    db: Session,
    *,
    name: str,
    provider: str,
    resource_type: str,
    version: str,
    genome_build: str | None,
    access_method: str,
    license_text: str | None,
    checksum: str | None,
    location: str | None,
    population_definition: dict | None,
    metadata_json: dict | None = None,
    organization_id: UUID | None = None,
    initial_status: str = "ACTIVE",
) -> tuple[Resource, bool]:
    """Register an immutable resource version.

    Existing callers may continue registering trusted resources as ACTIVE.
    Automated discovery should use CANDIDATE; candidates can only become
    production resources after an explicit qualification and activation step.
    """
    normalized_type = resource_type.strip().upper()
    if normalized_type not in _ALLOWED_TYPES:
        raise ResourceRegistryError(
            f"unsupported resource_type '{resource_type}'; expected one of {sorted(_ALLOWED_TYPES)}"
        )
    status = _validate_status(initial_status)

    values = {
        "organization_id": organization_id,
        "name": name.strip(),
        "provider": provider.strip(),
        "resource_type": normalized_type,
        "version": version.strip(),
        "genome_build": genome_build.strip() if genome_build else None,
        "access_method": access_method.strip(),
        "license_text": license_text,
        "checksum": _normalize_checksum(checksum),
        "location": location,
        "status": status,
        "population_definition": population_definition,
        "metadata_json": metadata_json or {},
    }
    for field in ("name", "provider", "version", "access_method"):
        if not values[field]:
            raise ResourceRegistryError(f"{field} is required")

    existing = db.scalar(
        select(Resource).where(
            Resource.organization_id == values["organization_id"],
            Resource.name == values["name"],
            Resource.provider == values["provider"],
            Resource.resource_type == values["resource_type"],
            Resource.version == values["version"],
            Resource.genome_build == values["genome_build"],
            Resource.checksum == values["checksum"],
        ).limit(1)
    )
    if existing:
        return existing, False

    if status == "ACTIVE":
        _supersede_active_identity(
            db,
            organization_id=values["organization_id"],
            name=values["name"],
            provider=values["provider"],
            resource_type=values["resource_type"],
            genome_build=values["genome_build"],
        )

    resource = Resource(
        id=uuid4(),
        **values,
    )
    db.add(resource)
    db.flush()
    return resource, True


def _supersede_active_identity(
    db: Session,
    *,
    organization_id: UUID | None,
    name: str,
    provider: str,
    resource_type: str,
    genome_build: str | None,
) -> None:
    active_rows = db.scalars(
        select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.name == name,
            Resource.provider == provider,
            Resource.resource_type == resource_type,
            Resource.genome_build == genome_build,
            Resource.status == "ACTIVE",
        )
    ).all()
    for row in active_rows:
        row.status = "SUPERSEDED"


def qualify_resource_version(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str,
    checks: dict,
    qualified_by: UUID | None,
) -> ResourceQualification:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if resource.status not in {"CANDIDATE", "QUALIFIED"}:
        raise ResourceRegistryError(
            f"resource status {resource.status!r} cannot be qualified"
        )
    if not qualification_version.strip():
        raise ResourceRegistryError("qualification_version is required")
    if not isinstance(checks, dict) or not isinstance(checks.get("passed"), bool):
        raise ResourceRegistryError("qualification result must contain boolean checks.passed")

    passed = bool(checks["passed"])
    qualification_status = "QUALIFIED" if passed else "BLOCKED"
    qualification = db.scalar(
        select(ResourceQualification).where(
            ResourceQualification.resource_id == resource_id,
            ResourceQualification.qualification_version == qualification_version.strip(),
        )
    )
    if qualification is None:
        qualification = ResourceQualification(
            id=uuid4(),
            resource_id=resource_id,
            qualification_version=qualification_version.strip(),
            status=qualification_status,
            checks_json=checks,
            qualified_by=qualified_by,
            qualified_at=datetime.now(timezone.utc),
        )
        db.add(qualification)
    else:
        qualification.status = qualification_status
        qualification.checks_json = checks
        qualification.qualified_by = qualified_by
        qualification.qualified_at = datetime.now(timezone.utc)

    if passed:
        resource.status = "QUALIFIED"
    elif resource.status == "QUALIFIED":
        resource.status = "CANDIDATE"
    db.flush()
    return qualification


def activate_resource_version(
    db: Session,
    *,
    resource_id: UUID,
    qualification_version: str,
) -> Resource:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if resource.status != "QUALIFIED":
        raise ResourceRegistryError(
            "only QUALIFIED resources can be activated"
        )

    qualification = db.scalar(
        select(ResourceQualification).where(
            ResourceQualification.resource_id == resource_id,
            ResourceQualification.qualification_version == qualification_version.strip(),
            ResourceQualification.status == "QUALIFIED",
        )
    )
    if qualification is None:
        raise ResourceRegistryError(
            "matching successful qualification is required before activation"
        )

    _supersede_active_identity(
        db,
        organization_id=resource.organization_id,
        name=resource.name,
        provider=resource.provider,
        resource_type=resource.resource_type,
        genome_build=resource.genome_build,
    )
    resource.status = "ACTIVE"
    db.flush()
    return resource



def request_resource_approval(db: Session, *, resource_id: UUID, organization_id: UUID, qualification_version: str) -> ResourceApproval:
    resource = db.get(Resource, resource_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if resource.organization_id is not None and resource.organization_id != organization_id:
        raise ResourceRegistryError("resource is owned by another organization")
    qualification = db.scalar(select(ResourceQualification).where(
        ResourceQualification.resource_id == resource_id,
        ResourceQualification.qualification_version == qualification_version.strip(),
        ResourceQualification.status == "QUALIFIED",
    ))
    if qualification is None:
        raise ResourceRegistryError("matching successful qualification is required before approval")
    existing = db.scalar(select(ResourceApproval).where(
        ResourceApproval.resource_id == resource_id,
        ResourceApproval.organization_id == organization_id,
        ResourceApproval.qualification_id == qualification.id,
    ))
    if existing:
        return existing
    approval = ResourceApproval(id=uuid4(), resource_id=resource_id, organization_id=organization_id,
                               qualification_id=qualification.id, status="PENDING", version=1)
    db.add(approval)
    db.flush()
    return approval


def decide_resource_approval(
    db: Session, *, approval_id: UUID, organization_id: UUID, actor_id: UUID,
    decision: str, expected_version: int, reason: str | None,
) -> ResourceApproval:
    decision = decision.strip().upper()
    if decision not in {"APPROVED", "REJECTED", "DEFERRED"}:
        raise ResourceRegistryError("decision must be APPROVED, REJECTED, or DEFERRED")
    approval = db.scalar(select(ResourceApproval).where(
        ResourceApproval.id == approval_id, ResourceApproval.organization_id == organization_id,
    ))
    if approval is None:
        raise ResourceRegistryError("approval request not found")
    if approval.status != "PENDING":
        raise ResourceRegistryError(f"approval request is already {approval.status}")
    if approval.version != expected_version:
        raise ResourceRegistryError("approval request changed; refresh before deciding")
    resource = db.get(Resource, approval.resource_id)
    qualification = db.get(ResourceQualification, approval.qualification_id)
    if resource is None:
        raise ResourceRegistryError("resource not found")
    if qualification is None or qualification.status != "QUALIFIED":
        raise ResourceRegistryError("approval requires a successful technical qualification")

    next_version = expected_version + 1
    result = db.execute(update(ResourceApproval).where(
        ResourceApproval.id == approval_id,
        ResourceApproval.organization_id == organization_id,
        ResourceApproval.status == "PENDING",
        ResourceApproval.version == expected_version,
    ).values(
        status=decision, version=next_version, decided_at=datetime.now(timezone.utc),
        decided_by=actor_id, reason=reason,
    ))
    if result.rowcount != 1:
        raise ResourceRegistryError("approval request changed concurrently; refresh before deciding")

    db.add(ResourceApprovalAction(
        id=uuid4(), approval_id=approval_id, organization_id=organization_id, actor_id=actor_id,
        action="DECIDE", before_status="PENDING", after_status=decision,
        expected_version=expected_version, resulting_version=next_version, reason=reason,
    ))

    if decision == "REJECTED":
        resource.status = "REJECTED"

    if decision == "APPROVED":
        resource_identity_key = "|".join([resource.name, resource.provider, resource.resource_type, resource.genome_build or "UNSPECIFIED"])
        binding = db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == organization_id,
            OrganizationResourceBinding.identity_key == resource_identity_key,
        ))
        previous_resource_id = binding.resource_id if binding else None
        previous_binding_version = binding.version if binding else None
        previous_resource = db.get(Resource, previous_resource_id) if previous_resource_id else None
        if binding is None:
            db.add(OrganizationResourceBinding(
                id=uuid4(), organization_id=organization_id, resource_id=resource.id,
                resource_name=resource.name, provider=resource.provider, resource_type=resource.resource_type,
                genome_build=resource.genome_build, identity_key=resource_identity_key, bound_by=actor_id, reason=reason, version=1,
            ))
        else:
            binding.previous_resource_id = previous_resource_id
            binding.resource_id = resource.id
            binding.bound_by = actor_id
            binding.bound_at = datetime.now(timezone.utc)
            binding.reason = reason
            binding.version += 1

    resulting_binding = None
    if decision == "APPROVED":
        resulting_binding = db.scalar(select(OrganizationResourceBinding).where(
            OrganizationResourceBinding.organization_id == organization_id,
            OrganizationResourceBinding.identity_key == "|".join([resource.name, resource.provider, resource.resource_type, resource.genome_build or "UNSPECIFIED"]),
        ))
    _record_resource_adoption_audit(
        db,
        approval=approval,
        resource=resource,
        qualification=qualification,
        organization_id=organization_id,
        actor_id=actor_id,
        decision=decision,
        reason=reason,
        previous_resource=previous_resource,
        binding=resulting_binding,
        previous_binding_version=previous_binding_version,
    )
    db.flush()
    db.refresh(approval)
    return approval



def _record_resource_adoption_audit(
    db: Session,
    *,
    approval: ResourceApproval,
    resource: Resource,
    qualification: ResourceQualification,
    organization_id: UUID,
    actor_id: UUID,
    decision: str,
    reason: str | None,
    previous_resource: Resource | None,
    binding: OrganizationResourceBinding | None,
    previous_binding_version: int | None,
) -> AuditEvent:
    """Persist immutable provenance for one organization release decision."""
    before_binding = None
    if previous_resource is not None:
        before_binding = {
            "resource_id": str(previous_resource.id),
            "version": previous_resource.version,
            "checksum": previous_resource.checksum,
            "binding_version": previous_binding_version,
        }
    after_binding = None
    if binding is not None and decision == "APPROVED":
        after_binding = {
            "binding_id": str(binding.id),
            "resource_id": str(binding.resource_id),
            "version": resource.version,
            "checksum": resource.checksum,
            "binding_version": binding.version,
        }
    payload = {
        "approval_id": str(approval.id),
        "approval_version": approval.version,
        "qualification_id": str(qualification.id),
        "qualification_version": qualification.qualification_version,
        "decision": decision,
        "reason": reason,
        "previous_binding": before_binding,
        "resulting_binding": after_binding,
    }
    event_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    event = AuditEvent(
        id=uuid4(),
        event_version="1",
        event_type="RESOURCE_ADOPTION_DECISION",
        actor_type="USER",
        actor_id=str(actor_id),
        subject_type="RESOURCE",
        subject_id=str(resource.id),
        operation=decision,
        before_state={
            "resource_id": str(resource.id),
            "resource_version": resource.version,
            "resource_status": "QUALIFIED",
            "binding": before_binding,
        },
        after_state={
            "resource_id": str(resource.id),
            "resource_version": resource.version,
            "resource_status": resource.status,
            "binding": after_binding,
        },
        reason=reason,
        software={},
        workflow={"domain": "resource_registry", "approval_id": str(approval.id), "approval_version": approval.version},
        resource_versions={
            "requested": {"resource_id": str(resource.id), "version": resource.version, "checksum": resource.checksum},
            "previous": before_binding,
            "resulting": after_binding,
        },
        payload=payload,
        event_hash=event_hash,
    )
    db.add(event)
    return event

def get_active_resource_for_organization(
    db: Session, *, organization_id: UUID, name: str, provider: str,
    resource_type: str, genome_build: str | None,
) -> Resource | None:
    binding = db.scalar(select(OrganizationResourceBinding).where(
        OrganizationResourceBinding.organization_id == organization_id,
        OrganizationResourceBinding.identity_key == "|".join([name, provider, resource_type, genome_build or "UNSPECIFIED"]),
    ))
    if binding:
        return db.get(Resource, binding.resource_id)
    return db.scalar(select(Resource).where(
        Resource.organization_id.is_(None), Resource.name == name, Resource.provider == provider,
        Resource.resource_type == resource_type, Resource.genome_build == genome_build,
        Resource.status == "ACTIVE",
    ))
