from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.resources import ResourceRegistryError, register_resource_version
from backend.app.infrastructure.db.models import Resource
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/resources", tags=["resources"])


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
        "metadata": row.metadata_json,
        "created_at": row.created_at,
    } for row in rows]


@router.post("")
def register_resource(
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, frozenset({"platform_admin"}))
    try:
        resource, created = register_resource_version(
            db,
            name=str(payload.get("name") or ""),
            provider=str(payload.get("provider") or ""),
            resource_type=str(payload.get("resource_type") or ""),
            version=str(payload.get("version") or ""),
            genome_build=str(payload["genome_build"]) if payload.get("genome_build") else None,
            access_method=str(payload.get("access_method") or ""),
            license_text=payload.get("license_text"),
            checksum=payload.get("checksum"),
            location=payload.get("location"),
            population_definition=payload.get("population_definition"),
            metadata_json=payload.get("metadata"),
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()

    # Resource registration is durable first. The scan is advisory and must
    # never make a successful registry write look failed if the queue is
    # temporarily unavailable; the daily Beat schedule remains the recovery
    # path.
    scan_queued = False
    if created:
        try:
            from backend.app.infrastructure.queue.celery_app import scan_reanalysis_resources
            scan_reanalysis_resources.delay()
            scan_queued = True
        except Exception:
            scan_queued = False

    return {
        "resource_id": str(resource.id),
        "created": created,
        "status": resource.status,
        "name": resource.name,
        "provider": resource.provider,
        "resource_type": resource.resource_type,
        "version": resource.version,
        "genome_build": resource.genome_build,
        "checksum": resource.checksum,
        "reanalysis_scan_queued": scan_queued,
    }


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
    if not row:
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
        "metadata": row.metadata_json,
        "created_at": row.created_at,
    }
