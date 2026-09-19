from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from backend.app.application.entitlements import create_trial_entitlement, get_entitlement, summarize
from backend.app.auth.principal import Principal, _verify_firebase_token, get_current_principal
from backend.app.infrastructure.db.models import Organization, OrganizationMembership, User
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/session")
def session(principal: Principal = Depends(get_current_principal), db: Session = Depends(get_db)):
    """Returns identity resolved by FastAPI, not a client-supplied role."""
    entitlement = summarize(get_entitlement(db, principal.organization_id))
    return {
        "user_id": str(principal.user_id), "organization_id": str(principal.organization_id),
        "role": principal.role, "subject": principal.subject, "email": principal.email,
        "entitlement": entitlement.as_dict() if entitlement else None,
    }


def _authenticate_bearer(authorization: str | None) -> tuple[str, dict]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer authentication is required")
    claims = _verify_firebase_token(authorization.removeprefix("Bearer ").strip())
    subject = str(claims.get("uid") or claims.get("sub") or "")
    if not subject or not claims.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Firebase email is required before onboarding")
    return subject, claims


def _reject_if_already_provisioned(db: Session, subject: str) -> User | None:
    """Looks up an existing SIRALOOM user for this identity and rejects re-onboarding if
    it already has an active organization membership. Returns the existing user (if any,
    unmembered) so the caller can re-provision it into a new organization."""
    user = db.scalar(select(User).where(User.external_subject == subject))
    if user:
        membership = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id, OrganizationMembership.status == "ACTIVE",
        ))
        if membership:
            raise HTTPException(status_code=409, detail="This identity already has an active organization membership")
    return user


def _provision_organization(db: Session, *, subject: str, claims: dict, organization_name: str) -> tuple[Organization, User, OrganizationMembership]:
    """Creates an Organization, its owning User, and the organization_admin membership
    for a verified Firebase identity. The privileged initial role is assigned here on the
    server, never accepted from the client.

    The organization is an implementation detail of onboarding, not something the person
    has to think about: both normal signup and free-trial signup call this, they just
    choose a different `organization_name` and add different entitlements afterwards.
    """
    user = _reject_if_already_provisioned(db, subject)
    org = Organization(id=uuid4(), name=organization_name.strip(), external_identifier=None)
    db.add(org)
    db.flush()

    if not user:
        user = User(
            id=uuid4(), organization_id=org.id, external_subject=subject, email=claims.get("email"),
            display_name=str(claims.get("name") or claims.get("email") or "SIRALOOM user"),
            role="organization_admin", status="ACTIVE",
        )
        db.add(user)
        db.flush()
    else:
        user.organization_id = org.id
        user.role = "organization_admin"
        user.status = "ACTIVE"

    membership = OrganizationMembership(
        id=uuid4(),
        organization_id=org.id,
        user_id=user.id,
        role="organization_admin",
        status="ACTIVE",
    )
    db.add(membership)
    return org, user, membership


class OrganizationOnboarding(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)


@router.post("/onboarding/organization", status_code=201)
def create_first_organization(payload: OrganizationOnboarding, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A verified Firebase identity can create only its own first (production) organization.

    This path carries no entitlement restrictions: it is the normal, full-access SaaS
    signup, distinct from the free-trial path below.
    """
    subject, claims = _authenticate_bearer(authorization)
    org, user, membership = _provision_organization(db, subject=subject, claims=claims, organization_name=payload.organization_name)
    db.commit()
    return {"organization_id": str(org.id), "membership_id": str(membership.id), "role": membership.role}


class TrialOnboarding(BaseModel):
    """Everything here is optional: a Lab Director should be able to start a trial with
    nothing more than a verified Google/email identity."""
    display_name: str | None = Field(default=None, max_length=200)
    laboratory_name: str | None = Field(default=None, max_length=200)


@router.post("/onboarding/trial", status_code=201)
def start_free_trial(payload: TrialOnboarding, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Creates a time-boxed, usage-capped Trial Workspace for a verified Firebase identity.

    No payment method, no billing account, no administrator provisioning step. Internally
    this still creates a real Organization/User/Membership (organization remains the
    tenant boundary everywhere else in the system) plus a TRIAL entitlement -- the
    organization is just not something the person has to name or manage themselves unless
    they want to.
    """
    subject, claims = _authenticate_bearer(authorization)
    owner_label = (payload.display_name or claims.get("name") or claims.get("email") or "Your").strip()
    org_name = payload.laboratory_name.strip() if payload.laboratory_name else f"{owner_label}'s SIRALOOM Trial"
    org, user, membership = _provision_organization(db, subject=subject, claims=claims, organization_name=org_name)
    entitlement = create_trial_entitlement(db, org.id)
    db.commit()
    return {
        "organization_id": str(org.id),
        "membership_id": str(membership.id),
        "role": membership.role,
        "entitlement": summarize(entitlement).as_dict(),
    }
