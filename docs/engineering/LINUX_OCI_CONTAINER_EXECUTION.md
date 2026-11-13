# Linux OCI container execution contract

## Scope

The common ToolExecutionRequest / ToolExecutionResult /
ToolExecutionProvenance contract is retained. EnvironmentAwareToolExecutor
selects the local-process executor for qualified HOST environments and the
Linux OCI adapter for qualified CONTAINER environments. The persistent execution service rehydrates the immutable registered environment
snapshot and selects the adapter when no explicit executor override is supplied.
Remote agents and unsupported schedulers fail closed; they never fall back to
host execution.

## Immutable image identity

A container environment must register both:

- runtime_image_digest: sha256:<64 lowercase hex>
- runtime_image_reference: registry/repository@sha256:<same digest>

A mutable tag is not accepted. Docker/Podman must already have the exact
repository digest locally; execution uses --pull=never. The adapter verifies
the Docker daemon (or Podman runtime) version, the inspected repository digest,
the in-image executable SHA-256, and the tool's version output before running
the requested operation.

## Isolation and resource enforcement

- Workspace is the only writable bind mount and is mounted at /workspace.
- Each input and each scientific resource is mounted separately read-only.
- Workspace symlinks, special files, and hard-linked files are rejected before mounting.
- The container root filesystem is read-only; /tmp, /inputs, and
  /resources are bounded tmpfs mount points.
- Network is disabled. Environments declaring allowlisted egress are rejected
  until a separately qualified network enforcement implementation exists.
- A verifiable Linux cgroup v1/v2 controller is required before resource flags are used.
- CPU, memory, swap, PID count, non-root UID/GID, Linux capabilities, and
  privilege escalation are constrained explicitly. UID or GID zero is rejected.
- Request timeout invokes runtime kill, terminates the runtime client process
  group, force-removes the named container, and verifies that no container
  remains. Cleanup uncertainty is returned as a retryable error with provenance.
- Output files are checksummed after the container exits; missing outputs or
  non-zero exits cannot return a successful result.

## Qualification evidence and boundary

The Linux integration qualification runs in GitHub Actions on an Ubuntu 24.04
x86_64 runner. CI builds the scientific worker image, publishes it to a
temporary local registry, and pulls the exact same immutable repository digest
for both Docker and Podman. The 7-test integration suite runs independently
against each runtime.

Run #4483 passed:
- Docker: 7 integration tests passed.
- Podman 4.9.3, rootful, cgroup v2: 7 integration tests passed.
- The tests execute BCFtools 1.25 reference-backed indel normalization and
  verify output checksums/provenance.
- Read-only input/resource mounts and writable workspace behavior are tested
  against the actual runtimes.
- CPU quota, memory limit/OOM behavior, and PID limit/fork denial are tested
  through the container's cgroup v2 files and controlled workload.
- Timeout termination, container removal, runtime image-inspection failure,
  and kill-command failure with force-remove recovery are tested.
- The same pinned worker image digest is used by both runtimes:
  sha256:0f86d45d8c121a34d6095550375c7d9f96f3b0083a0f50c599a3f039a90353db.

This qualifies the tested GitHub-hosted Linux runner and its runtime/cgroup
configuration. It does not establish qualification across every Linux
distribution, kernel, rootless Podman installation, lab host, storage backend,
or production resource policy. Lab-host qualification must register and test
the actual runtime version, cgroup mode, storage mounts, UID/GID mapping, and
resource ceilings before that environment is marked qualified.

Kubernetes, cloud object storage, remote agents, and scheduler-backed execution
remain separate work. Worker-loss recovery is also outside this OCI runtime
qualification and must be verified independently.
