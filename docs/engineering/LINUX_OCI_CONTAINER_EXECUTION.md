# Linux OCI container execution contract

## Scope

The common ToolExecutionRequest / ToolExecutionResult /
ToolExecutionProvenance contract is retained. EnvironmentAwareToolExecutor
selects the local-process executor for qualified HOST environments and the
Linux OCI adapter for qualified CONTAINER environments. Remote agents and
unsupported schedulers fail closed; they never fall back to host execution.

## Immutable image identity

A container environment must register both:

- runtime_image_digest: sha256:<64 lowercase hex>
- runtime_image_reference: registry/repository@sha256:<same digest>

A mutable tag is not accepted. Docker/Podman must already have the exact
repository digest locally; execution uses --pull=never. The adapter verifies
the runtime version, the inspected repository digest, the in-image executable
SHA-256, and the tool's version output before running the requested operation.

## Isolation and resource enforcement

- Workspace is the only writable bind mount and is mounted at /workspace.
- Each input and each scientific resource is mounted separately read-only.
- The container root filesystem is read-only; /tmp, /inputs, and
  /resources are bounded tmpfs mount points.
- Network is disabled. Environments declaring allowlisted egress are rejected
  until a separately qualified network enforcement implementation exists.
- CPU, memory, swap, PID count, non-root UID/GID, Linux capabilities, and
  privilege escalation are constrained explicitly.
- Request timeout kills the named container and then terminates the runtime
  client process group.
- Output files are checksummed after the container exits; missing outputs or
  non-zero exits cannot return a successful result.

## Qualification boundary

This adapter is an execution implementation, not evidence that a host has
passed production qualification. Qualification still needs integration tests
against supported Docker and Podman versions on Linux, including image digest
mismatch, unavailable runtime, missing mounts, read-only enforcement, resource
limit enforcement, timeout cleanup, output integrity, and worker-loss recovery.
Kubernetes, cloud object storage, remote agents, and scheduler-backed execution
remain separate work and are not implied by this adapter.
