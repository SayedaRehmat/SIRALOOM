from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth.principal import Principal, get_current_principal
from backend.app.infrastructure.db.models import OrganizationMembership, User
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/memberships")
def list_organization_memberships(
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Lists only memberships belonging to the authenticated tenant."""
    rows = db.execute(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(OrganizationMembership.organization_id == principal.organization_id)
        .order_by(OrganizationMembership.created_at.asc(), OrganizationMembership.id.asc())
    ).all()
    return {
        "organization_id": str(principal.organization_id),
        "members": [
            {
                "membership_id": str(membership.id),
                "user_id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
                "role": membership.role,
                "status": membership.status,
            }
            for membership, user in rows
        ],
    }
