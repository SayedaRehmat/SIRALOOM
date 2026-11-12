from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.domain.execution_context import (
    ExecutionEnvironmentAssignmentError,
    persistent_execution_for_case,
)
from backend.app.domain.execution_environments import (
    ExecutionCapacity,
    ExecutionEnvironmentProfile,
    ExecutionJobLimits,
)


def _profile(organization_id, *, executor_kind="CONTAINER", owner_scope="LABORATORY"):
    container = executor_kind == "CONTAINER"
    digest = "sha256:" + "a" * 64 if container else None
    return ExecutionEnvironmentProfile(
        environment_id="lab-server-a",
        profile_version="1",
        owner_scope=owner_scope,
        organization_id=organization_id if owner_scope == "LABORATORY" else None,
        executor_kind=executor_kind,
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release="6.8.0",
        runtime_kind="DOCKER" if container else "HOST",
        runtime_version="27.0" if container else "host",
        runtime_image_digest=digest,
        scheduler="NONE",
        capacity=ExecutionCapacity(
            cpu_cores=8,
            memory_bytes=32 * 1024**3,
            scratch_bytes=100 * 1024**3,
            max_concurrency=2,
        ),
        workspace_root="/data/siraloom/workspaces",
        storage_profile_ids=("lab-artifacts",),
        supported_tool_profile_ids=("bcftools-1.25",),
        network_policy="OFFLINE",
        runtime_image_reference=(
            "registry.example.org/siraloom/worker@" + digest if container else None
        ),
        tool_executable_sha256=(("bcftools-1.25", "b" * 64),),
        qualification_status="ENVIRONMENT_QUALIFIED",
        job_limits=(
            ExecutionJobLimits(
                cpu_cores=4,
                memory_bytes=16 * 1024**3,
                pids_limit=1024,
                container_user="10001:10001",
            ) if container else None
        ),
    )


def _case(organization_id, registration_id):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        execution_environment_registration_id=registration_id,
    )


def test_case_execution_requires_explicit_environment_assignment():
    case = _case(uuid4(), None)
    db = SimpleNamespace(get=lambda *_args: pytest.fail("unassigned case must not query a registration"))

    with pytest.raises(ExecutionEnvironmentAssignmentError, match="CASE_EXECUTION_ENVIRONMENT_REQUIRED"):
        persistent_execution_for_case(db, case=case, worker_id="worker-1")


def test_case_execution_rejects_host_process_environment():
    organization_id = uuid4()
    profile = _profile(organization_id, executor_kind="LOCAL_PROCESS")
    registration = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        owner_scope="LABORATORY",
        environment_id=profile.environment_id,
        profile_version=profile.profile_version,
        qualification_status="ENVIRONMENT_QUALIFIED",
        profile_json=profile.snapshot(),
    )
    case = _case(organization_id, registration.id)
    db = SimpleNamespace(get=lambda *_args: registration)

    with pytest.raises(ExecutionEnvironmentAssignmentError, match="Linux Docker/Podman"):
        persistent_execution_for_case(db, case=case, worker_id="worker-1")


def test_case_execution_rejects_cross_tenant_registration():
    organization_id = uuid4()
    other_organization_id = uuid4()
    profile = _profile(other_organization_id)
    registration = SimpleNamespace(
        id=uuid4(),
        organization_id=other_organization_id,
        owner_scope="LABORATORY",
        environment_id=profile.environment_id,
        profile_version=profile.profile_version,
        qualification_status="ENVIRONMENT_QUALIFIED",
        profile_json=profile.snapshot(),
    )
    case = _case(organization_id, registration.id)
    db = SimpleNamespace(get=lambda *_args: registration)

    with pytest.raises(ExecutionEnvironmentAssignmentError, match="TENANT_MISMATCH"):
        persistent_execution_for_case(db, case=case, worker_id="worker-1")


def test_case_execution_passes_qualified_oci_resource_limits_to_executor():
    organization_id = uuid4()
    profile = _profile(organization_id)
    registration = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        owner_scope="LABORATORY",
        environment_id=profile.environment_id,
        profile_version=profile.profile_version,
        qualification_status="ENVIRONMENT_QUALIFIED",
        profile_json=profile.snapshot(),
    )
    case = _case(organization_id, registration.id)
    db = SimpleNamespace(get=lambda *_args: registration)

    service = persistent_execution_for_case(
        db,
        case=case,
        analysis_id=uuid4(),
        worker_id="worker-1",
    )

    assert service.case_id == case.id
    assert service.analysis_id is not None
    assert service.container_limits.cpu_cores == 4
    assert service.container_limits.memory_bytes == 16 * 1024**3
    assert service.container_limits.pids_limit == 1024
    assert service.container_limits.container_user == "10001:10001"
