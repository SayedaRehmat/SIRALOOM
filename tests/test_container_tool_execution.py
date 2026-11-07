from __future__ import annotations

from uuid import uuid4

import pytest

from backend.app.domain.container_tool_execution import (
    ContainerResourceLimits,
    EnvironmentAwareToolExecutor,
    LinuxContainerToolExecutor,
)
from backend.app.domain.execution_environments import ExecutionCapacity, ExecutionEnvironmentProfile
from backend.app.domain.tool_execution import ToolExecutionContractError, ToolIdentity


def _environment(*, runtime_kind: str = "DOCKER", executor_kind: str = "CONTAINER"):
    digest = "sha256:" + "a" * 64
    return ExecutionEnvironmentProfile(
        environment_id="linux-container-test",
        profile_version="1",
        owner_scope="LABORATORY",
        organization_id=uuid4(),
        executor_kind=executor_kind,
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release="6.8.0",
        runtime_kind=runtime_kind,
        runtime_version="Docker version 27",
        runtime_image_digest=digest,
        scheduler="NONE",
        capacity=ExecutionCapacity(8, 16 * 1024**3, 50 * 1024**3, 2),
        workspace_root="/var/lib/siraloom/workspaces",
        storage_profile_ids=("local-verified",),
        supported_tool_profile_ids=("bcftools-pinned",),
        network_policy="OFFLINE",
        runtime_image_reference="registry.example.org/siraloom/bcftools@" + digest,
        tool_executable_sha256=(("bcftools-pinned", "b" * 64),),
        qualification_status="ENVIRONMENT_QUALIFIED",
    )


def _tool():
    return ToolIdentity(
        tool_id="bcftools",
        version="1.25",
        profile_id="bcftools-pinned",
        executable="/usr/bin/bcftools",
        executable_sha256="b" * 64,
        platform="linux-64",
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains="bcftools 1.25",
        runtime_image_digest="sha256:" + "a" * 64,
    )


def test_container_adapter_requires_explicit_job_resource_limits():
    executor = EnvironmentAwareToolExecutor(_environment())
    with pytest.raises(ToolExecutionContractError, match="explicit per-job"):
        executor.execute(_tool(), None)


def test_container_limits_cannot_exceed_environment_capacity():
    environment = _environment()
    limits = ContainerResourceLimits(
        cpu_cores=9,
        memory_bytes=1024**3,
        pids_limit=256,
    )
    with pytest.raises(ToolExecutionContractError, match="CPU limit"):
        limits.validate(environment)


def test_container_runtime_must_be_installed_and_explicit():
    environment = _environment()
    limits = ContainerResourceLimits(2, 4 * 1024**3, 256)
    executor = LinuxContainerToolExecutor(
        environment,
        limits,
        runtime_path="/definitely/missing/docker",
    )
    with pytest.raises(ToolExecutionContractError, match="runtime path"):
        executor._runtime()


def test_environment_aware_executor_never_falls_back_for_remote_agent():
    environment = _environment(runtime_kind="OCI", executor_kind="REMOTE_AGENT")
    executor = EnvironmentAwareToolExecutor(environment)
    with pytest.raises(Exception, match="Only Docker and Podman"):
        executor.execute(_tool(), None)
