from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.app.application.entitlements import create_trial_entitlement, get_entitlement, summarize
from backend.app.auth.principal import Principal, _verify_firebase_token, get_current_principal
from backend.app.config import settings
from backend.app.infrastructure.db.models import Organization, OrganizationMembership, User
from backend.app.infrastructure.db.organization_invitations import OrganizationInvitation
from backend.app.infrastructure.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


VALID_INVITATION_ROLES = frozenset({
    "organization_admin", "lab_director", "clinical_geneticist", "reviewer",
    "bioinformatician", "lab_scientist", "read_only",
})

INVITATION_ROLE_ORDER = {
    "read_only": 1,
    "lab_scientist": 2,
    "bioinformatician": 3,
    "reviewer": 4,
    "clinical_geneticist": 5,
    "lab_director": 6,
    "organization_admin": 7,
}


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


def _normalize_email(email: str | None) -> str:
    normalized = (email or "").strip().casefold()
    if not normalized or "@" not in normalized:
        raise HTTPException(status_code=403, detail="A verified Firebase email is required")
    return normalized


def _hash_invitation_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _invitation_roles_for(principal_role: str) -> frozenset[str]:
    if principal_role == "organization_admin":
        return VALID_INVITATION_ROLES
    if principal_role == "lab_director":
        return frozenset({"lab_director", "clinical_geneticist", "reviewer", "bioinformatician", "lab_scientist", "read_only"})
    if principal_role == "clinical_geneticist":
        return frozenset({"clinical_geneticist", "reviewer", "bioinformatician", "lab_scientist", "read_only"})
    if principal_role == "reviewer":
        return frozenset({"reviewer", "read_only"})
    return frozenset()


def _require_invitation_role(principal: Principal, role: str) -> None:
    if role not in VALID_INVITATION_ROLES or role not in _invitation_roles_for(principal.role):
        raise HTTPException(status_code=403, detail="Your organization role is not authorized to assign this role")
    if role == "platform_admin":
        raise HTTPException(status_code=403, detail="Platform administrator access cannot be granted through an organization invitation")


def _ensure_active_admin_invariant(
    db: Session,
    organization_id,
    *,
    current_role: str,
    current_status: str,
    effective_role: str,
    effective_status: str,
) -> None:
    """Rejects a transition that would leave a tenant without an active organization admin."""
    if current_role != "organization_admin" or current_status != "ACTIVE":
        return
    if effective_role == "organization_admin" and effective_status not in {"SUSPENDED", "REVOKED"}:
        return
    admin_count = db.scalar(select(func.count()).select_from(OrganizationMembership).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.role == "organization_admin",
        OrganizationMembership.status == "ACTIVE",
    )) or 0
    if admin_count <= 1:
        raise HTTPException(status_code=409, detail="The organization must retain at least one active organization administrator")


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
    server, never accepted from the client."""
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
        id=uuid4(), organization_id=org.id, user_id=user.id,
        role="organization_admin", status="ACTIVE",
    )
    db.add(membership)
    return org, user, membership


def _first_organization_bootstrap_is_available(db: Session) -> bool:
    """Returns whether this deployment is still in its one-time lab bootstrap state."""
    if not settings.organization_first_bootstrap_enabled:
        return False
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(73120491)"))
    return db.scalar(select(func.count()).select_from(Organization)) == 0


class OrganizationOnboarding(BaseModel):
    organization_name: str = Field(min_length=2, max_length=200)


@router.post("/onboarding/organization", status_code=201)
def create_first_organization(payload: OrganizationOnboarding, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Creates an organization for explicitly enabled SaaS self-signup or first-lab bootstrap."""
    first_bootstrap = _first_organization_bootstrap_is_available(db)
    if not settings.organization_self_signup_enabled and not first_bootstrap:
        raise HTTPException(
            status_code=403,
            detail="Organization self-signup is disabled for this deployment; a laboratory bootstrap is not available",
        )
    subject, claims = _authenticate_bearer(authorization)
    org, user, membership = _provision_organization(
        db, subject=subject, claims=claims, organization_name=payload.organization_name
    )
    db.commit()
    return {"organization_id": str(org.id), "membership_id": str(membership.id), "role": membership.role}


class TrialOnboarding(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    laboratory_name: str | None = Field(default=None, max_length=200)


@router.post("/onboarding/trial", status_code=201)
def start_free_trial(payload: TrialOnboarding, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Creates a time-boxed, usage-capped Trial Workspace for a verified Firebase identity."""
    subject, claims = _authenticate_bearer(authorization)
    owner_label = (payload.display_name or claims.get("name") or claims.get("email") or "Your").strip()
    org_name = payload.laboratory_name.strip() if payload.laboratory_name else f"{owner_label}'s SIRALOOM Trial"
    org, user, membership = _provision_organization(db, subject=subject, claims=claims, organization_name=org_name)
    entitlement = create_trial_entitlement(db, org.id)
    db.commit()
    return {
        "organization_id": str(org.id), "membership_id": str(membership.id),
        "role": membership.role, "entitlement": summarize(entitlement).as_dict(),
    }


class OrganizationInvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str
    expires_in_days: int = Field(default=7, ge=1, le=30)


@router.post("/invitations", status_code=201)
def create_organization_invitation(
    payload: OrganizationInvitationCreate,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Creates a tenant-scoped, single-use invitation for a verified Firebase email.

    The raw bearer token is returned once so a trusted UI/email-delivery layer can turn it
    into an invitation link. Only its SHA-256 hash is persisted in the database.
    """
    _require_invitation_role(principal, payload.role)
    email = _normalize_email(payload.email)

    existing = db.scalar(select(User).where(func.lower(User.email) == email))
    if existing and existing.organization_id != principal.organization_id:
        raise HTTPException(status_code=409, detail="This email is already associated with another SIRALOOM organization")
    if existing:
        active = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.user_id == existing.id,
            OrganizationMembership.organization_id == principal.organization_id,
            OrganizationMembership.status == "ACTIVE",
        ))
        if active:
            raise HTTPException(status_code=409, detail="This user is already an active organization member")

    pending = db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.organization_id == principal.organization_id,
        func.lower(OrganizationInvitation.email) == email,
        OrganizationInvitation.status == "PENDING",
    ))
    if pending and pending.expires_at > datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="A pending invitation already exists for this email")
    if pending:
        pending.status = "EXPIRED"

    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        id=uuid4(), organization_id=principal.organization_id, email=email,
        role=payload.role, token_hash=_hash_invitation_token(token), status="PENDING",
        invited_by=principal.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days),
    )
    db.add(invitation)
    db.commit()
    return {
        "invitation_id": str(invitation.id),
        "email": invitation.email,
        "role": invitation.role,
        "status": invitation.status,
        "expires_at": invitation.expires_at,
        "invitation_token": token,
    }


class InvitationAcceptance(BaseModel):
    token: str = Field(min_length=20, max_length=256)


@router.post("/invitations/accept", status_code=200)
def accept_organization_invitation(
    payload: InvitationAcceptance,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Accepts an invitation only when the verified Firebase email exactly matches it."""
    subject, claims = _authenticate_bearer(authorization)
    email = _normalize_email(claims.get("email"))
    invitation = db.scalar(select(OrganizationInvitation).where(
        OrganizationInvitation.token_hash == _hash_invitation_token(payload.token),
    ))
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if invitation.status != "PENDING":
        raise HTTPException(status_code=409, detail=f"Invitation is {invitation.status.lower()} and cannot be accepted")
    now = datetime.now(timezone.utc)
    if invitation.expires_at <= now:
        invitation.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=410, detail="Invitation has expired")
    if email != invitation.email.casefold():
        raise HTTPException(status_code=403, detail="The authenticated Firebase email does not match this invitation")

    user = db.scalar(select(User).where(User.external_subject == subject))
    if user:
        if user.organization_id != invitation.organization_id:
            raise HTTPException(status_code=409, detail="This identity already belongs to another SIRALOOM organization")
        membership = db.scalar(select(OrganizationMembership).where(
            OrganizationMembership.user_id == user.id,
            OrganizationMembership.organization_id == invitation.organization_id,
        ))
        if membership and membership.status == "ACTIVE":
            raise HTTPException(status_code=409, detail="This identity is already an active organization member")
        if membership:
            membership.role = invitation.role
            membership.status = "ACTIVE"
        else:
            membership = OrganizationMembership(
                id=uuid4(), organization_id=invitation.organization_id,
                user_id=user.id, role=invitation.role, status="ACTIVE",
            )
            db.add(membership)
        user.role = invitation.role
        user.status = "ACTIVE"
    else:
        user = User(
            id=uuid4(), organization_id=invitation.organization_id,
            external_subject=subject, email=claims.get("email"),
            display_name=str(claims.get("name") or claims.get("email") or "SIRALOOM user"),
            role=invitation.role, status="ACTIVE",
        )
        db.add(user)
        db.flush()
        membership = OrganizationMembership(
            id=uuid4(), organization_id=invitation.organization_id,
            user_id=user.id, role=invitation.role, status="ACTIVE",
        )
        db.add(membership)

    invitation.status = "ACCEPTED"
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = now
    db.commit()
    return {
        "organization_id": str(invitation.organization_id),
        "membership_id": str(membership.id),
        "role": membership.role,
        "status": membership.status,
    }


class MembershipUpdate(BaseModel):
    status: str | None = Field(default=None)
    role: str | None = Field(default=None)


@router.patch("/memberships/{membership_id}")
def update_organization_membership(
    membership_id: str,
    payload: MembershipUpdate,
    principal: Principal = Depends(get_current_principal),
    db: Session = Depends(get_db),
):
    """Suspends, revokes, or changes the role of a tenant member without permitting self-escalation."""
    try:
        membership_uuid = __import__("uuid").UUID(membership_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid membership id") from exc

    target = db.get(OrganizationMembership, membership_uuid)
    if not target or target.organization_id != principal.organization_id:
        raise HTTPException(status_code=404, detail="Membership not found")
    if target.user_id == principal.user_id and payload.status in {"SUSPENDED", "REVOKED"}:
        raise HTTPException(status_code=409, detail="You cannot suspend or revoke your own active membership")
    if principal.role not in {"organization_admin", "lab_director"}:
        raise HTTPException(status_code=403, detail="Your organization role is not authorized to manage memberships")

    if payload.status is not None and payload.status not in {"ACTIVE", "SUSPENDED", "REVOKED"}:
        raise HTTPException(status_code=422, detail="Membership status must be ACTIVE, SUSPENDED, or REVOKED")

    effective_role = payload.role if payload.role is not None else target.role
    effective_status = payload.status if payload.status is not None else target.status
    _ensure_active_admin_invariant(
        db,
        principal.organization_id,
        current_role=target.role,
        current_status=target.status,
        effective_role=effective_role,
        effective_status=effective_status,
    )

    if payload.role is not None:
        _require_invitation_role(principal, payload.role)
        target.role = payload.role
        user = db.get(User, target.user_id)
        if user:
            user.role = payload.role

    if payload.status is not None:
        target.status = payload.status
        user = db.get(User, target.user_id)
        if user:
            user.status = "ACTIVE" if payload.status == "ACTIVE" else "INACTIVE"

    db.commit()
    return {"membership_id": str(target.id), "role": target.role, "status": target.status}
