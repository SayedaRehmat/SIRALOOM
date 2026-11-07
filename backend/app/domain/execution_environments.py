"""Lab-owned execution environment contracts and fail-closed compatibility checks.

This is the domain contract layer, not a remote execution agent or provisioner.
It models the environment in which a qualified tool profile may run and keeps
tenant ownership, runtime identity, scheduler, capacity, storage and network
policy explicit. Persistent registration and agent heartbeats are separate
infrastructure work and are not implied by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Literal
from uuid import UUID

from backend.app.domain.tool_execution import ToolIdentity


class ExecutionEnvironmentError(ValueError):
    """An environment profile is incomplete, unsafe or incompatible."""


EnvironmentOwner = Literal["SIRALOOM", "LABORATORY"]
ExecutorKind = Literal["LOCAL_PROCESS", "CONTAINER", "REMOTE_AGENT"]
SchedulerKind = Literal["NONE", "DOCKER_COMPOSE", "KUBERNETES", "SLURM"]
RuntimeKind = Literal["HOST", "DOCKER", "PODMAN", "OCI"]
NetworkPolicy = Literal["OFFLINE", "ALLOWLISTED_EGRESS"]


@dataclass(frozen=True)
class ExecutionCapacity:
    cpu_cores: float
    memory_bytes: int
    scratch_bytes: int
    max_concurrency: int
    gpu_count: int = 0

    def validate(self) -> None:
        if self.cpu_cores <= 0:
            raise ExecutionEnvironmentError("Environment CPU capacity must be positive.")
        if self.memory_bytes <= 0 or self.scratch_bytes <= 0:
            raise ExecutionEnvironmentError("Environment memory and scratch capacity must be positive.")
        if self.max_concurrency < 1:
            raise ExecutionEnvironmentError("Environment max_concurrency must be at least one.")
        if self.gpu_count < 0:
            raise ExecutionEnvironmentError("Environment GPU count cannot be negative.")


@dataclass(frozen=True)
class ExecutionEnvironmentProfile:
    environment_id: str
    profile_version: str
    owner_scope: EnvironmentOwner
    organization_id: UUID | None
    executor_kind: ExecutorKind
    platform: str
    operating_system: str
    architecture: str
    kernel_release: str
    runtime_kind: RuntimeKind
    runtime_version: str
    runtime_image_digest: str | None
    scheduler: SchedulerKind
    capacity: ExecutionCapacity
    workspace_root: str
    storage_profile_ids: tuple[str, ...]
    supported_tool_profile_ids: tuple[str, ...]
    network_policy: NetworkPolicy
    allowed_egress_hosts: tuple[str, ...] = ()
    agent_id: str | None = None
    agent_version: str | None = None
    agent_last_seen_at: datetime | None = None
    qualification_status: str = "DISCOVERED"

    def validate(self) -> None:
        if self.owner_scope not in {"SIRALOOM", "LABORATORY"}:
            raise ExecutionEnvironmentError("Unknown execution environment owner scope.")
        if self.executor_kind not in {"LOCAL_PROCESS", "CONTAINER", "REMOTE_AGENT"}:
            raise ExecutionEnvironmentError("Unknown execution environment executor kind.")
        if self.scheduler not in {"NONE", "DOCKER_COMPOSE", "KUBERNETES", "SLURM"}:
            raise ExecutionEnvironmentError("Unknown execution environment scheduler.")
        if self.runtime_kind not in {"HOST", "DOCKER", "PODMAN", "OCI"}:
            raise ExecutionEnvironmentError("Unknown execution environment runtime kind.")
        if self.network_policy not in {"OFFLINE", "ALLOWLISTED_EGRESS"}:
            raise ExecutionEnvironmentError("Unknown execution environment network policy.")
        if self.executor_kind == "CONTAINER" and self.runtime_kind == "HOST":
            raise ExecutionEnvironmentError("Container execution requires a container runtime.")
        required = {
            "environment_id": self.environment_id,
            "profile_version": self.profile_version,
            "platform": self.platform,
            "operating_system": self.operating_system,
            "architecture": self.architecture,
            "kernel_release": self.kernel_release,
            "runtime_version": self.runtime_version,
            "workspace_root": self.workspace_root,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ExecutionEnvironmentError(
                "Execution environment is missing: " + ", ".join(missing)
            )
        if self.owner_scope == "LABORATORY" and self.organization_id is None:
            raise ExecutionEnvironmentError(
                "A laboratory-owned environment must be bound to an organization."
            )
        if self.owner_scope == "SIRALOOM" and self.organization_id is not None:
            raise ExecutionEnvironmentError(
                "A SIRALOOM-managed environment cannot carry a laboratory organization ID."
            )
        if self.executor_kind == "REMOTE_AGENT" and not self.agent_id:
            raise ExecutionEnvironmentError("Remote-agent environments require an agent identity.")
        if self.executor_kind != "REMOTE_AGENT" and self.agent_id is not None:
            raise ExecutionEnvironmentError("Only remote-agent environments may declare agent_id.")
        if self.runtime_kind == "HOST" and self.runtime_image_digest is not None:
            raise ExecutionEnvironmentError("Host runtime profiles cannot declare a container image digest.")
        if self.runtime_kind != "HOST" and not re.fullmatch(
            r"sha256:[0-9a-f]{64}", (self.runtime_image_digest or "").lower()
        ):
            raise ExecutionEnvironmentError(
                "Container runtime profiles require a pinned sha256 image digest."
            )
        if not self.workspace_root.startswith("/") or "\\x00" in self.workspace_root:
            raise ExecutionEnvironmentError("Environment workspace_root must be an absolute POSIX path.")
        self.capacity.validate()
        if not self.storage_profile_ids or any(not item.strip() for item in self.storage_profile_ids):
            raise ExecutionEnvironmentError("At least one approved storage profile is required.")
        if len(set(self.storage_profile_ids)) != len(self.storage_profile_ids):
            raise ExecutionEnvironmentError("Storage profile IDs must be unique.")
        if not self.supported_tool_profile_ids or any(
            not item.strip() for item in self.supported_tool_profile_ids
        ):
            raise ExecutionEnvironmentError("At least one explicitly supported tool profile is required.")
        if len(set(self.supported_tool_profile_ids)) != len(self.supported_tool_profile_ids):
            raise ExecutionEnvironmentError("Supported tool profile IDs must be unique.")
        if self.network_policy == "OFFLINE" and self.allowed_egress_hosts:
            raise ExecutionEnvironmentError("Offline environments cannot declare egress hosts.")
        if self.network_policy == "ALLOWLISTED_EGRESS":
            if not self.allowed_egress_hosts:
                raise ExecutionEnvironmentError("Allowlisted egress requires at least one host.")
            for host in self.allowed_egress_hosts:
                if not re.fullmatch(r"[A-Za-z0-9.-]+", host) or ".." in host or host.startswith(".") or host.endswith("."):
                    raise ExecutionEnvironmentError(f"Invalid allowlisted egress host: {host!r}.")
        if self.qualification_status not in {
            "DISCOVERED", "STAGED", "QUALIFICATION_PENDING", "ENVIRONMENT_QUALIFIED",
            "SUSPENDED", "RETIRED",
        }:
            raise ExecutionEnvironmentError("Unknown execution environment qualification status.")
        if self.agent_last_seen_at is not None and self.agent_last_seen_at.tzinfo is None:
            raise ExecutionEnvironmentError("Agent heartbeat timestamps must be timezone-aware.")
        if self.executor_kind == "REMOTE_AGENT" and not self.agent_version:
            raise ExecutionEnvironmentError("Remote-agent environments require an agent version.")

    def assert_tenant_access(self, organization_id: UUID) -> None:
        self.validate()
        if self.owner_scope == "LABORATORY" and self.organization_id != organization_id:
            raise ExecutionEnvironmentError(
                "Execution environment belongs to a different laboratory."
            )

    def assert_tool_compatible(self, tool: ToolIdentity) -> None:
        self.validate()
        if self.qualification_status != "ENVIRONMENT_QUALIFIED":
            raise ExecutionEnvironmentError(
                "Only environment-qualified profiles may accept scientific executions."
            )
        if tool.qualification_status != "SOFTWARE_QUALIFIED":
            raise ExecutionEnvironmentError(
                "Only software-qualified tool profiles may run in a qualified environment."
            )
        if tool.profile_id not in self.supported_tool_profile_ids:
            raise ExecutionEnvironmentError(
                f"Tool profile {tool.profile_id!r} is not approved for environment {self.environment_id!r}."
            )
        if tool.platform != self.platform:
            raise ExecutionEnvironmentError(
                f"Tool platform {tool.platform!r} does not match environment platform {self.platform!r}."
            )
        if tool.runtime_image_digest != self.runtime_image_digest:
            raise ExecutionEnvironmentError(
                "Tool runtime image digest does not exactly match the qualified environment runtime."
            )

    def snapshot(self) -> dict:
        """Return deterministic environment identity for an analysis snapshot."""
        self.validate()
        return {
            "environment_id": self.environment_id,
            "profile_version": self.profile_version,
            "owner_scope": self.owner_scope,
            "organization_id": str(self.organization_id) if self.organization_id else None,
            "executor_kind": self.executor_kind,
            "platform": self.platform,
            "operating_system": self.operating_system,
            "architecture": self.architecture,
            "kernel_release": self.kernel_release,
            "runtime_kind": self.runtime_kind,
            "runtime_version": self.runtime_version,
            "runtime_image_digest": self.runtime_image_digest,
            "scheduler": self.scheduler,
            "capacity": {
                "cpu_cores": self.capacity.cpu_cores,
                "memory_bytes": self.capacity.memory_bytes,
                "scratch_bytes": self.capacity.scratch_bytes,
                "max_concurrency": self.capacity.max_concurrency,
                "gpu_count": self.capacity.gpu_count,
            },
            "workspace_root": self.workspace_root,
            "storage_profile_ids": list(self.storage_profile_ids),
            "supported_tool_profile_ids": list(self.supported_tool_profile_ids),
            "network_policy": self.network_policy,
            "allowed_egress_hosts": list(self.allowed_egress_hosts),
            "agent_id": self.agent_id,
            "agent_version": self.agent_version,
            "agent_last_seen_at": (
                self.agent_last_seen_at.astimezone(timezone.utc).isoformat()
                if self.agent_last_seen_at else None
            ),
            "qualification_status": self.qualification_status,
        }


@dataclass(frozen=True)
class ExecutionEnvironmentRegistry:
    """Immutable in-process registry view; persistence is supplied by a repository."""

    profiles: tuple[ExecutionEnvironmentProfile, ...]

    def validate(self) -> None:
        identifiers = [item.environment_id for item in self.profiles]
        if len(identifiers) != len(set(identifiers)):
            raise ExecutionEnvironmentError("Execution environment IDs must be unique.")
        for profile in self.profiles:
            profile.validate()

    def resolve(
        self,
        environment_id: str,
        *,
        organization_id: UUID,
        tool: ToolIdentity,
    ) -> ExecutionEnvironmentProfile:
        self.validate()
        matches = [item for item in self.profiles if item.environment_id == environment_id]
        if len(matches) != 1:
            raise ExecutionEnvironmentError(
                f"Unknown or ambiguous execution environment: {environment_id!r}."
            )
        profile = matches[0]
        profile.assert_tenant_access(organization_id)
        profile.assert_tool_compatible(tool)
        return profile


def require_fresh_agent_heartbeat(
    profile: ExecutionEnvironmentProfile,
    *,
    now: datetime | None = None,
    max_age_seconds: int = 120,
) -> None:
    """Fail closed for remote dispatch when an agent heartbeat is stale or absent."""
    if profile.executor_kind != "REMOTE_AGENT":
        return
    if max_age_seconds < 1:
        raise ExecutionEnvironmentError("Heartbeat maximum age must be positive.")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ExecutionEnvironmentError("Heartbeat comparison time must be timezone-aware.")
    heartbeat = profile.agent_last_seen_at
    if heartbeat is None:
        raise ExecutionEnvironmentError("Remote execution agent has no recorded heartbeat.")
    age = (observed_now - heartbeat).total_seconds()
    if age < 0 or age > max_age_seconds:
        raise ExecutionEnvironmentError("Remote execution agent heartbeat is stale.")
