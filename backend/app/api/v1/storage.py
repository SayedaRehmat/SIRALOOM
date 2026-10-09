from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.domain.storage_profiles import (
    StorageProfileError,
    activate_storage_profile,
    get_active_storage_profile,
    register_storage_profile,
)
from backend.app.infrastructure.db.models import OrganizationStorageProfile
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/storage", tags=["storage"])

ADMIN_ROLES = frozenset({"platform_admin", "organization_admin", "lab_director"})
READ_ROLES = ADMIN_ROLES | frozenset({"bioinformatician", "lab_scientist", "read_only"})


def _payload(row: OrganizationStorageProfile) -> dict:
    return {
        "storage_profile_id": str(row.id),
        "organization_id": str(row.organization_id),
        "name": row.name,
        "version": row.version,
        "backend_type": row.backend_type,
        "storage_key": row.storage_key,
        "status": row.status,
        "created_by": str(row.created_by) if row.created_by else None,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/profiles")
def list_storage_profiles(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, READ_ROLES)
    rows = db.scalars(
        select(OrganizationStorageProfile)
        .where(OrganizationStorageProfile.organization_id == principal.organization_id)
        .order_by(
            OrganizationStorageProfile.name,
            OrganizationStorageProfile.version.desc(),
        )
    ).all()
    return [_payload(row) for row in rows]


@router.get("/active")
def active_storage_profile(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, READ_ROLES)
    row = get_active_storage_profile(
        db, organization_id=principal.organization_id
    )
    return _payload(row) if row else None


@router.post("/profiles", status_code=201)
def create_storage_profile(
    payload: dict,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, ADMIN_ROLES)
    try:
        row = register_storage_profile(
            db,
            organization_id=principal.organization_id,
            name=str(payload.get("name") or ""),
            backend_type=str(payload.get("backend_type") or ""),
            storage_key=str(payload.get("storage_key") or ""),
            configuration=payload.get("configuration"),
            created_by=principal.user_id,
        )
    except StorageProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _payload(row)


@router.post("/profiles/{profile_id}/activate")
def activate_storage_profile_endpoint(
    profile_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    require_role(principal, ADMIN_ROLES)
    try:
        row = activate_storage_profile(
            db,
            organization_id=principal.organization_id,
            profile_id=profile_id,
        )
    except StorageProfileError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return _payload(row)
