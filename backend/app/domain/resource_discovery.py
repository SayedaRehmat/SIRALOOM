from __future__ import annotations

"""Pluggable discovery for scientific resources."""

from importlib.metadata import entry_points
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.resources import register_resource_version
from backend.app.domain.resource_source_contract import validate_source_contract
from backend.app.domain.resource_staging import create_staging_candidate
from backend.app.infrastructure.db.models import (
    Notification,
    OrganizationMembership,
    ResourceDiscovery,
    ResourceStaging,
    User,
)

RESOURCE_PROVIDER_GROUP = "siraloom.resource_providers"
RESOURCE_NOTIFICATION_ROLES = frozenset({
    "organization_admin", "lab_director", "bioinformatician", "clinical_geneticist",
})


def _provider_instances() -> list[Any]:
    discovered = entry_points()
    if hasattr(discovered, "select"):
        entries = discovered.select(group=RESOURCE_PROVIDER_GROUP)
    else:
        entries = discovered.get(RESOURCE_PROVIDER_GROUP, [])
    providers = []
    for entry in entries:
        provider = entry.load()
        providers.append(provider() if isinstance(provider, type) else provider)
    return providers


def discover_resource_candidates(db: Session) -> dict[str, int]:
    """Run installed resource-provider adapters and create CANDIDATE records.

    Discovery never activates a resource. Qualification and activation are
    separate governed operations.
    """
    discovered_count = 0
    failed_providers = 0
    for provider in _provider_instances():
        try:
            candidates: Iterable[dict[str, Any]] = provider.discover()
            for candidate in candidates:
                source_contract = validate_source_contract(dict(candidate.get("source_contract") or {}))
                organization_id = UUID(str(candidate["organization_id"])) if candidate.get("organization_id") else None
                resource, _ = register_resource_version(
                    db,
                    name=str(candidate.get("name") or ""),
                    provider=str(candidate.get("provider") or ""),
                    resource_type=str(candidate.get("resource_type") or ""),
                    version=str(candidate.get("version") or ""),
                    genome_build=str(candidate["genome_build"]) if candidate.get("genome_build") else None,
                    access_method=str(candidate.get("access_method") or ""),
                    license_text=candidate.get("license_text"),
                    checksum=candidate.get("checksum"),
                    location=candidate.get("location"),
                    population_definition=candidate.get("population_definition"),
                    metadata_json={
                        **dict(candidate.get("metadata") or {}),
                        "source_contract": source_contract.as_dict(),
                        "discovery_provider": provider.__class__.__module__ + "." + provider.__class__.__name__,
                    },
                    organization_id=organization_id,
                    initial_status="CANDIDATE",
                )
                existing_discovery = db.scalar(
                    select(ResourceDiscovery).where(
                        ResourceDiscovery.resource_id == resource.id,
                        ResourceDiscovery.release_identity == str(candidate.get("version") or ""),
                        ResourceDiscovery.artifact_url == source_contract.artifact_url,
                    )
                )
                is_new_discovery = existing_discovery is None
                if is_new_discovery:
                    discovery = ResourceDiscovery(
                        id=uuid4(),
                        resource_id=resource.id,
                        publisher=source_contract.publisher,
                        canonical_source_url=source_contract.canonical_source_url,
                        artifact_url=source_contract.artifact_url,
                        release_identity=source_contract.release_identity,
                        access_mode=source_contract.access_mode,
                        license_status=source_contract.license_status,
                        license_url=source_contract.license_url,
                        terms_url=source_contract.terms_url,
                        checksum_status=source_contract.checksum_status,
                        expected_sha256=candidate.get("checksum"),
                        expected_size_bytes=candidate.get("expected_size_bytes"),
                        authority_evidence_url=source_contract.authority_evidence_url,
                        status="DISCOVERED",
                        metadata_json={"discovery_provider": provider.__class__.__module__ + "." + provider.__class__.__name__},
                    )
                    db.add(discovery)
                    db.flush()
                    _notify_organizations_of_release(
                        db,
                        resource=resource,
                        discovery=discovery,
                        source_contract=source_contract.as_dict(),
                    )
                else:
                    discovery = existing_discovery

                destination_uri = candidate.get("staging_destination")
                staging = None
                if destination_uri:
                    staging = create_staging_candidate(
                        db,
                        resource=resource,
                        source_uri=source_contract.artifact_url,
                        destination_uri=str(destination_uri),
                        storage_backend=str(candidate.get("storage_backend") or "LOCAL_FILESYSTEM"),
                        expected_sha256=candidate.get("checksum"),
                        expected_size_bytes=candidate.get("expected_size_bytes"),
                        staging_key=f"{resource.provider}:{resource.version}:{source_contract.artifact_url}",
                        metadata={"discovery_id": str(discovery.id), "publisher": source_contract.publisher},
                    )
                discovered_count += 1
        except Exception:
            db.rollback()
            failed_providers += 1
        else:
            db.commit()
    db.commit()
    return {"candidates_discovered": discovered_count, "providers_failed": failed_providers}

def _notify_organizations_of_release(
    db: Session,
    *,
    resource,
    discovery: ResourceDiscovery,
    source_contract: dict[str, object],
) -> int:
    """Notify active lab resource stewards once per newly persisted release."""
    query = (
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.status == "ACTIVE",
            OrganizationMembership.role.in_(RESOURCE_NOTIFICATION_ROLES),
            User.status == "ACTIVE",
        )
    )
    if resource.organization_id is not None:
        query = query.where(OrganizationMembership.organization_id == resource.organization_id)
    recipients = db.execute(query).all()
    created = 0
    for membership, user in recipients:
        db.add(Notification(
            id=uuid4(),
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            notification_type="RESOURCE_RELEASE_DISCOVERED",
            status="UNREAD",
            title=f"New {resource.provider} release discovered",
            body=(
                f"{resource.name} version {resource.version} was discovered from "
                f"{source_contract.get('publisher')}. Review the source contract, "
                "license/terms and integrity evidence before adopting or activating it."
            ),
            metadata_json={
                "resource_id": str(resource.id),
                "discovery_id": str(discovery.id),
                "provider": resource.provider,
                "resource_name": resource.name,
                "release_identity": discovery.release_identity,
                "artifact_url": discovery.artifact_url,
                "license_status": discovery.license_status,
                "checksum_status": discovery.checksum_status,
                "requires_lab_review": True,
                "title_ar": f"تم اكتشاف إصدار جديد من {resource.provider}",
                "body_ar": (
                    f"تم اكتشاف {resource.name} الإصدار {resource.version} من "
                    f"{source_contract.get('publisher')}. راجع عقد المصدر وشروط الترخيص "
                    "وأدلة السلامة قبل اعتماد الإصدار أو تفعيله."
                ),
            },
        ))
        created += 1
    return created
