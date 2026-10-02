"""Resolve the deployment-level resource policy without creating a second workflow.

The workflow is identical in trial and laboratory deployments. Only the governed
resource resolution policy differs:
- TRIAL_PUBLIC: SIRALOOM-managed global resources may be selected.
- LABORATORY: an organization-approved binding is required for resource recovery.

No adapter is allowed to infer a deployment mode from URLs or environment flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.infrastructure.db.models import (
    OrganizationEntitlement,
    ResourceDeploymentProfile,
)


class ResourceDeploymentProfileError(ValueError):
    pass


TRIAL_PUBLIC = "TRIAL_PUBLIC"
LABORATORY = "LABORATORY"
PROFILE_TYPES = frozenset({TRIAL_PUBLIC, LABORATORY})


@dataclass(frozen=True)
class ResourceDeploymentPolicy:
    profile_type: str
    profile_version: str
    allow_siraloom_managed_global_resources: bool
    require_organization_binding_for_lab_resources: bool

    @property
    def is_trial(self) -> bool:
        return self.profile_type == TRIAL_PUBLIC

    @property
    def is_laboratory(self) -> bool:
        return self.profile_type == LABORATORY


def _policy_for_profile(profile: ResourceDeploymentProfile) -> ResourceDeploymentPolicy:
    return ResourceDeploymentPolicy(
        profile_type=profile.profile_type,
        profile_version=profile.profile_version,
        allow_siraloom_managed_global_resources=(
            profile.profile_type == TRIAL_PUBLIC
        ),
        require_organization_binding_for_lab_resources=(
            profile.profile_type == LABORATORY
        ),
    )


def resolve_resource_deployment_policy(
    db: Session,
    *,
    organization_id: UUID,
) -> ResourceDeploymentPolicy:
    """Resolve the immutable deployment policy used for resource selection.

    An explicit profile wins. For existing trial organizations created before
    profiles existed, the entitlement plan is a backwards-compatible bootstrap
    signal. All non-trial organizations default to LABORATORY, preventing
    accidental use of SIRALOOM-managed global resources for lab deployments.
    """
    profile = db.scalar(
        select(ResourceDeploymentProfile).where(
            ResourceDeploymentProfile.organization_id == organization_id,
            ResourceDeploymentProfile.status == "ACTIVE",
        )
    )
    if profile is not None:
        return _policy_for_profile(profile)

    entitlement = db.scalar(
        select(OrganizationEntitlement).where(
            OrganizationEntitlement.organization_id == organization_id,
            OrganizationEntitlement.status == "ACTIVE",
        )
    )
    if entitlement is not None and entitlement.plan.strip().upper() in {"TRIAL", "EVALUATION"}:
        return ResourceDeploymentPolicy(
            profile_type=TRIAL_PUBLIC,
            profile_version="bootstrap-from-entitlement-v1",
            allow_siraloom_managed_global_resources=True,
            require_organization_binding_for_lab_resources=False,
        )

    return ResourceDeploymentPolicy(
        profile_type=LABORATORY,
        profile_version="bootstrap-default-laboratory-v1",
        allow_siraloom_managed_global_resources=False,
        require_organization_binding_for_lab_resources=True,
    )


def create_resource_deployment_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_type: str,
    profile_version: str = "1",
) -> ResourceDeploymentProfile:
    profile_type = profile_type.strip().upper()
    if profile_type not in PROFILE_TYPES:
        raise ResourceDeploymentProfileError(
            f"profile_type must be one of {sorted(PROFILE_TYPES)}"
        )
    if not profile_version.strip():
        raise ResourceDeploymentProfileError("profile_version is required")

    existing = db.scalar(
        select(ResourceDeploymentProfile).where(
            ResourceDeploymentProfile.organization_id == organization_id,
        )
    )
    if existing is not None:
        raise ResourceDeploymentProfileError(
            "organization already has a deployment profile"
        )

    profile = ResourceDeploymentProfile(
        id=__import__("uuid").uuid4(),
        organization_id=organization_id,
        profile_type=profile_type,
        profile_version=profile_version.strip(),
        status="ACTIVE",
    )
    db.add(profile)
    db.flush()
    return profile
