from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.domain.execution_environments import (
    ExecutionCapacity,
    ExecutionEnvironmentError,
    ExecutionEnvironmentProfile,
    ExecutionEnvironmentRegistry,
    require_fresh_agent_heartbeat,
)
from backend.app.domain.tool_execution import ToolIdentity


def _tool(*, platform: str = "linux-64", image_digest: str | None = None) -> ToolIdentity:
    return ToolIdentity(
        tool_id="bcftools",
        version="1.25",
        profile_id="bcftools-1.25-htslib-1.25-linux-amd64",
        executable="/usr/bin/bcftools",
        executable_sha256="a" * 64,
        platform=platform,
        qualification_status="SOFTWARE_QUALIFIED",
        version_args=("--version",),
        version_output_contains="bcftools 1.25",
        runtime_image_digest=image_digest,
    )


def _environment(
    organization_id,
    *,
    status: str = "ENVIRONMENT_QUALIFIED",
    owner_scope: str = "LABORATORY",
    runtime_kind: str = "HOST",
    image_digest: str | None = None,
    executor_kind: str = "LOCAL_PROCESS",
    agent_last_seen_at=None,
) -> ExecutionEnvironmentProfile:
    return ExecutionEnvironmentProfile(
        environment_id="lab-a-linux-amd64",
        profile_version="1",
        owner_scope=owner_scope,
        organization_id=organization_id if owner_scope == "LABORATORY" else None,
        executor_kind=executor_kind,
        platform="linux-64",
        operating_system="linux",
        architecture="x86_64",
        kernel_release="6.8.0",
        runtime_kind=runtime_kind,
        runtime_version="1",
        runtime_image_digest=image_digest,
        scheduler="DOCKER_COMPOSE",
        capacity=ExecutionCapacity(
            cpu_cores=8,
            memory_bytes=32 * 1024**3,
            scratch_bytes=100 * 1024**3,
            max_concurrency=4,
        ),
        workspace_root="/var/lib/siraloom/workspaces",
        storage_profile_ids=("lab-a-artifacts",),
        supported_tool_profile_ids=("bcftools-1.25-htslib-1.25-linux-amd64",),
        network_policy="OFFLINE",
        agent_id="agent-a" if executor_kind == "REMOTE_AGENT" else None,
        agent_version="1.0.0" if executor_kind == "REMOTE_AGENT" else None,
        agent_last_seen_at=agent_last_seen_at,
        qualification_status=status,
    )


def test_registry_resolves_qualified_tool_and_tenant_environment():
    organization_id = uuid4()
    profile = _environment(organization_id)
    registry = ExecutionEnvironmentRegistry((profile,))

    resolved = registry.resolve(
        profile.environment_id,
        organization_id=organization_id,
        tool=_tool(),
    )

    assert resolved is profile
    snapshot = resolved.snapshot()
    assert snapshot["organization_id"] == str(organization_id)
    assert snapshot["qualification_status"] == "ENVIRONMENT_QUALIFIED"
    assert snapshot["supported_tool_profile_ids"] == [
        "bcftools-1.25-htslib-1.25-linux-amd64"
    ]


def test_registry_rejects_cross_tenant_environment_access():
    profile = _environment(uuid4())
    registry = ExecutionEnvironmentRegistry((profile,))

    with pytest.raises(ExecutionEnvironmentError, match="different laboratory"):
        registry.resolve(
            profile.environment_id,
            organization_id=uuid4(),
            tool=_tool(),
        )


def test_registry_rejects_environment_without_qualification():
    profile = _environment(uuid4(), status="QUALIFICATION_PENDING")

    with pytest.raises(ExecutionEnvironmentError, match="environment-qualified"):
        profile.assert_tool_compatible(_tool())


def test_registry_rejects_tool_profile_not_explicitly_approved():
    profile = _environment(uuid4())
    incompatible_tool = ToolIdentity(
        **{
            **_tool().__dict__,
            "profile_id": "unapproved-tool-profile",
        }
    )

    with pytest.raises(ExecutionEnvironmentError, match="not approved"):
        profile.assert_tool_compatible(incompatible_tool)


def test_container_environment_requires_pinned_image_digest():
    profile = _environment(uuid4(), runtime_kind="DOCKER")

    with pytest.raises(ExecutionEnvironmentError, match="pinned sha256 image digest"):
        profile.validate()


def test_remote_agent_requires_fresh_heartbeat():
    now = datetime.now(timezone.utc)
    profile = _environment(
        uuid4(),
        executor_kind="REMOTE_AGENT",
        agent_last_seen_at=now - timedelta(seconds=30),
    )

    require_fresh_agent_heartbeat(profile, now=now, max_age_seconds=120)

    with pytest.raises(ExecutionEnvironmentError, match="heartbeat is stale"):
        require_fresh_agent_heartbeat(
            profile,
            now=now,
            max_age_seconds=10,
        )


def test_offline_environment_cannot_allow_egress():
    profile = _environment(uuid4())
    unsafe = ExecutionEnvironmentProfile(
        **{**profile.__dict__, "allowed_egress_hosts": ("example.org",)}
    )

    with pytest.raises(ExecutionEnvironmentError, match="Offline environments"):
        unsafe.validate()
