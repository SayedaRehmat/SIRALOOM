from __future__ import annotations

"""Pluggable discovery for scientific resources."""

from importlib.metadata import entry_points
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.resources import register_resource_version, request_resource_approval
from backend.app.domain.resource_source_contract import validate_source_contract
from backend.app.domain.resource_staging import create_staging_candidate
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Notification,
    OrganizationMembership,
    OrganizationResourceBinding,
    ResourceApproval,
    ResourceDiscovery,
    User,
)

RESOURCE_PROVIDER_GROUP = "siraloom.resource_providers"
RESOURCE_NOTIFICATION_ROLES = frozenset({
    "organization_admin", "lab_director", "bioinformatician", "clinical_geneticist",
})


def _provider_entries() -> list[Any]:
    discovered = entry_points()
    if hasattr(discovered, "select"):
        entries = discovered.select(group=RESOURCE_PROVIDER_GROUP)
    else:
        entries = discovered.get(RESOURCE_PROVIDER_GROUP, [])
    return list(entries)


def _provider_identity(provider: Any) -> str:
    return f"{provider.__class__.__module__}.{provider.__class__.__name__}"


def _entry_point_identity(entry: Any) -> str:
    return str(
        getattr(entry, "value", None)
        or getattr(entry, "name", None)
        or f"{entry.__class__.__module__}.{entry.__class__.__name__}"
    )


def discover_resource_candidates(db: Session) -> dict[str, int]:
    """Run installed resource-provider adapters and create CANDIDATE records.

    Discovery never activates a resource. Qualification and activation are
    separate governed operations.
    """
    discovered_count = 0
    failed_providers = 0
    for entry in _provider_entries():
        provider_id = _entry_point_identity(entry)
        try:
            provider = entry.load()
            provider = provider() if isinstance(provider, type) else provider
            provider_id = _provider_identity(provider)
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
                        "discovery_provider": provider_id,
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
                        metadata_json={"discovery_provider": provider_id},
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
                if destination_uri:
                    create_staging_candidate(
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
        except Exception as exc:
            db.rollback()
            error_type = type(exc).__name__
            AuditService(db).record(
                event_type="RESOURCE_DISCOVERY_PROVIDER_FAILED",
                case_id=None,
                analysis_id=None,
                actor_type="SYSTEM",
                actor_id="resource-discovery",
                subject_type="RESOURCE_PROVIDER",
                subject_id=provider_id,
                operation="DISCOVER",
                reason=f"Resource provider discovery failed ({error_type}).",
                workflow={"domain": "scientific_resource_discovery"},
                payload={"provider_id": provider_id, "error_type": error_type},
            )
            db.commit()
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

def notify_organizations_of_qualified_release(
    db: Session,
    *,
    resource,
    qualification,
) -> int:
    """Create lab-specific approval requests and notifications after qualification.

    Discovery alone never creates an approval request. Only a technically
    QUALIFIED normalization or VCF specification release reaches this boundary. Each organization
    receives its own pending decision; no active binding is changed here.
    """
    if (
        str(resource.resource_type or "").strip().upper() not in {"NORMALIZATION", "VCF_SPECIFICATION"}
        or str(qualification.status or "").strip().upper() != "QUALIFIED"
        or str(resource.status or "").strip().upper() not in {"QUALIFIED", "ACTIVE", "SUPERSEDED"}
    ):
        return 0

    identity_key = "|".join([
        resource.name,
        resource.provider,
        resource.resource_type,
        resource.genome_build or "UNSPECIFIED",
    ])
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

    created = 0
    for membership, user in db.execute(query).all():
        # A binding to this release does not imply approval of a newer
        # qualification record. The qualification-scoped approval below is
        # the idempotency boundary and must be requested even for the same
        # resource row when its qualification changes.

        existing = db.scalar(
            select(ResourceApproval).where(
                ResourceApproval.resource_id == resource.id,
                ResourceApproval.organization_id == membership.organization_id,
                ResourceApproval.qualification_id == qualification.id,
            ).limit(1)
        )
        if existing is not None:
            continue

        approval = request_resource_approval(
            db,
            resource_id=resource.id,
            organization_id=membership.organization_id,
            qualification_version=qualification.qualification_version,
        )
        if resource.resource_type == "VCF_SPECIFICATION":
            title = f"Qualified VCF specification available: {resource.version}"
            body = (
                f"SIRALOOM has qualified parser conformance for {resource.version}. "
                "Your laboratory must approve this exact specification version before "
                "files declaring it can enter clinical analysis."
            )
            title_ar = f"مواصفة VCF مؤهلة متاحة: {resource.version}"
            body_ar = (
                f"أكمل SIRALOOM تأهيل توافق المحلل للمواصفة {resource.version}. "
                "يجب على المختبر الموافقة على هذا الإصدار تحديدًا قبل إدخال الملفات "
                "التي تعلنه في التحليل السريري."
            )
        else:
            title = f"Qualified normalization release available: {resource.name} {resource.version}"
            body = (
                f"SIRALOOM has technically qualified {resource.provider} version {resource.version}. "
                "Your laboratory must approve or reject this release before new analyses can use it. "
                "Your currently approved normalization resource remains unchanged until approval."
            )
            title_ar = f"إصدار تطبيع مؤهل متاح: {resource.name} {resource.version}"
            body_ar = (
                f"أكمل SIRALOOM التأهيل التقني للإصدار {resource.version} من {resource.provider}. "
                "يجب على المختبر الموافقة على هذا الإصدار أو رفضه قبل استخدامه في التحليلات الجديدة. "
                "سيظل مورد التطبيع المعتمد حاليًا دون تغيير حتى الموافقة."
            )
        db.add(Notification(
            id=uuid4(),
            organization_id=membership.organization_id,
            user_id=membership.user_id,
            notification_type="RESOURCE_RELEASE_QUALIFIED",
            status="UNREAD",
            title=title,
            body=body,
            metadata_json={
                "resource_id": str(resource.id),
                "qualification_id": str(qualification.id),
                "qualification_version": qualification.qualification_version,
                "approval_id": str(approval.id),
                "provider": resource.provider,
                "resource_name": resource.name,
                "release_version": resource.version,
                "checksum": resource.checksum,
                "requires_lab_decision": True,
                "title_ar": title_ar,
                "body_ar": body_ar,
            },
        ))
        AuditService(db).record(
            event_type="RESOURCE_ADOPTION_REQUESTED",
            case_id=None,
            analysis_id=None,
            actor_type="SYSTEM",
            actor_id="resource-qualification",
            subject_type="RESOURCE",
            subject_id=str(resource.id),
            operation="REQUEST_APPROVAL",
            after_state={
                "approval_id": str(approval.id),
                "approval_version": approval.version,
                "status": approval.status,
                "qualification_id": str(qualification.id),
                "qualification_version": qualification.qualification_version,
            },
            workflow={
                "domain": "resource_registry",
                "organization_id": str(membership.organization_id),
                "trigger": "RESOURCE_RELEASE_QUALIFIED",
            },
            resource_versions={
                "requested": {
                    "resource_id": str(resource.id),
                    "version": resource.version,
                    "checksum": resource.checksum,
                },
            },
        )
        created += 1
    return created

