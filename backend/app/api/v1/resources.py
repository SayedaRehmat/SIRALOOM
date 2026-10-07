from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.resources import (
    ResourceRegistryError, decide_resource_approval, register_resource_version,
    request_resource_approval,
)
from backend.app.infrastructure.db.models import Resource, ResourceApproval, ResourceQualification
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
            organization_id=principal.organization_id if principal.role != "platform_admin" else (
                UUID(str(payload["organization_id"])) if payload.get("organization_id") else None
            ),
            initial_status=requested_status,
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
        "organization_id": str(resource.organization_id) if resource.organization_id else None,
        "checksum": resource.checksum,
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
    row = db.get(Resource, resource_id)
    if not row or (row.organization_id and row.organization_id != principal.organization_id):
        raise HTTPException(status_code=404, detail="Resource not found")
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
    row = db.get(Resource, resource_id)
    if not row or (row.organization_id and row.organization_id != principal.organization_id):
        raise HTTPException(status_code=404, detail="Resource not found")
    try:
        from backend.app.domain.resources import activate_resource_version
        row = activate_resource_version(
            db,
            resource_id=resource_id,
            qualification_version=str(payload.get("qualification_version") or ""),
        )
    except ResourceRegistryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "resource_id": str(row.id),
        "organization_id": str(row.organization_id) if row.organization_id else None,
        "status": row.status,
        "version": row.version,
    }
