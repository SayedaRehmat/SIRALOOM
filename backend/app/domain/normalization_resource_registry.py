"""Registry extension for globally heterogeneous VCF normalization engines.

Normalization releases are deliberately registered as CANDIDATE resources. A
successful technical qualification does not change production execution. The
laboratory must approve the qualified release, creating its organization-scoped
binding. Existing bindings therefore remain untouched when a new release is
qualified, rejected, or merely awaiting a decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.resource_execution import (
    ResolvedResourceExecution,
    ResourceExecutionError,
    resolve_resource_execution,
)
from backend.app.infrastructure.db.models import (
    Analysis,
    Case,
    OrganizationResourceBinding,
    Resource,
    ResourceQualification,
)

NORMALIZATION_RESOURCE_TYPE = "NORMALIZATION"


class NormalizationResourceRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizationResourceSelection:
    resource: Resource
    execution: ResolvedResourceExecution

    @property
    def snapshot(self) -> dict[str, object]:
        return {
            "resource_id": str(self.resource.id),
            "name": self.resource.name,
            "provider": self.resource.provider,
            "version": self.resource.version,
            "genome_build": self.resource.genome_build,
            "checksum": self.resource.checksum,
            "execution": self.execution.snapshot,
        }


def register_normalization_resource(
    db: Session,
    *,
    name: str,
    provider: str,
    version: str,
    genome_build: str | None,
    access_method: str,
    location: str | None,
    checksum: str | None,
    metadata_json: dict | None = None,
    organization_id: UUID | None = None,
) -> tuple[Resource, bool]:
    """Register a normalization engine release without activating it.

    Every discovered release enters CANDIDATE state. In particular, this function
    never supersedes an existing ACTIVE release and never creates an organization
    binding. Qualification and laboratory adoption remain separate operations.
    """
    provider = str(provider or "").strip()
    version = str(version or "").strip()
    name = str(name or "").strip()
    access_method = str(access_method or "").strip().upper()
    if not name or not provider or not version or not access_method:
        raise NormalizationResourceRegistryError(
            "name, provider, version and access_method are required"
        )
    if checksum is not None and len(str(checksum).strip()) != 64:
        raise NormalizationResourceRegistryError("checksum must be a SHA-256 digest")

    metadata = dict(metadata_json or {})
    capabilities = {
        str(item).strip().upper()
        for item in (metadata.get("capabilities") or [])
        if str(item).strip()
    }
    capabilities.add("NORMALIZATION")
    metadata["capabilities"] = sorted(capabilities)
    metadata.setdefault("normalization_contract_version", "1")
    metadata.setdefault("execution", {})
    metadata["execution"] = {
        **dict(metadata["execution"] or {}),
        "provider_id": provider,
        "provider_version": version,
        "access_method": access_method,
        "location": location,
    }

    existing = db.scalar(
        select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.name == name,
            Resource.provider == provider,
            Resource.resource_type == NORMALIZATION_RESOURCE_TYPE,
            Resource.version == version,
            Resource.genome_build == genome_build,
            Resource.checksum == checksum,
        ).limit(1)
    )
    if existing is not None:
        return existing, False

    resource = Resource(
        id=uuid4(),
        organization_id=organization_id,
        name=name,
        provider=provider,
        resource_type=NORMALIZATION_RESOURCE_TYPE,
        version=version,
        genome_build=genome_build,
        access_method=access_method,
        license_text=None,
        checksum=checksum,
        location=location,
        status="CANDIDATE",
        population_definition=None,
        metadata_json=metadata,
        created_at=datetime.now(UTC),
    )
    db.add(resource)
    db.flush()
    return resource, True


def list_qualified_normalization_releases(
    db: Session,
    *,
    genome_build: str | None = None,
) -> list[Resource]:
    conditions = [
        Resource.resource_type == NORMALIZATION_RESOURCE_TYPE,
        Resource.status == "QUALIFIED",
    ]
    if genome_build:
        conditions.append(Resource.genome_build == genome_build)
    return list(
        db.scalars(
            select(Resource)
            .where(*conditions)
            .order_by(Resource.provider, Resource.name, Resource.version)
        ).all()
    )


def _analysis_case(db: Session, analysis: Analysis) -> Case:
    case = db.get(Case, analysis.case_id)
    if case is None:
        raise NormalizationResourceRegistryError("analysis case not found")
    return case


def resolve_approved_normalization_resource(
    db: Session,
    *,
    analysis_id: UUID,
    resource_id: UUID | None = None,
) -> NormalizationResourceSelection:
    """Resolve the exact organization-approved normalization release.

    A supplied resource ID is honored only when it is the organization's current
    binding. Without an ID, the organization's current normalization binding is
    used. There is deliberately no "latest" lookup and no automatic fallback to
    another provider/version.
    """
    analysis = db.get(Analysis, analysis_id)
    if analysis is None:
        raise NormalizationResourceRegistryError("analysis not found")
    case = _analysis_case(db, analysis)

    if resource_id is not None:
        resource = db.get(Resource, resource_id)
        if resource is None:
            raise NormalizationResourceRegistryError("requested normalization resource not found")
        binding = db.scalar(
            select(OrganizationResourceBinding).where(
                OrganizationResourceBinding.organization_id == case.organization_id,
                OrganizationResourceBinding.resource_id == resource.id,
                OrganizationResourceBinding.resource_type == NORMALIZATION_RESOURCE_TYPE,
            ).limit(1)
        )
    else:
        binding = db.scalar(
            select(OrganizationResourceBinding)
            .where(
                OrganizationResourceBinding.organization_id == case.organization_id,
                OrganizationResourceBinding.resource_type == NORMALIZATION_RESOURCE_TYPE,
            )
            .order_by(OrganizationResourceBinding.updated_at.desc(), OrganizationResourceBinding.version.desc())
            .limit(1)
        )
        resource = db.get(Resource, binding.resource_id) if binding else None

    if binding is None or resource is None:
        raise NormalizationResourceRegistryError(
            "No organization-approved normalization release is bound to this laboratory."
        )
    if resource.resource_type != NORMALIZATION_RESOURCE_TYPE:
        raise NormalizationResourceRegistryError("bound resource is not a normalization engine")
    if resource.status not in {"QUALIFIED", "ACTIVE", "SUPERSEDED"}:
        raise NormalizationResourceRegistryError(
            f"bound normalization release is not executable: {resource.status}"
        )
    qualification_id = _qualification_id_for_binding(db, resource.id, binding.organization_id)
    try:
        execution = resolve_resource_execution(
            db,
            resource=resource,
            qualification_id=qualification_id,
        )
    except ResourceExecutionError as exc:
        raise NormalizationResourceRegistryError(str(exc)) from exc
    return NormalizationResourceSelection(resource=resource, execution=execution)


def _qualification_id_for_binding(
    db: Session,
    resource_id: UUID,
    organization_id: UUID,
) -> UUID:
    # Approval bindings are organization-scoped; select the successful
    # qualification that backs the bound release rather than re-qualifying it.
    from backend.app.infrastructure.db.models import ResourceApproval

    approval = db.scalar(
        select(ResourceApproval)
        .join(
            ResourceQualification,
            ResourceQualification.id == ResourceApproval.qualification_id,
        )
        .where(
            ResourceApproval.resource_id == resource_id,
            ResourceApproval.organization_id == organization_id,
            ResourceApproval.status == "APPROVED",
            ResourceQualification.status == "QUALIFIED",
        )
        .order_by(ResourceApproval.version.desc())
        .limit(1)
    )
    if approval is None:
        raise NormalizationResourceRegistryError(
            "Approved normalization binding has no successful technical qualification."
        )
    return approval.qualification_id
