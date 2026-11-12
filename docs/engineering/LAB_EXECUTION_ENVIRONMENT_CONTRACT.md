# Laboratory Execution Environment Contract (A1)

## Purpose

This change introduces the domain contract used to describe a laboratory-owned
scientific execution environment and to reject incompatible or unqualified
tool/environment combinations before dispatch. It is additive to the common
tool execution contract in PR #301.

The contract separates five identities that must not be conflated:

1. **Laboratory ownership** — owner_scope and organization_id enforce tenant
   binding. A laboratory environment cannot be selected by another organization.
2. **Execution mechanism** — local process, container, or remote agent.
3. **Runtime identity** — host/container runtime, OS, architecture, kernel,
   runtime version and optional pinned image digest.
4. **Capacity and placement** — CPU, memory, scratch, concurrency, GPU count,
   scheduler, workspace and approved storage profiles.
5. **Governance** — explicitly supported tool profiles, network egress policy,
   and environment qualification status.

## Implemented

- Immutable dataclasses for capacity and environment profile identity.
- Strict validation of ownership, executor/runtime/scheduler/network enums,
  capacity, absolute workspace, storage/tool profile allowlists, egress hosts,
  container image digests and remote-agent identity.
- Fail-closed tenant check for laboratory-owned environments.
- Fail-closed tool compatibility check requiring:
  - environment qualification status ENVIRONMENT_QUALIFIED;
  - tool qualification status SOFTWARE_QUALIFIED;
  - explicit tool profile allowlisting;
  - exact platform match;
  - exact runtime image digest match.
- Remote-agent heartbeat freshness check (default maximum age 120 seconds).
- Deterministic environment snapshot suitable for later analysis-level
  persistence and provenance.
- Tests for tenant isolation, qualification, tool allowlisting, container
  digest pinning, heartbeat freshness and offline egress policy.

## Explicit non-claims / remaining work

This PR is environment contract A1, not a complete environment control plane.
It does not yet provide:

- database persistence, migrations, tenant-scoped CRUD or immutable version
  history for environment profiles;
- agent enrollment, mutual TLS, signed heartbeat, revocation or capability
  attestation;
- scheduler adapters for Docker Compose, Kubernetes or Slurm;
- resource leasing, queue routing, capacity reservation or concurrent quota
  enforcement;
- cgroup/container CPU, memory, process-count or scratch-disk enforcement;
- provisioning, image distribution, secrets delivery or network policy
  enforcement;
- durable environment snapshots attached to Analysis/ToolRun;
- production integration of environment resolution into workflow dispatch.

Those are separate implementation gates. A profile declaration is not proof
that the underlying host actually has the declared capacity or security
posture. Environment qualification must be backed by measured host/runtime
attestation and operational tests before production dispatch is enabled.

## Relationship to existing contracts

- toolchain_profiles.py remains the BCFtools/HTSlib scientific software
  profile registry. This contract does not replace it.
- tool_execution.py remains the tool-neutral process execution boundary.
  This contract selects/qualifies the environment in which that boundary may
  execute; it does not run processes itself.
- laboratory_deployment.py remains a deployment requirements declaration.
  It does not become an environment registry through this change.
- Resource profiles and organization resource bindings remain responsible for
  scientific data/reference/cache selection. storage_profile_ids here bind
  the execution environment to approved storage configurations, not to
  scientific evidence resources.

## Qualification boundary

Passing unit tests proves contract validation behavior only. It does not
qualify a physical lab host, remote agent, container image, scheduler, storage
system, or scientific tool. The environment must remain DISCOVERED,
STAGED, or QUALIFICATION_PENDING until measured qualification evidence is
available. Dispatch accepts only ENVIRONMENT_QUALIFIED environments.

## Lab Server case-workflow execution policy

The first commercial Lab Server workflow is stricter than the generic environment
contract. A case may be assigned only to an immutable, environment-qualified
profile whose snapshot and registration columns agree and whose tenant ownership
matches the case. The case-bound execution resolver rejects:

- host/local-process execution and remote agents;
- non-Linux environments or runtimes other than Docker and Podman;
- mutable/unpinned container images;
- network-enabled profiles and unsupported schedulers;
- missing per-job CPU, memory, PID and non-root UID:GID limits.

Container profiles carry explicit `job_limits`. CPU and memory limits must fit
the environment's concurrency-adjusted capacity; the OCI adapter applies the
limits at container creation. These are configuration and adapter controls,
not proof of a qualified host. The current implementation does **not** yet
enforce a per-job scratch-disk quota, durable capacity reservations, or an
end-to-end storage quota. Those remain release blockers for production
qualification.

The generic `LOCAL_PROCESS` executor remains available to non-clinical
development/qualified contexts, but the case-bound Lab Server resolver will
not select it. BCFtools and VEP scientific commands do not retain a local
subprocess fallback when a persistent case execution service is absent.
