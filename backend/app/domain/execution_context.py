"""Resolve mandatory, case-bound persistent execution context."""
from __future__ import annotations

from sqlalchemy.orm import Session

from backend.app.domain.execution_environments import (
    ExecutionEnvironmentError,
    execution_environment_profile_from_snapshot,
)
from backend.app.domain.container_tool_execution import ContainerResourceLimits
from backend.app.domain.persistent_tool_executor import PersistentToolExecutionService
from backend.app.infrastructure.db.models import Case, ExecutionEnvironmentRegistration


class ExecutionEnvironmentAssignmentError(RuntimeError):
    """A case cannot execute scientific tools without an approved environment."""


def persistent_execution_for_case(
    db: Session,
    *,
    case: Case,
    worker_id: str,
    analysis_id=None,
) -> PersistentToolExecutionService:
    registration_id = case.execution_environment_registration_id
    if registration_id is None:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_REQUIRED: assign an environment-qualified registration "
            "to the case before scientific processing."
        )
    registration = db.get(ExecutionEnvironmentRegistration, registration_id)
    if registration is None:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_MISSING: the assigned execution environment registration "
            "does not exist."
        )
    if registration.owner_scope == "LABORATORY" and registration.organization_id != case.organization_id:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_TENANT_MISMATCH: the assigned environment belongs to another laboratory."
        )
    if registration.qualification_status != "ENVIRONMENT_QUALIFIED":
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_NOT_QUALIFIED: the assigned execution environment is not qualified."
        )

    try:
        profile = execution_environment_profile_from_snapshot(registration.profile_json)
        profile.assert_tenant_access(case.organization_id)
    except (ExecutionEnvironmentError, TypeError, ValueError) as exc:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_PROFILE_INVALID: the registered environment profile is invalid."
        ) from exc

    if (
        profile.environment_id != registration.environment_id
        or profile.profile_version != registration.profile_version
        or profile.owner_scope != registration.owner_scope
        or profile.organization_id != registration.organization_id
        or profile.qualification_status != "ENVIRONMENT_QUALIFIED"
    ):
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_ENVIRONMENT_IDENTITY_MISMATCH: registration columns do not match the immutable profile snapshot."
        )

    # The first commercial Lab Server release is a customer-owned Linux OCI
    # worker, not an unrestricted host-process execution mode or remote agent.
    if (
        profile.executor_kind != "CONTAINER"
        or profile.runtime_kind not in {"DOCKER", "PODMAN"}
        or profile.operating_system.casefold() != "linux"
        or profile.scheduler not in {"NONE", "DOCKER_COMPOSE"}
        or profile.network_policy != "OFFLINE"
    ):
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_RUNTIME_UNSUPPORTED: Lab Server scientific execution requires a qualified "
            "Linux Docker/Podman container profile with offline networking and no remote scheduler."
        )

    if profile.job_limits is None:
        raise ExecutionEnvironmentAssignmentError(
            "CASE_EXECUTION_LIMITS_REQUIRED: the qualified environment has no per-job OCI limits."
        )

    return PersistentToolExecutionService(
        db,
        organization_id=case.organization_id,
        case_id=case.id,
        analysis_id=analysis_id,
        environment_registration_id=registration.id,
        worker_id=worker_id,
        container_limits=ContainerResourceLimits(
            cpu_cores=profile.job_limits.cpu_cores,
            memory_bytes=profile.job_limits.memory_bytes,
            pids_limit=profile.job_limits.pids_limit,
            container_user=profile.job_limits.container_user,
        ),
    )
