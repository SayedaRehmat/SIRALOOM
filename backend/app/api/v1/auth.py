from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.auth.principal import Principal, _verify_firebase_token, get_current_principal
from backend.app.infrastructure.db.models import Organization, OrganizationMembership, User
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

@router.get("/session")
def session(principal: Principal = Depends(get_current_principal)):
    """Returns identity resolved by FastAPI, not a client-supplied role."""
    return {
        "user_id": str(principal.user_id), "organization_id": str(principal.organization_id),
        "role": principal.role, "subject": principal.subject, "email": principal.email,
    }

class OrganizationOnboarding(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)

@router.post("/onboarding/organization", status_code=201)
def create_first_organization(payload: OrganizationOnboarding, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A verified Firebase identity can create only its own first organization.

    The privileged initial role is assigned here on the server, not accepted from the client.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer authentication is required")
    claims = _verify_firebase_token(authorization.removeprefix("Bearer ").strip())
    subject = str(claims.get("uid") or claims.get("sub") or "")
    if not subject or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Firebase email is required before organization onboarding")
    user = db.scalar(select(User).where(User.external_subject == subject))
    if user:
        membership = db.scalar(select(OrganizationMembership).where(OrganizationMembership.user_id == user.id, OrganizationMembership.status == "ACTIVE"))
        if membership: raise HTTPException(status_code=409, detail="This identity already has an active organization membership")
    org = Organization(id=uuid4(), name=payload.organization_name.strip(), external_identifier=None)
    if not user:
        user = User(id=uuid4(), organization_id=org.id, external_subject=subject, email=claims.get("email"), display_name=str(claims.get("name") or claims.get("email") or "SIRALOOM user"), role="organization_admin", status="ACTIVE")
        db.add(user)
    else:
        user.organization_id = org.id; user.role = "organization_admin"; user.status = "ACTIVE"
    db.add(org)
    membership = OrganizationMembership(id=uuid4(), organization_id=org.id, user_id=user.id, role="organization_admin", status="ACTIVE")
    db.add(membership); db.commit()
    return {"organization_id": str(org.id), "membership_id": str(membership.id), "role": membership.role}
