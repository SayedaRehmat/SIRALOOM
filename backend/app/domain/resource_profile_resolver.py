"""Deterministic preflight resolution of an analysis profile to governed resources."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.analysis_resource_profiles import (
    AnalysisResourceProfile,
    ProfileResourceRequirement,
    get_analysis_resource_profile,
)
from backend.app.domain.resource_capabilities import get_scientific_provider
from backend.app.domain.resource_deployment import resolve_resource_deployment_policy
from backend.app.domain.resource_execution import (
    ResourceExecutionError,
    ResolvedResourceExecution,
    resolve_resource_execution,
)
from backend.app.domain.workflow_resource_contracts import WORKFLOW_STAGE_CONTRACTS
from backend.app.infrastructure.db.models import (
    OrganizationResourceBinding,
    Resource,
)


class ResourceProfileResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedProfileResource:
    capability: str
    required: bool
    resource: Resource
    execution: ResolvedResourceExecution
    provider_rank: int

    @property
    def execution_for(self, capability: str) -> ResolvedProfileResource:
        """Return the exact preflight-selected resource for a workflow capability."""
        for item in self.selected:
            if item.capability == capability:
                return item
        raise ResourceProfileResolutionError(
            f"No selected resource exists for required capability {capability}."
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "capability": self.capability,
            "required": self.required,
            "resource_id": str(self.resource.id),
            "name": self.resource.name,
            "provider": self.resource.provider,
            "version": self.resource.version,
            "genome_build": self.resource.genome_build,
            "checksum": self.resource.checksum,
            "execution": self.execution.snapshot,
        }


@dataclass(frozen=True)
class ResourceResolutionIssue:
    capability: str
    required: bool
    code: str
    message: str
    candidate_count: int = 0


@dataclass(frozen=True)
class AnalysisResourcePlan:
    profile_id: str
    profile_version: str
    genome_build: str
    deployment_profile_type: str
    deployment_profile_version: str
    status: str
    selected: tuple[ResolvedProfileResource, ...]
    issues: tuple[ResourceResolutionIssue, ...]
    plan_hash: str

    @property
    def is_ready(self) -> bool:
        return self.status in {"READY", "READY_WITH_LIMITATIONS"}

    @property
    def required_issues(self) -> tuple[ResourceResolutionIssue, ...]:
        return tuple(i for i in self.issues if i.required)

    def snapshot(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "genome_build": self.genome_build,
            "deployment": {
                "profile_type": self.deployment_profile_type,
                "profile_version": self.deployment_profile_version,
            },
            "status": self.status,
            "selected": [r.snapshot for r in self.selected],
            "issues": [
                {
                    "capability": i.capability,
                    "required": i.required,
                    "code": i.code,
                    "message": i.message,
                    "candidate_count": i.candidate_count,
                }
                for i in self.issues
            ],
            "plan_hash": self.plan_hash,
        }


def build_workflow_stage_resource_plan(plan: AnalysisResourcePlan) -> list[dict[str, object]]:
    """Project the resolved analysis resource plan onto the canonical workflow stages.

    This is a deterministic derived snapshot: it never selects a different resource
    and it never changes the analysis-level readiness decision.
    """
    selected_by_capability = {item.capability: item for item in plan.selected}
    issues_by_capability = {item.capability: item for item in plan.issues}
    stage_plan: list[dict[str, object]] = []

    for contract in WORKFLOW_STAGE_CONTRACTS:
        capabilities = tuple(dict.fromkeys((*contract.required_resources, *contract.optional_resources)))
        stage_issues = [issues_by_capability[c] for c in capabilities if c in issues_by_capability]
        required_blocked = any(issue.required for issue in stage_issues)
        stage_plan.append({
            "step_id": contract.step_id,
            "order": contract.order,
            "purpose": contract.purpose,
            "status": (
                "BLOCKED"
                if required_blocked
                else "READY_WITH_LIMITATIONS"
                if stage_issues
                else "READY"
            ),
            "required_resources": list(contract.required_resources),
            "optional_resources": list(contract.optional_resources),
            "selected": [
                selected_by_capability[c].snapshot
                for c in capabilities
                if c in selected_by_capability
            ],
            "issues": [
                {
                    "capability": issue.capability,
                    "required": issue.required,
                    "code": issue.code,
                    "message": issue.message,
                    "candidate_count": issue.candidate_count,
                }
                for issue in stage_issues
            ],
        })
    return stage_plan


def _identity_key(resource: Resource) -> str:
    return "|".join(
        [
            resource.name,
            resource.provider,
            resource.resource_type,
            resource.genome_build or "UNSPECIFIED",
        ]
    )


def _organization_resource_ids(db: Session, organization_id: UUID) -> set[UUID]:
    rows = db.scalars(
        select(OrganizationResourceBinding.resource_id).where(
            OrganizationResourceBinding.organization_id == organization_id
        )
    ).all()
    return {UUID(str(row)) for row in rows}


def _candidate_resources(
    db: Session,
    *,
    organization_id: UUID,
    capability: str,
    genome_build: str,
    allow_global: bool,
    require_binding: bool,
) -> list[Resource]:
    conditions = [
        Resource.resource_type == capability,
        Resource.status == "ACTIVE",
    ]
    if genome_build:
        conditions.append(Resource.genome_build == genome_build)

    rows = db.scalars(select(Resource).where(*conditions)).all()
    bound_ids = _organization_resource_ids(db, organization_id)

    candidates: list[Resource] = []
    for resource in rows:
        if resource.organization_id is None:
            if allow_global:
                candidates.append(resource)
            continue
        if resource.organization_id != organization_id:
            continue
        if require_binding and resource.id not in bound_ids:
            continue
        candidates.append(resource)
    return candidates


def _provider_rank(provider: str, preferred: tuple[str, ...]) -> int:
    if not preferred:
        return 0
    normalized = provider.strip().upper()
    for index, value in enumerate(preferred):
        if normalized == value.upper():
            return index
    return len(preferred)


def _license_is_sufficient(resource: Resource, requirement: ProfileResourceRequirement) -> bool:
    if not requirement.license_required:
        return True
    return bool(str(resource.license_text or "").strip())


def _matches_known_provider(resource: Resource, capability: str) -> bool:
    try:
        provider = get_scientific_provider(resource.provider)
    except Exception:
        # Laboratory may register a provider that SIRALOOM does not yet know.
        # Capability type remains authoritative; adapter support is checked later.
        return True
    return provider.resource_type == capability


def _select_candidate(
    candidates: list[tuple[Resource, ResolvedResourceExecution]],
    requirement: ProfileResourceRequirement,
) -> tuple[tuple[Resource, ResolvedResourceExecution] | None, int, str | None]:
    eligible = [
        pair for pair in candidates
        if _matches_known_provider(pair[0], requirement.capability)
        and _license_is_sufficient(pair[0], requirement)
    ]
    if not eligible:
        return None, 0, "RESOURCE_UNAVAILABLE"

    ranked = sorted(
        eligible,
        key=lambda pair: (
            _provider_rank(pair[0].provider, requirement.preferred_providers),
            pair[0].provider.upper(),
            pair[0].name,
            pair[0].version,
            pair[0].checksum or "",
            str(pair[0].id),
        ),
    )
    best_rank = _provider_rank(ranked[0][0].provider, requirement.preferred_providers)
    best = [
        pair for pair in ranked
        if _provider_rank(pair[0].provider, requirement.preferred_providers) == best_rank
    ]

    # A profile may express provider preference, but it must never silently pick
    # between two equally preferred releases. The lab must make that choice.
    if len(best) != 1:
        return None, best_rank, "RESOURCE_AMBIGUOUS"
    return best[0], best_rank, None

def _plan_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def resolve_analysis_resource_profile(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: str,
    analysis_reference_build: str | None = None,
) -> AnalysisResourcePlan:
    profile: AnalysisResourceProfile = get_analysis_resource_profile(profile_id)
    if analysis_reference_build and analysis_reference_build != profile.genome_build:
        raise ResourceProfileResolutionError(
            f"resource profile {profile.profile_id} requires {profile.genome_build}, "
            f"but analysis reference_build is {analysis_reference_build}"
        )

    policy = resolve_resource_deployment_policy(
        db, organization_id=organization_id
    )

    selected: list[ResolvedProfileResource] = []
    issues: list[ResourceResolutionIssue] = []

    for requirement in profile.requirements:
        candidates = _candidate_resources(
            db,
            organization_id=organization_id,
            capability=requirement.capability,
            genome_build=profile.genome_build if requirement.genome_build_required else "",
            allow_global=policy.allow_siraloom_managed_global_resources,
            require_binding=policy.require_organization_binding_for_lab_resources,
        )
        qualified_candidates: list[tuple[Resource, ResolvedResourceExecution]] = []
        for candidate in candidates:
            try:
                execution = resolve_resource_execution(db, resource=candidate)
            except ResourceExecutionError:
                continue
            qualified_candidates.append((candidate, execution))

        selected_pair, provider_rank, selection_error = _select_candidate(
            qualified_candidates, requirement
        )
        resource = selected_pair[0] if selected_pair is not None else None
        execution = selected_pair[1] if selected_pair is not None else None

        if resource is None:
            code = selection_error or "RESOURCE_UNAVAILABLE"
            if code == "RESOURCE_AMBIGUOUS":
                message = (
                    f"Multiple equally preferred qualified candidates exist for "
                    f"{requirement.capability}; activate/bind one deterministic resource."
                )
            elif requirement.license_required:
                message = (
                    f"No licensed active resource is available for {requirement.capability}."
                )
            else:
                message = (
                    f"No active resource satisfies {requirement.capability} "
                    f"for profile {profile.profile_id}."
                )
            issues.append(ResourceResolutionIssue(
                requirement.capability, requirement.required, code, message, len(qualified_candidates)
            ))
            continue

        assert execution is not None

        selected.append(
            ResolvedProfileResource(
                capability=requirement.capability,
                required=requirement.required,
                resource=resource,
                execution=execution,
                provider_rank=provider_rank,
            )
        )

    required_blockers = tuple(i for i in issues if i.required)
    status = "BLOCKED" if required_blockers else "READY_WITH_LIMITATIONS" if issues else "READY"

    provisional = {
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "genome_build": profile.genome_build,
        "deployment_profile_type": policy.profile_type,
        "deployment_profile_version": policy.profile_version,
        "selected": [r.snapshot for r in selected],
        "issues": [
            {
                "capability": i.capability,
                "required": i.required,
                "code": i.code,
                "message": i.message,
            }
            for i in issues
        ],
    }
    return AnalysisResourcePlan(
        profile_id=profile.profile_id,
        profile_version=profile.version,
        genome_build=profile.genome_build,
        deployment_profile_type=policy.profile_type,
        deployment_profile_version=policy.profile_version,
        status=status,
        selected=tuple(selected),
        issues=tuple(issues),
        plan_hash=_plan_hash(provisional),
    )
