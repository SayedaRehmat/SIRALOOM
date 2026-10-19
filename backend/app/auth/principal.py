from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.config import settings
from backend.app.infrastructure.db.models import OrganizationMembership, User
from backend.app.infrastructure.db.session import get_db

VALID_ROLES = frozenset({
    "platform_admin", "organization_admin", "lab_director", "clinical_geneticist",
    "reviewer", "bioinformatician", "lab_scientist", "read_only",
})

@dataclass(frozen=True)
class Principal:
    user_id: UUID
    organization_id: UUID
    role: str
    subject: str
    email: str | None = None

def _verify_firebase_token(token: str) -> dict:
    try:
        import firebase_admin
        from firebase_admin import auth, credentials, exceptions
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Firebase Admin SDK is not installed") from exc
    if not firebase_admin._apps:
        credential = credentials.Certificate(settings.firebase_credentials_path) if settings.firebase_credentials_path else credentials.ApplicationDefault()
        firebase_admin.initialize_app(credential, {"projectId": settings.firebase_project_id} if settings.firebase_project_id else None)
    try:
        return auth.verify_id_token(token, check_revoked=True)
    except (auth.InvalidIdTokenError, auth.UserDisabledError, auth.UserNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired Firebase token") from exc
    except exceptions.FirebaseError as exc:
        # Provider/key-fetch failures are service outages, not proof that the
        # user's identity is invalid. Keep them distinct so clients can fail
        # closed without unnecessarily signing out every active user.
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Firebase authentication is temporarily unavailable") from exc

def _development_principal(db: Session) -> Principal:
    # This path is deliberately unavailable when Firebase authentication is required.
    from backend.app.application.cases import ensure_dev_identity
    org, user = ensure_dev_identity(db)
    return Principal(user_id=user.id, organization_id=org.id, role="bioinformatician", subject=str(user.id), email=user.email)

def get_current_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        # The implicit local identity is a development/test convenience only.
        # Every shared environment (including staging and preview deployments)
        # must authenticate explicitly; "not production" is not a safe boundary.
        environment = settings.app_env.strip().lower()
        if settings.firebase_auth_required or environment not in {"development", "test"}:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer authentication is required",
            )
        return _development_principal(db)

    token = authorization.removeprefix("Bearer ").strip()
    decoded = _verify_firebase_token(token)
    subject = str(decoded.get("uid") or decoded.get("sub") or "")
    if not subject:
        raise HTTPException(status_code=401, detail="Firebase token has no subject")
    if not decoded.get("email_verified"):
        raise HTTPException(status_code=403, detail="A verified Firebase email is required")
    user = db.scalar(select(User).where(User.external_subject == subject))
    if not user:
        raise HTTPException(
            status_code=403,
            detail="No SIRALOOM user is provisioned for this identity",
            headers={"X-Siraloom-Session-State": "UNPROVISIONED"},
        )
    if str(user.status) != "ACTIVE":
        raise HTTPException(status_code=403, detail="This SIRALOOM account is inactive")
    membership = db.scalar(select(OrganizationMembership).where(
        OrganizationMembership.user_id == user.id,
        OrganizationMembership.organization_id == user.organization_id,
        OrganizationMembership.status == "ACTIVE",
    ))
    if not membership or membership.role not in VALID_ROLES:
        raise HTTPException(status_code=403, detail="No active SIRALOOM organization membership")
    return Principal(user_id=user.id, organization_id=membership.organization_id, role=membership.role, subject=subject, email=decoded.get("email"))

def require_case_tenant(case, principal: Principal) -> None:
    if case.organization_id != principal.organization_id:
        # Return 404 to avoid disclosing another tenant's object existence.
        raise HTTPException(status_code=404, detail="Case not found")
