from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from celery.exceptions import CeleryError
from fastapi import APIRouter, Depends, HTTPException
from kombu.exceptions import KombuError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.auth.authorization import require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.config import settings
from backend.app.domain.local_uri import local_path_from_uri
from backend.app.domain.resource_staging import (
    ResourceStagingError,
    create_staging_candidate,
    prepare_staging,
)
from backend.app.domain.resources import (
    ResourceRegistryError,
    decide_resource_approval,
    register_resource_version,
    request_resource_approval,
)
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import (
    Resource,
    ResourceApproval,
    ResourceQualification,
    ResourceStaging,
)
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/resources", tags=["resources"])
logger = logging.getLogger(__name__)


class ResourceStagingCreateRequest(BaseModel):
    source_uri: str | None = Field(default=None, min_length=1)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    expected_size_bytes: int | None = Field(default=None, gt=0)
    storage_backend: str = Field(default="ORGANIZATION_LOCAL_FILESYSTEM", min_length=1, max_length=64)
    metadata: dict = Field(default_factory=dict)


def _safe_path_segment(value: str) -> str:
    segment = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip()).strip(".-")
    return (segment or "resource")[:100]


def _organization_resource_root(organization_id: UUID) -> Path:
    return (Path(settings.resource_cache_root).expanduser().resolve() / str(organization_id)).resolve()


def _resource_destination_path(organization_id: UUID, provider: str, version: str, artifact_url: str) -> Path:
    filename = Path(urlparse(artifact_url).path).name
    filename = _safe_path_segment(filename or f"{provider}-{version}.resource")
    return _organization_resource_root(organization_id) / _safe_path_segment(provider) / _safe_path_segment(version) / filename


def _validate_org_destination(destination_uri: str, organization_id: UUID) -> Path:
    destination = Path(destination_uri).expanduser().resolve(strict=False)
    root = _organization_resource_root(organization_id)
    try:
        relative = destination.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Resource destination must be inside the organization's resource cache: {root}",
        ) from exc
    if not relative.parts:
        raise HTTPException(status_code=400, detail="Resource destination must name a file below the organization resource cache")
    return destination


def _local_source_path(source_uri: str) -> Path | None:
    return local_path_from_uri(source_uri)


def _allowed_resource_hosts() -> set[str]:
    return {host.strip().lower().rstrip(".") for host in settings.resource_staging_allowed_hosts.replace(";", ",").split(",") if host.strip()}


def _allowed_local_source_roots() -> list[Path]:
    return [Path(root.strip()).expanduser().resolve() for root in settings.resource_staging_local_source_roots.replace(";", ",").split(",") if root.strip()]


def _require_resource_owner(row: Resource | None, principal: Principal) -> Resource:
    if row is None or row.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Organization resource not found")
    return row


def _require_resource_lifecycle_access(row: Resource | None, principal: Principal) -> Resource:
    """Only platform administrators may change shared global resource state."""
    if row is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    if row.organization_id is None:
        if principal.role != "platform_admin":
            raise HTTPException(status_code=404, detail="Resource not found")
    elif row.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Resource not found")
    return row


def _staging_payload(row: ResourceStaging) -> dict:
    metadata = dict(row.metadata_json or {})
    preflight = metadata.get("storage_preflight") or {}
    dispatch = metadata.get("staging_dispatch") or {}
    return {
        "staging_id": str(row.id),
        "resource_id": str(row.resource_id),
        "resource_version": row.resource_version,
        "staging_key": row.staging_key,
        "source_uri": row.source_uri,
        "destination_uri": row.destination_uri,
        "storage_backend": row.storage_backend,
        "status": row.status,
        "expected_sha256": row.expected_sha256,
        "observed_sha256": row.observed_sha256,
        "expected_size_bytes": row.expected_size_bytes,
        "observed_size_bytes": row.observed_size_bytes,
        "attempt": row.attempt,
        "error_code": row.error_code,
        "error_message": row.error_message,
        "storage_preflight": preflight,
        "dispatch": dispatch,
        "metadata": metadata,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "completed_at": row.completed_at,
    }


def _staging_dispatch_is_definitively_dead(
    dispatch: dict,
    *,
    now: datetime,
    task_state_lookup,
    stale_after_seconds: int = 120,
) -> bool:
    """Only replace an old staging dispatch after Celery proves it is dead.

    PENDING/UNKNOWN are ambiguous: the broker may have accepted the task, or
    the result backend may not know about it. Replacing those dispatches could
    start duplicate resource acquisition against the same destination.
    """
    status = str(dispatch.get("status") or "").upper()
    if status not in {"QUEUING", "PUBLISHED"}:
        return False
    timestamp = dispatch.get("published_at") if status == "PUBLISHED" else dispatch.get("queued_at")
    if not timestamp:
        return False
    try:
        recorded_at = datetime.fromisoformat(str(timestamp))
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        age_seconds = (now - recorded_at).total_seconds()
    except (TypeError, ValueError):
        return False
    if age_seconds <= stale_after_seconds:
        return False
    task_id = dispatch.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return False
    try:
        task_state = str(task_state_lookup(task_id)).upper()
    except Exception:
        return False
    return task_state in {"FAILURE", "REVOKED"}


def _celery_task_state(task_id: str) -> str:
    from backend.app.infrastructure.queue.celery_app import celery_app

    return str(celery_app.AsyncResult(task_id).state)


@router.get("")
def list_resources(
    resource_type: str | None = None,
    status: str | None = "ACTIVE",
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director",
        "clinical_geneticist", "reviewer", "bioinformatician",
        "lab_scientist", "read_only",
    }))
    query = select(Resource).order_by(Resource.name, Resource.version)
    if resource_type:
        query = query.where(Resource.resource_type == resource_type.strip().upper())
    if status:
        query = query.where(Resource.status == status.strip().upper())
    if principal.role != "platform_admin":
        query = query.where(
            (Resource.organization_id.is_(None)) |
            (Resource.organization_id == principal.organization_id)
        )
    rows = db.scalars(query.limit(500)).all()
    return [{
        "resource_id": str(row.id),
        "name": row.name,
        "provider": row.provider,
        "resource_type": row.resource_type,
        "version": row.version,
        "genome_build": row.genome_build,
        "access_method": row.access_method,
        "checksum": row.checksum,
        "location": row.location,
        "status": row.status,
        "population_definition": row.population_definition,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
    } for row in rows]


@router.post("")
def register_resource(
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "organization_admin", "lab_director", "bioinformatician"}))
    requested_status = str(payload.get("status") or "CANDIDATE").strip().upper()
    if principal.role != "platform_admin" and requested_status != "CANDIDATE":
        raise HTTPException(status_code=403, detail="Lab-managed resources must enter as CANDIDATE")
    provider = str(payload.get("provider") or "").strip()
    version = str(payload.get("version") or "").strip()
    access_method = str(payload.get("access_method") or "").strip().upper()
    metadata_json = dict(payload.get("metadata") or {})
    organization_id = principal.organization_id if principal.role != "platform_admin" else (
        UUID(str(payload["organization_id"])) if payload.get("organization_id") else None
    )
    location = str(payload.get("location") or "").strip() or None
    source_contract = dict(metadata_json.get("source_contract") or {})
    artifact_url = str(source_contract.get("artifact_url") or "").strip()
    file_release_contract = (
        access_method == "HTTPS"
        and str(source_contract.get("access_mode") or "").upper() == "PUBLIC"
        and str(source_contract.get("checksum_status") or "").upper() == "PUBLISHED_AND_VERIFIED"
        and str(source_contract.get("license_status") or "").upper() in {"VERIFIED", "NOT_REQUIRED"}
        and urlparse(artifact_url).scheme == "https"
        and bool(urlparse(artifact_url).hostname)
    )
    if file_release_contract and organization_id is not None:
        if location:
            destination = _validate_org_destination(location, organization_id)
            location = str(destination)
        else:
            location = str(_resource_destination_path(organization_id, provider, version, artifact_url))
        execution = dict(metadata_json.get("execution") or {})
        execution["provider_id"] = provider
        execution["provider_version"] = version
        execution["access_method"] = access_method
        execution["location"] = location
        metadata_json["execution"] = execution
    resource_identity = {
        "organization_id": organization_id,
        "name": str(payload.get("name") or "").strip(),
        "provider": provider,
        "resource_type": str(payload.get("resource_type") or "").strip().upper(),
        "genome_build": str(payload["genome_build"]).strip() if payload.get("genome_build") else None,
    }
    superseded_before = list(db.scalars(
        select(Resource).where(
            Resource.organization_id == organization_id,
            Resource.name == resource_identity["name"],
            Resource.provider == provider,
            Resource.resource_type == resource_identity["resource_type"],
            Resource.genome_build == resource_identity["genome_build"],
            Resource.status == "ACTIVE",
        )
    ).all())
    superseded_before_state = [
        {"resource_id": str(item.id), "version": item.version, "status": item.status}
        for item in superseded_before
    ]
    try:
        resource, created = register_resource_version(
            db,
            name=str(payload.get("name") or ""),
            provider=provider,
            resource_type=str(payload.get("resource_type") or ""),
            version=version,
            genome_build=str(payload["genome_build"]) if payload.get("genome_build") else None,
            access_method=access_method,
            license_text=payload.get("license_text"),
            checksum=payload.get("checksum"),
            location=location,
            population_definition=payload.get("population_definition"),
            metadata_json=metadata_json,
            organization_id=organization_id,
            initial_status=requested_status,
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if created:
        superseded_after_state = [
            {"resource_id": str(item.id), "version": item.version, "status": item.status}
            for item in superseded_before
        ]
        AuditService(db).record(
            event_type="RESOURCE_VERSION_REGISTERED",
            case_id=None,
            analysis_id=None,
            actor_type="HUMAN",
            actor_id=str(principal.user_id),
            subject_type="RESOURCE",
            subject_id=str(resource.id),
            operation="CREATE",
            before_state={"active_resources": superseded_before_state},
            after_state={
                "resource_id": str(resource.id),
                "name": resource.name,
                "provider": resource.provider,
                "resource_type": resource.resource_type,
                "version": resource.version,
                "genome_build": resource.genome_build,
                "checksum": resource.checksum,
                "status": resource.status,
                "superseded_resources": superseded_after_state,
            },
            workflow={"domain": "resource_registry", "organization_id": str(organization_id) if organization_id else None},
            payload={"created": True},
        )
    db.commit()

    # Only a platform administrator can register an ACTIVE resource. A
    # laboratory's CANDIDATE resource has no effect on active-release scans;
    # its organization-scoped scan is queued only after authorized activation.
    scan_queued = False
    if created and resource.status == "ACTIVE" and principal.role == "platform_admin":
        scan_queued = _queue_reanalysis_scan(resource.organization_id)

    return {
        "resource_id": str(resource.id),
        "created": created,
        "status": resource.status,
        "name": resource.name,
        "provider": resource.provider,
        "resource_type": resource.resource_type,
        "version": resource.version,
        "genome_build": resource.genome_build,
        "organization_id": str(resource.organization_id) if resource.organization_id else None,
        "checksum": resource.checksum,
        "location": resource.location,
        "reanalysis_scan_queued": scan_queued,
    }


@router.post("/{resource_id}/approval-request")
def create_resource_approval_request(
    resource_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "organization_admin", "lab_director", "bioinformatician"}))
    try:
        approval = request_resource_approval(
            db,
            resource_id=resource_id,
            organization_id=principal.organization_id,
            qualification_version=str(payload.get("qualification_version") or ""),
            actor_id=principal.user_id,
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "approval_id": str(approval.id),
        "resource_id": str(approval.resource_id),
        "organization_id": str(approval.organization_id),
        "qualification_id": str(approval.qualification_id),
        "status": approval.status,
        "version": approval.version,
    }


@router.get("/approvals/pending")
def list_pending_resource_approvals(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "organization_admin", "lab_director", "bioinformatician", "read_only"}))
    rows = db.scalars(
        select(ResourceApproval).where(
            ResourceApproval.organization_id == principal.organization_id,
            ResourceApproval.status == "PENDING",
        ).order_by(ResourceApproval.requested_at)
    ).all()
    return [{
        "approval_id": str(row.id),
        "resource_id": str(row.resource_id),
        "organization_id": str(row.organization_id),
        "qualification_id": str(row.qualification_id),
        "status": row.status,
        "version": row.version,
        "requested_at": row.requested_at,
    } for row in rows]


@router.post("/approvals/{approval_id}/decision")
def decide_resource_approval_endpoint(
    approval_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "organization_admin", "lab_director"}))
    try:
        approval = decide_resource_approval(
            db,
            approval_id=approval_id,
            organization_id=principal.organization_id,
            actor_id=principal.user_id,
            decision=str(payload.get("decision") or ""),
            expected_version=int(payload.get("expected_version") or 0),
            reason=str(payload.get("reason")) if payload.get("reason") is not None else None,
        )
    except (ResourceRegistryError, ValueError) as exc:
        raise HTTPException(status_code=409 if "changed" in str(exc).lower() else 400, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Another resource release decision changed this organization's binding; refresh and retry.",
        ) from exc
    db.commit()
    return {
        "approval_id": str(approval.id),
        "resource_id": str(approval.resource_id),
        "organization_id": str(approval.organization_id),
        "status": approval.status,
        "version": approval.version,
        "decided_by": str(approval.decided_by) if approval.decided_by else None,
        "decided_at": approval.decided_at,
    }


@router.get("/staging/config")
def get_resource_staging_config(
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director", "bioinformatician",
    }))
    return {
        "resource_cache_root": str(Path(settings.resource_cache_root).expanduser().resolve()),
        "organization_resource_root": str(_organization_resource_root(principal.organization_id)),
        "max_remote_bytes": settings.resource_staging_max_bytes,
        "timeout_seconds": settings.resource_staging_timeout_seconds,
        "allowed_publisher_hosts": sorted(_allowed_resource_hosts()),
        "local_source_roots": [str(root) for root in _allowed_local_source_roots()],
        "remote_staging_enabled": bool(_allowed_resource_hosts()),
    }


@router.get("/{resource_id}/staging")
def list_resource_staging(
    resource_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director", "bioinformatician",
        "clinical_geneticist", "reviewer", "lab_scientist", "read_only",
    }))
    resource = _require_resource_owner(db.get(Resource, resource_id), principal)
    rows = db.scalars(
        select(ResourceStaging)
        .where(
            ResourceStaging.resource_id == resource.id,
            ResourceStaging.resource_version == resource.version,
        )
        .order_by(ResourceStaging.created_at.desc())
        .limit(50)
    ).all()
    return [_staging_payload(row) for row in rows]


@router.post("/{resource_id}/staging", status_code=201)
def create_resource_staging(
    resource_id: UUID,
    payload: ResourceStagingCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director", "bioinformatician",
    }))
    resource = _require_resource_owner(db.get(Resource, resource_id), principal)
    if payload.storage_backend != "ORGANIZATION_LOCAL_FILESYSTEM":
        raise HTTPException(status_code=422, detail="Unsupported organization resource staging backend")
    if resource.status not in {"CANDIDATE", "QUALIFIED"}:
        raise HTTPException(status_code=409, detail=f"Resource status {resource.status} cannot be staged")
    if not resource.location:
        raise HTTPException(status_code=400, detail="Resource must have a registered execution destination before staging")
    destination = _validate_org_destination(resource.location, principal.organization_id)
    collision = db.scalar(select(Resource).where(Resource.location == str(destination), Resource.id != resource.id).limit(1))
    if collision is not None:
        raise HTTPException(status_code=409, detail="Another registered resource already uses this destination path")
    source_contract = dict((resource.metadata_json or {}).get("source_contract") or {})
    access_method = str(resource.access_method or "").strip().upper()
    source_uri = str(payload.source_uri or "").strip()
    if not source_uri and access_method == "HTTPS":
        source_uri = str(source_contract.get("artifact_url") or "").strip()
    if not source_uri:
        raise HTTPException(status_code=400, detail="source_uri is required for local resources")

    expected_sha256 = str(payload.expected_sha256 or resource.checksum or "").strip() or None
    if resource.checksum and expected_sha256 and expected_sha256.lower() != resource.checksum.lower():
        raise HTTPException(status_code=409, detail="Staging SHA-256 must match the checksum registered on this immutable resource version")
    expected_size_bytes = payload.expected_size_bytes
    if access_method == "HTTPS":
        parsed = urlparse(source_uri)
        if parsed.scheme != "https" or not parsed.hostname:
            raise HTTPException(status_code=400, detail="Remote resource staging requires an absolute HTTPS source URL")
        if source_uri != str(source_contract.get("artifact_url") or "").strip():
            raise HTTPException(status_code=400, detail="Source URL must match the registered source contract")
        if str(source_contract.get("access_mode") or "").upper() != "PUBLIC":
            raise HTTPException(status_code=400, detail="Generic staging only supports public resources; use a provider-specific adapter for authenticated/licensed sources")
        if str(source_contract.get("checksum_status") or "").upper() != "PUBLISHED_AND_VERIFIED":
            raise HTTPException(status_code=400, detail="Remote staging requires a published and verified checksum declaration")
        if str(source_contract.get("license_status") or "").upper() not in {"VERIFIED", "NOT_REQUIRED"}:
            raise HTTPException(status_code=409, detail="License/terms review must be resolved before resource acquisition")
        allowed_hosts = _allowed_resource_hosts()
        if not allowed_hosts:
            raise HTTPException(status_code=409, detail="Remote staging is disabled until the lab configures RESOURCE_STAGING_ALLOWED_HOSTS")
        if parsed.hostname.lower().rstrip(".") not in allowed_hosts:
            raise HTTPException(status_code=403, detail=f"Publisher host {parsed.hostname!r} is not allowed by this deployment")
        if not expected_sha256:
            raise HTTPException(status_code=400, detail="Remote staging requires an expected SHA-256 checksum")
        if expected_size_bytes is None:
            raise HTTPException(status_code=400, detail="Remote staging requires the expected release size so storage preflight can reserve capacity")
        if expected_size_bytes > settings.resource_staging_max_bytes:
            raise HTTPException(status_code=413, detail=f"Resource exceeds the configured staging limit of {settings.resource_staging_max_bytes} bytes")
    else:
        source_path = _local_source_path(source_uri)
        if source_path is None:
            raise HTTPException(status_code=400, detail="Local staging source must be a filesystem path or file:// URI")
        allowed_roots = _allowed_local_source_roots()
        if not allowed_roots or not any(source_path == root or root in source_path.parents for root in allowed_roots):
            raise HTTPException(status_code=403, detail="Local source is outside RESOURCE_STAGING_LOCAL_SOURCE_ROOTS")
        if not source_path.is_file():
            raise HTTPException(status_code=400, detail="Local staging source file does not exist")
        if source_path.stat().st_size <= 0:
            raise HTTPException(status_code=400, detail="Local staging source file is empty")
        if expected_size_bytes is None:
            expected_size_bytes = source_path.stat().st_size
        if expected_size_bytes > settings.resource_staging_max_bytes:
            raise HTTPException(status_code=413, detail=f"Resource exceeds the configured staging limit of {settings.resource_staging_max_bytes} bytes")

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        row = create_staging_candidate(
            db,
            resource=resource,
            source_uri=source_uri,
            destination_uri=str(destination),
            storage_backend=payload.storage_backend,
            expected_sha256=expected_sha256,
            expected_size_bytes=expected_size_bytes,
            metadata={
                **payload.metadata,
                "source_contract_release": source_contract.get("release_identity"),
                "created_by": str(principal.user_id),
            },
        )
        if row.status in {"DISCOVERED", "PREFLIGHT_FAILED"} or (
            row.status == "INTEGRITY_FAILED" and bool((row.metadata_json or {}).get("retryable"))
        ):
            prepare_staging(db, row)
        db.commit()
        db.refresh(row)
    except (ResourceStagingError, ValueError, OSError) as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _staging_payload(row)


@router.post("/{resource_id}/staging/{staging_id}/execute")
def execute_resource_staging(
    resource_id: UUID,
    staging_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director", "bioinformatician",
    }))
    resource = _require_resource_owner(db.get(Resource, resource_id), principal)
    row = db.get(ResourceStaging, staging_id)
    if row is None or row.resource_id != resource.id or row.resource_version != resource.version:
        raise HTTPException(status_code=404, detail="Staging record not found for this resource version")
    if row.status == "STAGED":
        return _staging_payload(row)
    if row.status == "STAGING":
        return _staging_payload(row)
    if row.status == "INTEGRITY_FAILED" and not bool((row.metadata_json or {}).get("retryable")):
        raise HTTPException(status_code=409, detail="This staging failure is not retryable; correct the release/checksum and register a new resource version")
    if row.status in {"DISCOVERED", "PREFLIGHT_FAILED", "INTEGRITY_FAILED"}:
        try:
            prepare_staging(db, row)
            db.commit()
            db.refresh(row)
        except (ResourceStagingError, ValueError, OSError) as exc:
            db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row.status != "READY_TO_STAGE":
        raise HTTPException(status_code=409, detail=f"Staging is not ready to execute: {row.status}")

    metadata = dict(row.metadata_json or {})
    dispatch = dict(metadata.get("staging_dispatch") or {})
    dispatch_status = str(dispatch.get("status") or "").upper()
    dispatch_dead = _staging_dispatch_is_definitively_dead(
        dispatch,
        now=datetime.now(timezone.utc),
        task_state_lookup=_celery_task_state,
    ) if dispatch_status in {"QUEUING", "PUBLISHED"} else False
    if dispatch_status in {"QUEUING", "PUBLISHED", "RUNNING"} and not dispatch_dead:
        return _staging_payload(row)

    dispatch_task_id = f"siraloom-resource-stage-{row.id}-{uuid4()}"
    metadata["staging_dispatch"] = {
        "status": "QUEUING",
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "task_id": dispatch_task_id,
    }
    row.metadata_json = metadata
    db.add(row)
    db.commit()
    try:
        from backend.app.infrastructure.queue.celery_app import run_resource_staging_task
        run_resource_staging_task.apply_async(
            args=[str(row.id)],
            task_id=dispatch_task_id,
        )
    except Exception as exc:
        current = db.get(ResourceStaging, row.id)
        if current is not None:
            current_metadata = dict(current.metadata_json or {})
            current_metadata["staging_dispatch"] = {
                "status": "FAILED",
                "error": str(exc),
                "failed_at": datetime.now(timezone.utc).isoformat(),
            }
            current.metadata_json = current_metadata
            db.add(current)
            db.commit()
        raise HTTPException(status_code=503, detail="Resource staging could not be queued. The staging record is preserved; retry the queue action after the worker/broker is healthy.") from exc

    current = db.get(ResourceStaging, row.id)
    if current is not None:
        current_metadata = dict(current.metadata_json or {})
        current_dispatch = dict(current_metadata.get("staging_dispatch") or {})
        if str(current_dispatch.get("status") or "").upper() == "QUEUING":
            current_metadata["staging_dispatch"] = {
                **current_dispatch,
                "status": "PUBLISHED",
                "published_at": datetime.now(timezone.utc).isoformat(),
            }
            current.metadata_json = current_metadata
            db.add(current)
            db.commit()
        row = current
    db.refresh(row)
    return _staging_payload(row)


@router.get("/{resource_id}")
def get_resource(
    resource_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({
        "platform_admin", "organization_admin", "lab_director",
        "clinical_geneticist", "reviewer", "bioinformatician",
        "lab_scientist", "read_only",
    }))
    row = db.get(Resource, resource_id)
    if not row or (
        principal.role != "platform_admin"
        and row.organization_id is not None
        and row.organization_id != principal.organization_id
    ):
        raise HTTPException(status_code=404, detail="Resource not found")
    return {
        "resource_id": str(row.id),
        "name": row.name,
        "provider": row.provider,
        "resource_type": row.resource_type,
        "version": row.version,
        "genome_build": row.genome_build,
        "access_method": row.access_method,
        "checksum": row.checksum,
        "location": row.location,
        "status": row.status,
        "population_definition": row.population_definition,
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "metadata": row.metadata_json,
        "created_at": row.created_at,
    }



@router.post("/{resource_id}/qualify")
def qualify_resource(
    resource_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "lab_director", "bioinformatician"}))
    row = _require_resource_lifecycle_access(db.get(Resource, resource_id), principal)
    before_status = row.status
    try:
        from backend.app.domain.resource_qualification import qualify_resource as run_qualification
        from backend.app.domain.resources import qualify_resource_version

        qualification_version = str(
            payload.get("qualification_version") or "siraloom-resource-qualification-v1"
        )
        staging = db.scalar(
            select(ResourceStaging)
            .where(
                ResourceStaging.resource_id == row.id,
                ResourceStaging.resource_version == row.version,
            )
            .order_by(ResourceStaging.updated_at.desc(), ResourceStaging.created_at.desc())
            .limit(1)
        )
        result = run_qualification(
            row,
            staging=staging,
            qualification_version=qualification_version,
        )
        qualification = qualify_resource_version(
            db,
            resource_id=resource_id,
            qualification_version=result.qualification_version,
            checks=result.checks,
            qualified_by=principal.user_id,
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService(db).record(
        event_type="RESOURCE_QUALIFICATION_RECORDED",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="RESOURCE",
        subject_id=str(row.id),
        operation="QUALIFY",
        before_state={"status": before_status},
        after_state={
            "status": row.status,
            "qualification_id": str(qualification.id),
            "qualification_version": qualification.qualification_version,
            "qualification_status": qualification.status,
            "passed": result.passed,
            "outcome": result.checks.get("qualification_outcome"),
        },
        workflow={"domain": "resource_registry", "organization_id": str(row.organization_id) if row.organization_id else None},
    )
    db.commit()
    return {
        "resource_id": str(resource_id),
        "status": row.status,
        "qualification_id": str(qualification.id),
        "qualification_version": qualification.qualification_version,
        "passed": result.passed,
        "outcome": result.checks.get("qualification_outcome"),
        "activation_blockers": result.blockers,
        "checks": result.checks,
    }


@router.post("/{resource_id}/activate")
def activate_resource(
    resource_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin", "lab_director"}))
    row = _require_resource_lifecycle_access(db.get(Resource, resource_id), principal)
    before_state = {"resource_id": str(row.id), "version": row.version, "status": row.status}
    active_siblings = list(db.scalars(
        select(Resource).where(
            Resource.organization_id == row.organization_id,
            Resource.name == row.name,
            Resource.provider == row.provider,
            Resource.resource_type == row.resource_type,
            Resource.genome_build == row.genome_build,
            Resource.status == "ACTIVE",
        )
    ).all())
    sibling_states = [
        {"resource_id": str(item.id), "version": item.version, "status": item.status}
        for item in active_siblings
    ]
    try:
        from backend.app.domain.resources import activate_resource_version
        row = activate_resource_version(
            db,
            resource_id=resource_id,
            qualification_version=str(payload.get("qualification_version") or ""),
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService(db).record(
        event_type="RESOURCE_VERSION_ACTIVATED",
        case_id=None,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="RESOURCE",
        subject_id=str(row.id),
        operation="ACTIVATE",
        before_state={"resource": before_state, "active_resources": sibling_states},
        after_state={
            "resource": {"resource_id": str(row.id), "version": row.version, "status": row.status},
            "superseded_resources": [
                {"resource_id": str(item.id), "version": item.version, "status": item.status}
                for item in active_siblings
            ],
        },
        workflow={"domain": "resource_registry", "organization_id": str(row.organization_id) if row.organization_id else None},
        payload={"qualification_version": str(payload.get("qualification_version") or "")},
    )
    db.commit()
    scan_queued = _queue_reanalysis_scan(row.organization_id)
    return {
        "resource_id": str(row.id),
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "status": row.status,
        "version": row.version,
        "reanalysis_scan_queued": scan_queued,
    }


def _queue_reanalysis_scan(organization_id: UUID | None) -> bool:
    """Queue a scoped scan; daily global scanning recovers broker outages."""
    try:
        from backend.app.infrastructure.queue.celery_app import scan_reanalysis_resources

        if organization_id is None:
            scan_reanalysis_resources.delay()
        else:
            scan_reanalysis_resources.delay(str(organization_id))
    except (CeleryError, KombuError, ImportError) as exc:
        # The resource change is already committed. Keep its API result honest
        # without logging broker URLs or other exception text that may contain
        # credentials; the daily system scan is the recovery path.
        logger.warning(
            "Reanalysis scan dispatch failed; daily scan will recover "
            "(error_type=%s)",
            type(exc).__name__,
        )
        return False
    return True
