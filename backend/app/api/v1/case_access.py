from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.authorization import CASE_ACCESS_ADMIN_ROLES, require_case_permission, require_role
from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.audit.service import AuditService
from backend.app.infrastructure.db.models import Case, CaseAccessGrant, OrganizationMembership, User
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/cases", tags=["case-access"])


class CaseAccessGrantInput(BaseModel):
    can_read: bool = True
    can_write: bool = False
    can_review: bool = False

    @model_validator(mode="after")
    def require_read_for_other_capabilities(self):
        if (self.can_write or self.can_review) and not self.can_read:
            raise ValueError("write and review grants require read access")
        if not (self.can_read or self.can_write or self.can_review):
            raise ValueError("at least one case capability must be granted")
        return self


def _authorized_case(case_id: UUID, db: Session, principal: Principal) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    require_case_permission(case, principal, db, "read")
    actor_membership = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == case.organization_id,
            OrganizationMembership.user_id == principal.user_id,
            OrganizationMembership.status == "ACTIVE",
        )
        .with_for_update()
    )
    if actor_membership is None:
        raise HTTPException(status_code=404, detail="Case not found")
    require_role(
        Principal(
            user_id=principal.user_id,
            organization_id=principal.organization_id,
            role=actor_membership.role,
            subject=principal.subject,
            email=principal.email,
        ),
        CASE_ACCESS_ADMIN_ROLES,
    )
    return case


@router.get("/{case_id}/access")
def list_case_access(
    case_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = _authorized_case(case_id, db, principal)
    grants = db.scalars(
        select(CaseAccessGrant)
        .where(CaseAccessGrant.case_id == case.id)
        .order_by(CaseAccessGrant.created_at, CaseAccessGrant.user_id)
    ).all()
    result = []
    for grant in grants:
        user = db.get(User, grant.user_id)
        membership = db.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == case.organization_id,
                OrganizationMembership.user_id == grant.user_id,
            )
        )
        if user is None or membership is None:
            raise HTTPException(status_code=409, detail="Case access grant has no organization member")
        result.append({
            "user_id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "membership_status": membership.status,
            "role": membership.role,
            "can_read": grant.can_read,
            "can_write": grant.can_write,
            "can_review": grant.can_review,
            "granted_by": str(grant.granted_by) if grant.granted_by else None,
            "created_at": grant.created_at.isoformat(),
            "updated_at": grant.updated_at.isoformat(),
        })
    return {"case_id": str(case.id), "items": result}


@router.put("/{case_id}/access/{user_id}")
def set_case_access(
    case_id: UUID,
    user_id: UUID,
    payload: CaseAccessGrantInput,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = _authorized_case(case_id, db, principal)
    membership = db.scalar(
        select(OrganizationMembership)
        .where(
            OrganizationMembership.organization_id == case.organization_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == "ACTIVE",
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Active organization member not found")
    grant = db.scalar(
        select(CaseAccessGrant)
        .where(CaseAccessGrant.case_id == case.id, CaseAccessGrant.user_id == user_id)
        .with_for_update()
    )
    before = None if grant is None else {
        "can_read": grant.can_read,
        "can_write": grant.can_write,
        "can_review": grant.can_review,
    }
    if grant is None:
        grant = CaseAccessGrant(
            id=uuid4(), case_id=case.id, user_id=user_id,
            granted_by=principal.user_id,
            can_read=payload.can_read,
            can_write=payload.can_write,
            can_review=payload.can_review,
        )
        db.add(grant)
        operation = "GRANT"
    else:
        grant.can_read = payload.can_read
        grant.can_write = payload.can_write
        grant.can_review = payload.can_review
        grant.granted_by = principal.user_id
        db.add(grant)
        operation = "UPDATE_GRANT"
    db.flush()
    AuditService(db).record(
        event_type="CASE_ACCESS_GRANT_CHANGED",
        case_id=case.id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CASE_ACCESS_GRANT",
        subject_id=f"{case.id}:{user_id}",
        operation=operation,
        before_state=before,
        after_state={
            "user_id": str(user_id),
            "can_read": grant.can_read,
            "can_write": grant.can_write,
            "can_review": grant.can_review,
        },
    )
    db.commit()
    return {
        "case_id": str(case.id),
        "user_id": str(user_id),
        "can_read": grant.can_read,
        "can_write": grant.can_write,
        "can_review": grant.can_review,
    }


@router.delete("/{case_id}/access/{user_id}", status_code=204)
def revoke_case_access(
    case_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
):
    case = _authorized_case(case_id, db, principal)
    grant = db.scalar(
        select(CaseAccessGrant)
        .where(CaseAccessGrant.case_id == case.id, CaseAccessGrant.user_id == user_id)
        .with_for_update()
    )
    if grant is None:
        raise HTTPException(status_code=404, detail="Case access grant not found")
    before = {
        "user_id": str(user_id),
        "can_read": grant.can_read,
        "can_write": grant.can_write,
        "can_review": grant.can_review,
    }
    db.delete(grant)
    AuditService(db).record(
        event_type="CASE_ACCESS_GRANT_REVOKED",
        case_id=case.id,
        analysis_id=None,
        actor_type="HUMAN",
        actor_id=str(principal.user_id),
        subject_type="CASE_ACCESS_GRANT",
        subject_id=f"{case.id}:{user_id}",
        operation="REVOKE",
        before_state=before,
        after_state=None,
    )
    db.commit()
