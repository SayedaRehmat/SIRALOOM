from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from backend.app.domain.execution_environments import (
    ExecutionCapacity,
    ExecutionEnvironmentError,
    ExecutionEnvironmentProfile,
    ExecutionJobLimits,
    ExecutionEnvironmentRegistry,
    require_fresh_agent_heartbeat,
    execution_environment_profile_from_snapshot,
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
    image_reference: str | None = None,
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
        runtime_image_reference=image_reference,
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
        tool_executable_sha256=(("bcftools-1.25-htslib-1.25-linux-amd64", "a" * 64),),
        agent_id="agent-a" if executor_kind == "REMOTE_AGENT" else None,
        agent_version="1.0.0" if executor_kind == "REMOTE_AGENT" else None,
        agent_last_seen_at=agent_last_seen_at,
        qualification_status=status,
        job_limits=(
            ExecutionJobLimits(
                cpu_cores=2,
                memory_bytes=8 * 1024**3,
                pids_limit=1024,
                container_user="10001:10001",
            )
            if executor_kind == "CONTAINER" else None
        ),
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


def test_qualified_environment_requires_and_enforces_executable_digest():
    profile = _environment(uuid4())
    with pytest.raises(ExecutionEnvironmentError, match="approved executable SHA-256"):
        ExecutionEnvironmentProfile(
            **{
                **profile.__dict__,
                "tool_executable_sha256": (),
            }
        ).validate()

    changed_tool = ToolIdentity(
        **{
            **_tool().__dict__,
            "executable_sha256": "b" * 64,
        }
    )
    with pytest.raises(ExecutionEnvironmentError, match="approved executable digest"):
        profile.assert_tool_compatible(changed_tool)


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
    profile = _environment(uuid4(), runtime_kind="DOCKER", executor_kind="CONTAINER")

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



def test_container_environment_requires_repository_digest_reference():
    digest = "sha256:" + "b" * 64
    profile = _environment(
        uuid4(),
        runtime_kind="DOCKER",
        executor_kind="CONTAINER",
        image_digest=digest,
    )
    with pytest.raises(ExecutionEnvironmentError, match="immutable repository"):
        profile.validate()


def test_container_environment_rejects_reference_digest_mismatch():
    digest = "sha256:" + "b" * 64
    profile = _environment(
        uuid4(),
        runtime_kind="PODMAN",
        executor_kind="CONTAINER",
        image_digest=digest,
        image_reference="registry.example.org/siraloom/bcftools@sha256:" + "c" * 64,
    )
    with pytest.raises(ExecutionEnvironmentError, match="exactly match"):
        profile.validate()


def test_container_environment_snapshot_records_immutable_image_reference():
    digest = "sha256:" + "b" * 64
    reference = "registry.example.org/siraloom/bcftools@" + digest
    profile = _environment(
        uuid4(),
        runtime_kind="DOCKER",
        executor_kind="CONTAINER",
        image_digest=digest,
        image_reference=reference,
    )
    assert profile.snapshot()["runtime_image_reference"] == reference



def test_persisted_environment_snapshot_round_trips_runtime_contract():
    original = _environment(uuid4())
    restored = execution_environment_profile_from_snapshot(original.snapshot())
    assert restored.snapshot() == original.snapshot()



def test_container_environment_snapshot_round_trips_immutable_image_identity():
    digest = "sha256:" + "d" * 64
    reference = "registry.example.org/siraloom/bcftools@" + digest
    original = _environment(
        uuid4(),
        runtime_kind="DOCKER",
        executor_kind="CONTAINER",
        image_digest=digest,
        image_reference=reference,
    )
    restored = execution_environment_profile_from_snapshot(original.snapshot())
    assert restored.runtime_image_digest == digest
    assert restored.runtime_image_reference == reference
    assert restored.snapshot() == original.snapshot()
