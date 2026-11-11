"""Governed retention and verification of exact provider response bytes."""
from __future__ import annotations

import hashlib
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.artifact_integrity import validate_integrity_expectations, verify_artifact_file
from backend.app.domain.storage_profiles import artifact_store_for_organization, artifact_store_for_uri
from backend.app.infrastructure.db.models import Analysis, Artifact, Case, Evidence, Resource, ResourceDiscovery


@dataclass(frozen=True)
class ProviderResponseRetention:
    status: str
    reason: str
    artifact_id: UUID | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    license_status: str = "UNKNOWN"


def _retention_permission(db: Session, resource: Resource) -> tuple[str, str, ResourceDiscovery | None]:
    """Only an exact release with affirmative license/terms review permits raw retention."""
    discovery = db.scalar(
        select(ResourceDiscovery)
        .where(
            ResourceDiscovery.resource_id == resource.id,
            ResourceDiscovery.release_identity == resource.version,
        )
        .order_by(ResourceDiscovery.created_at.desc(), ResourceDiscovery.id.desc())
        .limit(1)
    )
    if discovery is None:
        return "REVIEW_REQUIRED", "No source-discovery license record matches the exact resource release.", None
    status = str(discovery.license_status or "UNKNOWN").strip().upper()
    if status == "RESTRICTED":
        return "NOT_PERMITTED", "The source release is marked RESTRICTED; raw response retention is prohibited.", discovery
    if status not in {"VERIFIED", "NOT_REQUIRED"}:
        return "REVIEW_REQUIRED", f"Raw response retention is not approved for license status {status}.", discovery
    if status == "VERIFIED" and not (discovery.license_url or discovery.terms_url):
        return "REVIEW_REQUIRED", "Verified license status has no retained license or terms URL.", discovery
    return "RETAINED", "Exact resource release has an affirmative retention permission record.", discovery


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
) -> ProviderResponseRetention:
    """Persist exact response bytes only after affirmative release-specific permission."""
    if not isinstance(raw_response_bytes, bytes) or not raw_response_bytes:
        return ProviderResponseRetention(
            "NOT_AVAILABLE", "Provider did not supply non-empty raw response bytes."
        )
    permission, reason, discovery = _retention_permission(db, resource)
    if permission != "RETAINED":
        return ProviderResponseRetention(
            permission, reason, license_status=(
                str(discovery.license_status).upper() if discovery else "UNKNOWN"
            )
        )
    if analysis.case_id is None or analysis.id is None:
        raise ValueError("Provider response retention requires persisted analysis and case identity.")
    case = db.get(Case, analysis.case_id)
    if case is None or case.organization_id is None:
        raise ValueError("Provider response retention requires a case with organization identity.")
    digest = hashlib.sha256(raw_response_bytes).hexdigest()
    size = len(raw_response_bytes)
    store = artifact_store_for_organization(db, organization_id=case.organization_id)
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
            metadata={
                "retention_status": "RETAINED",
                "retention_policy": "RESOURCE_RELEASE_LICENSE_GATE_V1",
                "license_status": str(discovery.license_status).upper(),
                "license_url": discovery.license_url,
                "terms_url": discovery.terms_url,
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


def verify_evidence_response_artifact(
    db: Session,
    evidence: Evidence,
    *,
    require_retained: bool = True,
) -> bool:
    """Verify evidence-to-artifact identity, tenant lineage, digest, size and actual bytes."""
    status = str(evidence.response_retention_status or "NOT_AVAILABLE").upper()
    if status != "RETAINED":
        if require_retained:
            raise ValueError(
                f"Evidence {evidence.id} has no retained provider response bytes (status={status})."
            )
        if evidence.response_artifact_id is not None:
            raise ValueError("Evidence has an artifact reference but is not marked RETAINED.")
        return False
    if evidence.response_artifact_id is None:
        raise ValueError("Retained evidence response is missing its artifact ID.")
    digest = str(evidence.response_artifact_sha256 or "").lower()
    size = evidence.response_artifact_size_bytes
    validate_integrity_expectations(digest, size)
    analysis = db.get(Analysis, evidence.analysis_id)
    if analysis is None or analysis.case_id is None:
        raise ValueError("Evidence analysis/case lineage is unavailable.")
    case = db.get(Case, analysis.case_id)
    artifact = db.get(Artifact, evidence.response_artifact_id)
    if case is None or artifact is None:
        raise ValueError("Evidence response artifact or owning case is missing.")
    if (
        artifact.case_id != case.id
        or artifact.analysis_id != analysis.id
        or artifact.artifact_type != "PROVIDER_RESPONSE_RAW"
        or artifact.sha256 != digest
        or artifact.size_bytes != size
    ):
        raise ValueError("Evidence response artifact identity, case, analysis, digest or size was substituted.")
    metadata = dict(artifact.metadata_json or {})
    if (
        metadata.get("resource_id") != str(evidence.resource_id)
        or metadata.get("request_fingerprint") != evidence.request_fingerprint
        or metadata.get("raw_response_sha256") != digest
        or metadata.get("raw_response_size_bytes") != size
    ):
        raise ValueError("Evidence response artifact provenance does not match the evidence record.")
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
