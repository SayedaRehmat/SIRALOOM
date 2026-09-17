"""Licensing/usage envelope for organizations.

Design intent (see docs/authorization.md for the tenant model this sits on top of):

- A normal signup (``POST /auth/onboarding/organization``) creates an organization with
  *no* entitlement row. No entitlement row means no restrictions are enforced -- existing
  and paid organizations are unaffected by anything in this module.
- The free-trial signup path (``POST /auth/onboarding/trial``) explicitly creates a TRIAL
  entitlement with a time box and a usage cap, so a Lab Director can reach the product in
  under a minute without unlimited, unaudited access to clinical processing.
- Trial -> paid conversion later only needs to change the entitlement row's plan/status;
  it does not require re-provisioning the organization/user/membership.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.enums import EntitlementPlan, EntitlementStatus
from backend.app.infrastructure.db.models import OrganizationEntitlement

TRIAL_DURATION_DAYS = 14
TRIAL_MAX_ANALYSES = 5
TRIAL_MAX_VCF_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB: enough for a demonstration VCF, not a production WGS file.

# Plans that carry no automatic usage/time enforcement here. ON_PREMISE/ENTERPRISE deployments
# are expected to enforce their own contractual limits outside this module.
_UNRESTRICTED_PLANS = frozenset({EntitlementPlan.PAID, EntitlementPlan.ENTERPRISE, EntitlementPlan.ON_PREMISE})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_entitlement(db: Session, organization_id: UUID) -> OrganizationEntitlement | None:
    return db.scalar(select(OrganizationEntitlement).where(OrganizationEntitlement.organization_id == organization_id))


def create_trial_entitlement(db: Session, organization_id: UUID) -> OrganizationEntitlement:
    """Creates a time-boxed, usage-capped TRIAL entitlement for a newly provisioned organization.

    Callers are expected to have already checked that the organization has no existing
    entitlement row (an organization should only ever get one trial).
    """
    started = _now()
    entitlement = OrganizationEntitlement(
        id=uuid4(),
        organization_id=organization_id,
        plan=EntitlementPlan.TRIAL,
        status=EntitlementStatus.ACTIVE,
        max_analyses=TRIAL_MAX_ANALYSES,
        analyses_used=0,
        max_vcf_size_bytes=TRIAL_MAX_VCF_SIZE_BYTES,
        trial_started_at=started,
        trial_expires_at=started + timedelta(days=TRIAL_DURATION_DAYS),
    )
    db.add(entitlement)
    return entitlement


@dataclass(frozen=True)
class EntitlementSummary:
    plan: str
    status: str
    analyses_used: int | None
    max_analyses: int | None
    trial_expires_at: datetime | None

    def as_dict(self) -> dict:
        return {
            "plan": self.plan,
            "status": self.status,
            "analyses_used": self.analyses_used,
            "max_analyses": self.max_analyses,
            "trial_expires_at": self.trial_expires_at.isoformat() if self.trial_expires_at else None,
        }


def summarize(entitlement: OrganizationEntitlement | None) -> EntitlementSummary | None:
    if entitlement is None:
        return None
    return EntitlementSummary(
        plan=entitlement.plan,
        status=_effective_status(entitlement),
        analyses_used=entitlement.analyses_used,
        max_analyses=entitlement.max_analyses,
        trial_expires_at=entitlement.trial_expires_at,
    )


def _effective_status(entitlement: OrganizationEntitlement) -> str:
    """Computes status lazily instead of relying on a background job to flip it."""
    if entitlement.status in (EntitlementStatus.CONVERTED, EntitlementStatus.CANCELLED):
        return entitlement.status
    if entitlement.plan in _UNRESTRICTED_PLANS:
        return EntitlementStatus.ACTIVE
    if entitlement.trial_expires_at and _now() >= entitlement.trial_expires_at:
        return EntitlementStatus.EXPIRED
    if entitlement.max_analyses is not None and entitlement.analyses_used >= entitlement.max_analyses:
        return EntitlementStatus.EXHAUSTED
    return EntitlementStatus.ACTIVE


def require_analysis_quota(db: Session, organization_id: UUID) -> None:
    """Raises if the organization's entitlement forbids starting another analysis.

    No-op when the organization has no entitlement row (normal/paid organizations) or
    when its plan is one of the unrestricted plans.
    """
    entitlement = get_entitlement(db, organization_id)
    if entitlement is None or entitlement.plan in _UNRESTRICTED_PLANS:
        return
    status = _effective_status(entitlement)
    if status == EntitlementStatus.EXPIRED:
        raise HTTPException(status_code=402, detail="Your SIRALOOM trial has expired. Upgrade to continue running analyses.")
    if status == EntitlementStatus.EXHAUSTED:
        raise HTTPException(status_code=402, detail=f"Your SIRALOOM trial has used all {entitlement.max_analyses} included analyses. Upgrade to continue.")
    if status in (EntitlementStatus.CONVERTED, EntitlementStatus.CANCELLED):
        raise HTTPException(status_code=402, detail="This trial workspace is no longer active.")


def consume_analysis_quota(db: Session, organization_id: UUID) -> None:
    """Increments trial usage after an analysis has actually been created.

    Call this only after `require_analysis_quota` has passed and the analysis was
    successfully persisted, so a failed request never burns a trial credit.
    """
    entitlement = get_entitlement(db, organization_id)
    if entitlement is None or entitlement.plan in _UNRESTRICTED_PLANS:
        return
    entitlement.analyses_used += 1
    db.add(entitlement)
    db.commit()


def effective_max_upload_bytes(db: Session, organization_id: UUID, default_max_bytes: int) -> int:
    """Returns the smaller of the platform-wide upload limit and any trial-specific limit."""
    entitlement = get_entitlement(db, organization_id)
    if entitlement is None or entitlement.max_vcf_size_bytes is None:
        return default_max_bytes
    return min(default_max_bytes, entitlement.max_vcf_size_bytes)
