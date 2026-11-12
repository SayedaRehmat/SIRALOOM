"""Governed retention and verification of exact provider response bytes."""
from __future__ import annotations

import hashlib
import re
import tempfile
from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.artifact_integrity import validate_integrity_expectations, verify_artifact_file
from backend.app.domain.storage_profiles import artifact_store_for_organization, artifact_store_for_uri
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Analysis, Artifact, Case, Evidence, OrganizationMembership,
    ProviderRetentionApproval, ProviderRetentionApprovalAction, Resource,
    ResourceDiscovery, User,
)


@dataclass(frozen=True)
class ProviderResponseRetention:
    status: str
    reason: str
    artifact_id: UUID | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    license_status: str = "UNKNOWN"


def _authorized_reviewer(db: Session, *, organization_id: UUID, reviewer_id: UUID) -> User:
    user = db.get(User, reviewer_id)
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.user_id == reviewer_id,
        OrganizationMembership.status == "ACTIVE",
    ))
    allowed_roles = {"LAB_ADMIN", "QUALITY_MANAGER", "COMPLIANCE_OFFICER", "DATA_GOVERNANCE_OFFICER"}
    if (
        user is None or user.organization_id != organization_id
        or str(user.status or "").upper() != "ACTIVE"
        or membership is None or str(membership.role or "").upper() not in allowed_roles
    ):
        raise PermissionError("Provider retention decisions require an active, authorized reviewer in the same organization.")
    return user


def _verify_terms_evidence_bytes(
    db: Session, *, organization_id: UUID, evidence: Artifact,
) -> None:
    """Recheck the approved terms artifact bytes before relying on its approval."""
    terms_case = db.get(Case, evidence.case_id)
    if terms_case is None or terms_case.organization_id != organization_id:
        raise PermissionError("Provider retention terms evidence belongs to another organization.")
    store = artifact_store_for_uri(
        db, organization_id=organization_id, storage_uri=evidence.storage_uri,
    )
    if callable(getattr(store, "download_to_file", None)):
        with tempfile.NamedTemporaryFile(prefix="siraloom-terms-gate-", delete=False) as handle:
            staged = Path(handle.name)
        try:
            store.download_to_file(
                evidence.storage_uri, staged,
                expected_sha256=evidence.sha256,
                expected_size_bytes=evidence.size_bytes,
            )
            verify_artifact_file(staged, sha256=evidence.sha256, size_bytes=evidence.size_bytes)
        finally:
            staged.unlink(missing_ok=True)
    else:
        verify_artifact_file(
            store.local_path(evidence.storage_uri),
            sha256=evidence.sha256,
            size_bytes=evidence.size_bytes,
        )


def _expire_approval_if_due(db: Session, approval: ProviderRetentionApproval) -> bool:
    """Persist automatic expiry as an append-only system decision."""
    if approval.status != "APPROVED" or approval.expires_at is None:
        return False
    expiry = approval.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if expiry > datetime.now(UTC):
        return False
    approval.status = "EXPIRED"
    db.flush()
    db.add(ProviderRetentionApprovalAction(
        id=__import__("uuid").uuid4(), approval_id=approval.id,
        organization_id=approval.organization_id, actor_id=None,
        action="EXPIRE", before_status="APPROVED", after_status="EXPIRED",
        reason="Approval expired under its recorded expiry condition.",
        permission_scope=list(approval.permission_scope or []),
    ))
    AuditService(db).record(
        event_type="PROVIDER_RETENTION_EXPIRED", case_id=None, analysis_id=None,
        actor_type="SYSTEM", actor_id="siraloom:provider-retention-expiry",
        subject_type="PROVIDER_RETENTION_APPROVAL", subject_id=str(approval.id),
        operation="EXPIRE", before_state={"status": "APPROVED"},
        after_state={"status": "EXPIRED"},
        reason="Approval expired under its recorded expiry condition.",
        payload={"organization_id": str(approval.organization_id),
            "resource_discovery_id": str(approval.resource_discovery_id),
            "permission_scope": list(approval.permission_scope or [])},
    )
    return True


def approve_provider_retention(
    db: Session, *, organization_id: UUID, resource_discovery_id: UUID,
    reviewer_id: UUID, permission_scope: list[str], reason: str,
    terms_evidence_artifact_id: UUID, terms_evidence_sha256: str,
    expires_at: datetime | None = None,
) -> ProviderRetentionApproval:
    """Create a versioned approval tied to exact release and immutable terms evidence."""
    discovery = db.get(ResourceDiscovery, resource_discovery_id)
    if discovery is None:
        raise ValueError("Provider retention approval requires an existing exact resource discovery.")
    resource = db.get(Resource, discovery.resource_id)
    if resource is None or resource.version != discovery.release_identity:
        raise ValueError("Provider retention approval release identity does not match the resource.")
    _authorized_reviewer(db, organization_id=organization_id, reviewer_id=reviewer_id)
    scopes = sorted({str(scope).strip().upper() for scope in permission_scope if str(scope).strip()})
    if "RAW_PROVIDER_RESPONSE_RETENTION" not in scopes:
        raise ValueError("Approval scope must explicitly include RAW_PROVIDER_RESPONSE_RETENTION.")
    if not reason.strip():
        raise ValueError("Approval requires a documented decision rationale.")
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ValueError("Approval expiry must be in the future.")
    evidence = db.get(Artifact, terms_evidence_artifact_id)
    if evidence is None or evidence.sha256.lower() != terms_evidence_sha256.lower():
        raise ValueError("Terms evidence artifact and SHA-256 do not match.")
    evidence_case = db.get(Case, evidence.case_id)
    if evidence_case is None or evidence_case.organization_id != organization_id:
        raise PermissionError("Terms evidence must belong to the approving organization.")
    terms_store = artifact_store_for_uri(
        db, organization_id=organization_id, storage_uri=evidence.storage_uri
    )
    if callable(getattr(terms_store, "download_to_file", None)):
        with tempfile.NamedTemporaryFile(prefix="siraloom-terms-approval-", delete=False) as handle:
            terms_path = Path(handle.name)
        try:
            terms_store.download_to_file(
                evidence.storage_uri, terms_path,
                expected_sha256=evidence.sha256,
                expected_size_bytes=evidence.size_bytes,
            )
            verify_artifact_file(terms_path, sha256=evidence.sha256, size_bytes=evidence.size_bytes)
        finally:
            terms_path.unlink(missing_ok=True)
    else:
        verify_artifact_file(
            terms_store.local_path(evidence.storage_uri),
            sha256=evidence.sha256, size_bytes=evidence.size_bytes,
        )
    if not (discovery.license_url or discovery.terms_url):
        raise ValueError("Exact release has no recorded license or terms URL.")
    now = datetime.now(UTC)
    existing = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.organization_id == organization_id,
        ProviderRetentionApproval.resource_discovery_id == resource_discovery_id,
        ProviderRetentionApproval.status == "APPROVED",
    ))
    if existing is not None:
        existing_expiry = existing.expires_at
        if existing_expiry is not None and existing_expiry.tzinfo is None:
            existing_expiry = existing_expiry.replace(tzinfo=UTC)
        if existing_expiry is None or existing_expiry > now:
            raise ValueError("An active approval already exists; revoke it before creating a replacement.")
        existing.status = "EXPIRED"
        db.flush()
        db.add(ProviderRetentionApprovalAction(
            id=__import__("uuid").uuid4(), approval_id=existing.id,
            organization_id=organization_id, actor_id=reviewer_id,
            action="EXPIRE", before_status="APPROVED", after_status="EXPIRED",
            reason="Approval expired before a replacement approval was issued.",
            permission_scope=list(existing.permission_scope or []),
        ))
        AuditService(db).record(
            event_type="PROVIDER_RETENTION_EXPIRED", case_id=None, analysis_id=None,
            actor_type="USER", actor_id=str(reviewer_id),
            subject_type="PROVIDER_RETENTION_APPROVAL", subject_id=str(existing.id),
            operation="EXPIRE", before_state={"status": "APPROVED"},
            after_state={"status": "EXPIRED"},
            reason="Approval expired before a replacement approval was issued.",
            payload={"organization_id": str(organization_id),
                "resource_discovery_id": str(resource_discovery_id)},
        )
    latest_version = db.scalar(select(ProviderRetentionApproval.version).where(
        ProviderRetentionApproval.organization_id == organization_id,
        ProviderRetentionApproval.resource_discovery_id == resource_discovery_id,
    ).order_by(ProviderRetentionApproval.version.desc()).limit(1)) or 0
    approval = ProviderRetentionApproval(
        id=__import__("uuid").uuid4(), organization_id=organization_id,
        resource_id=resource.id, resource_discovery_id=discovery.id,
        release_identity=discovery.release_identity, permission_scope=scopes,
        license_url=discovery.license_url, terms_url=discovery.terms_url,
        terms_evidence_artifact_id=evidence.id, terms_evidence_sha256=evidence.sha256,
        reviewer_id=reviewer_id, status="APPROVED", approved_at=now,
        expires_at=expires_at, version=latest_version + 1,
    )
    db.add(approval)
    db.flush()
    action = ProviderRetentionApprovalAction(
        id=__import__("uuid").uuid4(), approval_id=approval.id,
        organization_id=organization_id, actor_id=reviewer_id,
        action="APPROVE", before_status=None, after_status="APPROVED",
        reason=reason.strip(), permission_scope=scopes,
    )
    db.add(action)
    AuditService(db).record(
        event_type="PROVIDER_RETENTION_APPROVED", case_id=None, analysis_id=None,
        actor_type="USER", actor_id=str(reviewer_id),
        subject_type="PROVIDER_RETENTION_APPROVAL", subject_id=str(approval.id),
        operation="APPROVE", after_state={"status": "APPROVED", "version": approval.version},
        reason=reason.strip(), payload={"organization_id": str(organization_id),
            "resource_id": str(resource.id), "release_identity": discovery.release_identity,
            "resource_discovery_id": str(discovery.id), "permission_scope": scopes,
            "terms_evidence_artifact_id": str(evidence.id), "terms_evidence_sha256": evidence.sha256},
    )
    return approval


def revoke_provider_retention(
    db: Session, *, approval_id: UUID, actor_id: UUID, reason: str,
) -> ProviderRetentionApproval:
    """Revoke future use without deleting approval or decision history."""
    # Revocation must serialize with retention and verification, which take
    # the same approval-row lock before authorizing any future use.
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.id == approval_id,
    ).with_for_update().execution_options(populate_existing=True))
    if approval is None:
        raise ValueError("Provider retention approval does not exist.")
    _authorized_reviewer(db, organization_id=approval.organization_id, reviewer_id=actor_id)
    if not reason.strip():
        raise ValueError("Revocation requires a documented reason.")
    if approval.status != "APPROVED":
        raise ValueError("Only an active provider retention approval can be revoked.")
    before = approval.status
    approval.status = "REVOKED"
    approval.revoked_at = datetime.now(UTC)
    approval.revocation_reason = reason.strip()
    db.flush()
    db.add(ProviderRetentionApprovalAction(
        id=__import__("uuid").uuid4(), approval_id=approval.id,
        organization_id=approval.organization_id, actor_id=actor_id,
        action="REVOKE", before_status=before, after_status="REVOKED",
        reason=reason.strip(), permission_scope=list(approval.permission_scope or []),
    ))
    AuditService(db).record(
        event_type="PROVIDER_RETENTION_REVOKED", case_id=None, analysis_id=None,
        actor_type="USER", actor_id=str(actor_id),
        subject_type="PROVIDER_RETENTION_APPROVAL", subject_id=str(approval.id),
        operation="REVOKE", before_state={"status": before},
        after_state={"status": "REVOKED"}, reason=reason.strip(),
        payload={"organization_id": str(approval.organization_id),
            "resource_discovery_id": str(approval.resource_discovery_id),
            "permission_scope": list(approval.permission_scope or [])},
    )
    return approval


def _retention_permission(
    db: Session, resource: Resource, *, organization_id: UUID,
) -> tuple[str, str, ResourceDiscovery | None, ProviderRetentionApproval | None]:
    """Authorize raw retention only from a current, scoped, organization approval."""
    discovery = db.scalar(select(ResourceDiscovery).where(
        ResourceDiscovery.resource_id == resource.id,
        ResourceDiscovery.release_identity == resource.version,
    ).order_by(ResourceDiscovery.created_at.desc(), ResourceDiscovery.id.desc()).limit(1))
    if discovery is None:
        return "REVIEW_REQUIRED", "No source-discovery record matches the exact resource release.", None, None
    if str(discovery.status or "").upper() in {"REJECTED", "WITHDRAWN", "REVOKED", "BLOCKED"}:
        return "NOT_PERMITTED", "The exact resource release is blocked or withdrawn.", discovery, None
    if str(discovery.license_status or "").upper() == "RESTRICTED":
        return "NOT_PERMITTED", "The exact resource release is marked RESTRICTED.", discovery, None
    # Serialize expiry/revocation decisions with concurrent retention requests.
    # The row lock is held until the caller commits or rolls back its transaction.
    approval = db.scalar(select(ProviderRetentionApproval).where(
        ProviderRetentionApproval.organization_id == organization_id,
        ProviderRetentionApproval.resource_id == resource.id,
        ProviderRetentionApproval.resource_discovery_id == discovery.id,
        ProviderRetentionApproval.release_identity == resource.version,
        ProviderRetentionApproval.status == "APPROVED",
    ).order_by(ProviderRetentionApproval.version.desc()).limit(1).with_for_update().execution_options(populate_existing=True))
    if approval is None:
        return "REVIEW_REQUIRED", "No active organization-scoped approval exists for this exact release.", discovery, None
    now = datetime.now(UTC)
    expires = approval.expires_at
    if expires is not None:
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            _expire_approval_if_due(db, approval)
            return "REVIEW_REQUIRED", "The provider retention approval has expired.", discovery, approval
    if "RAW_PROVIDER_RESPONSE_RETENTION" not in set(approval.permission_scope or []):
        return "NOT_PERMITTED", "The approval does not include raw provider response retention.", discovery, approval
    try:
        _authorized_reviewer(db, organization_id=organization_id, reviewer_id=approval.reviewer_id)
    except PermissionError:
        return "REVIEW_REQUIRED", "The approving reviewer is no longer an active authorized organization member.", discovery, approval
    evidence = db.get(Artifact, approval.terms_evidence_artifact_id)
    if evidence is None or evidence.sha256.lower() != str(approval.terms_evidence_sha256 or "").lower():
        return "REVIEW_REQUIRED", "The terms evidence artifact is missing or its digest no longer matches.", discovery, approval
    try:
        _verify_terms_evidence_bytes(
            db, organization_id=organization_id, evidence=evidence,
        )
    except Exception:
        return "REVIEW_REQUIRED", "The approved provider terms evidence failed organization or byte-integrity verification.", discovery, approval
    return "RETAINED", "Exact release has a current organization approval with verified terms evidence.", discovery, approval


def retain_provider_response_bytes(
    db: Session,
    *,
    analysis: Analysis,
    resource: Resource,
    provider_id: str,
    provider_version: str,
    request_fingerprint: str,
    raw_response_bytes: bytes,
    media_type: str | None = None,
    store=None,
) -> ProviderResponseRetention:
    """Persist exact response bytes only after affirmative release-specific permission."""
    if not isinstance(raw_response_bytes, bytes) or not raw_response_bytes:
        return ProviderResponseRetention(
            "NOT_AVAILABLE", "Provider did not supply non-empty raw response bytes."
        )
    if analysis.case_id is None or analysis.id is None:
        raise ValueError("Provider response retention requires persisted analysis and case identity.")
    case = db.get(Case, analysis.case_id)
    if case is None or case.organization_id is None:
        raise ValueError("Provider response retention requires a case with organization identity.")
    permission, reason, discovery, approval = _retention_permission(
        db, resource, organization_id=case.organization_id
    )
    if permission != "RETAINED":
        return ProviderResponseRetention(
            permission, reason, license_status=(
                str(discovery.license_status).upper() if discovery else "UNKNOWN"
            )
        )
    if approval is None:
        raise RuntimeError("Provider retention gate returned RETAINED without a persisted approval.")
    digest = hashlib.sha256(raw_response_bytes).hexdigest()
    size = len(raw_response_bytes)
    artifact_id = uuid5(
        NAMESPACE_URL,
        f"siraloom-provider-response:{analysis.id}:{resource.id}:{request_fingerprint}",
    )
    store = store or artifact_store_for_organization(db, organization_id=case.organization_id)
    existing = db.get(Artifact, artifact_id)
    if existing is not None:
        existing_metadata = dict(existing.metadata_json or {})
        if (
            existing.case_id != case.id or existing.analysis_id != analysis.id
            or existing.artifact_type != "PROVIDER_RESPONSE_RAW"
            or existing.sha256 != digest or existing.size_bytes != size
            or existing_metadata.get("resource_id") != str(resource.id)
            or existing_metadata.get("request_fingerprint") != request_fingerprint
            or existing_metadata.get("provider_id") != provider_id
            or existing_metadata.get("provider_version") != provider_version
            or existing_metadata.get("retention_approval_id") != str(approval.id)
        ):
            raise ValueError("Write-once provider response identity already exists with different bytes or provenance.")
        existing_store = artifact_store_for_uri(
            db, organization_id=case.organization_id, storage_uri=existing.storage_uri
        )
        if callable(getattr(existing_store, "download_to_file", None)):
            with tempfile.NamedTemporaryFile(prefix="siraloom-provider-retry-", delete=False) as handle:
                retry_path = Path(handle.name)
            try:
                existing_store.download_to_file(
                    existing.storage_uri, retry_path,
                    expected_sha256=digest, expected_size_bytes=size,
                )
                verify_artifact_file(retry_path, sha256=digest, size_bytes=size)
            finally:
                retry_path.unlink(missing_ok=True)
        else:
            verify_artifact_file(
                existing_store.local_path(existing.storage_uri),
                sha256=digest, size_bytes=size,
            )
        return ProviderResponseRetention(
            "RETAINED", "Idempotent retry matched the existing immutable provider response.",
            existing.id, digest, size, str(discovery.license_status).upper(),
        )
    with tempfile.NamedTemporaryFile(prefix="siraloom-provider-response-", suffix=".bin", delete=False) as handle:
        staged = Path(handle.name)
        handle.write(raw_response_bytes)
        handle.flush()
    try:
        artifact = store.put_file(
            db=db,
            case_id=case.id,
            analysis_id=analysis.id,
            source_path=staged,
            filename=f"provider-response-{digest[:16]}.bin",
            artifact_type="PROVIDER_RESPONSE_RAW",
            media_type=media_type or "application/octet-stream",
            genome_build=analysis.reference_build,
            validation_status="VALIDATED",
            artifact_id=artifact_id,
            metadata={
                "retention_status": "RETAINED",
                "retention_policy": "ORG_RELEASE_APPROVAL_V2",
                "license_status": str(discovery.license_status).upper(),
                "license_url": discovery.license_url,
                "terms_url": discovery.terms_url,
                "retention_approval_id": str(approval.id),
                "retention_approval_version": approval.version,
                "retention_approval_reviewer_id": str(approval.reviewer_id),
                "retention_approval_terms_evidence_artifact_id": str(approval.terms_evidence_artifact_id),
                "retention_approval_terms_evidence_sha256": approval.terms_evidence_sha256,
                "resource_id": str(resource.id),
                "resource_version": resource.version,
                "provider_id": provider_id,
                "provider_version": provider_version,
                "request_fingerprint": request_fingerprint,
                "raw_response_sha256": digest,
                "raw_response_size_bytes": size,
            },
        )
        if artifact.sha256 != digest or artifact.size_bytes != size:
            raise RuntimeError("Stored provider response artifact differs from the exact received bytes.")
        return ProviderResponseRetention(
            "RETAINED", reason, artifact.id, digest, size,
            str(discovery.license_status).upper(),
        )
    finally:
        staged.unlink(missing_ok=True)


def verify_provider_response_reference(
    db: Session,
    *,
    analysis_id: UUID,
    case_id: UUID,
    resource_id: UUID | None,
    request_fingerprint: str | None,
    artifact_id: UUID | None,
    artifact_sha256: str | None,
    artifact_size_bytes: int | None,
    retention_status: str,
    require_retained: bool = False,
) -> bool:
    """Verify a provider response reference without trusting database metadata alone."""
    status = str(retention_status or "NOT_AVAILABLE").upper()
    if status != "RETAINED":
        if require_retained:
            raise ValueError(f"Provider response bytes are not retained (status={status}).")
        if artifact_id is not None or artifact_sha256 is not None or artifact_size_bytes is not None:
            raise ValueError("Non-retained provider response contains an artifact reference or digest.")
        if status not in {"NOT_PERMITTED", "REVIEW_REQUIRED", "NOT_AVAILABLE"}:
            raise ValueError(f"Unsupported provider response retention status: {status}.")
        return False
    if artifact_id is None:
        raise ValueError("Retained provider response is missing its artifact ID.")
    digest = str(artifact_sha256 or "").lower()
    size = artifact_size_bytes
    validate_integrity_expectations(digest, size)
    analysis = db.get(Analysis, analysis_id)
    case = db.get(Case, case_id)
    artifact = db.get(Artifact, artifact_id)
    if analysis is None or analysis.case_id != case_id or case is None or artifact is None:
        raise ValueError("Provider response analysis/case/artifact lineage is unavailable.")
    if (
        artifact.case_id != case_id
        or artifact.analysis_id != analysis_id
        or artifact.artifact_type != "PROVIDER_RESPONSE_RAW"
        or artifact.sha256 != digest
        or artifact.size_bytes != size
    ):
        raise ValueError("Provider response artifact identity, case, analysis, digest or size was substituted.")
    metadata = dict(artifact.metadata_json or {})
    if (
        metadata.get("resource_id") != str(resource_id)
        or metadata.get("request_fingerprint") != request_fingerprint
        or metadata.get("raw_response_sha256") != digest
        or metadata.get("raw_response_size_bytes") != size
    ):
        raise ValueError("Provider response artifact provenance does not match its source record.")
    approval_id = metadata.get("retention_approval_id")
    if not approval_id:
        raise ValueError("Provider response artifact is missing its governed retention approval reference.")
    try:
        approval = db.scalar(select(ProviderRetentionApproval).where(
            ProviderRetentionApproval.id == UUID(str(approval_id)),
        ).with_for_update().execution_options(populate_existing=True))
    except (TypeError, ValueError):
        approval = None
    if (
        approval is None or approval.organization_id != case.organization_id
        or approval.resource_id != resource_id
        or approval.status != "APPROVED"
        or "RAW_PROVIDER_RESPONSE_RETENTION" not in set(approval.permission_scope or [])
    ):
        raise ValueError("Provider response retention approval is missing, revoked, or out of scope.")
    now = datetime.now(UTC)
    if approval.expires_at is not None:
        expires = approval.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        if expires <= now:
            _expire_approval_if_due(db, approval)
            raise ValueError("Provider response retention approval has expired.")
    _authorized_reviewer(db, organization_id=case.organization_id, reviewer_id=approval.reviewer_id)
    if (
        metadata.get("retention_approval_version") != approval.version
        or metadata.get("retention_approval_terms_evidence_artifact_id") != str(approval.terms_evidence_artifact_id)
        or metadata.get("retention_approval_terms_evidence_sha256") != approval.terms_evidence_sha256
    ):
        raise ValueError("Provider response artifact approval snapshot was substituted.")
    terms_artifact = db.get(Artifact, approval.terms_evidence_artifact_id)
    if terms_artifact is None or terms_artifact.sha256 != approval.terms_evidence_sha256:
        raise ValueError("Provider retention terms evidence is missing or has changed.")
    terms_case = db.get(Case, terms_artifact.case_id)
    if terms_case is None or terms_case.organization_id != case.organization_id:
        raise ValueError("Provider retention terms evidence belongs to another organization.")
    terms_store = artifact_store_for_uri(
        db, organization_id=case.organization_id, storage_uri=terms_artifact.storage_uri
    )
    if callable(getattr(terms_store, "download_to_file", None)):
        with tempfile.NamedTemporaryFile(prefix="siraloom-terms-verify-", delete=False) as handle:
            terms_staged = Path(handle.name)
        try:
            terms_store.download_to_file(
                terms_artifact.storage_uri, terms_staged,
                expected_sha256=terms_artifact.sha256,
                expected_size_bytes=terms_artifact.size_bytes,
            )
            verify_artifact_file(
                terms_staged, sha256=terms_artifact.sha256,
                size_bytes=terms_artifact.size_bytes,
            )
        finally:
            terms_staged.unlink(missing_ok=True)
    else:
        verify_artifact_file(
            terms_store.local_path(terms_artifact.storage_uri),
            sha256=terms_artifact.sha256, size_bytes=terms_artifact.size_bytes,
        )
    store = artifact_store_for_uri(
        db, organization_id=case.organization_id, storage_uri=artifact.storage_uri
    )
    if callable(getattr(store, "download_to_file", None)):
        with tempfile.NamedTemporaryFile(prefix="siraloom-evidence-verify-", delete=False) as handle:
            staged = Path(handle.name)
        try:
            store.download_to_file(
                artifact.storage_uri, staged,
                expected_sha256=digest, expected_size_bytes=size,
            )
            verify_artifact_file(staged, sha256=digest, size_bytes=size)
        finally:
            staged.unlink(missing_ok=True)
    else:
        verify_artifact_file(
            store.local_path(artifact.storage_uri), sha256=digest, size_bytes=size
        )
    return True


def verify_evidence_response_artifact(
    db: Session,
    evidence: Evidence,
    *,
    require_retained: bool = True,
) -> bool:
    analysis = db.get(Analysis, evidence.analysis_id)
    if analysis is None:
        raise ValueError("Evidence analysis lineage is unavailable.")
    from backend.app.domain.resource_release_integrity import (
        verify_evidence_source_release_reference,
    )
    verify_evidence_source_release_reference(db, evidence)
    return verify_provider_response_reference(
        db,
        analysis_id=evidence.analysis_id,
        case_id=analysis.case_id,
        resource_id=evidence.resource_id,
        request_fingerprint=evidence.request_fingerprint,
        artifact_id=evidence.response_artifact_id,
        artifact_sha256=evidence.response_artifact_sha256,
        artifact_size_bytes=evidence.response_artifact_size_bytes,
        retention_status=evidence.response_retention_status,
        require_retained=require_retained,
    )
