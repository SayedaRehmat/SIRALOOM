# Universal scientific tool execution contract

**Status:** foundational implementation; not yet integrated into production BCFtools/VEP workflow calls.  
**Dependency:** service boundary in PR #300 (stacked on durable artifact validation PR #297).  
**Qualification scope:** contract unit tests and local process executor only; no clinical/workflow qualification.

## Purpose

BCFtools and VEP currently have different execution paths: BCFtools normalization and splitting invoke subprocesses in the VCF domain layer, while VEP is implemented as a scientific resource provider with its own binary/cache attestation and process lifecycle.

A resource-provider contract is not a generic executable contract. This module introduces a separate, tool-neutral boundary:

- `ToolIdentity`: exact tool/version/profile, executable path and SHA-256, platform, software qualification state, version attestation and supported operations.
- `ToolExecutionRequest`: execution/tenant/workflow identity, operation, argv, workspace, input/output artifacts, resource bindings, timeout and controlled environment.
- `ToolExecutionProvenance`: tool/profile identity, executable digest, input/output digests, resource versions/digests, argv, exit status and timestamps.
- `ToolExecutor`: adapter-independent execution interface.
- `LocalProcessToolExecutor`: local process implementation using argument arrays (never a shell), executable digest verification, runtime version attestation, bounded process-group lifetime, workspace-scoped outputs and content-digest provenance.

Tool-specific adapters remain responsible for constructing scientifically correct arguments and validating semantic outputs. The executor does not decide what a VCF normalization, annotation, alignment or calling operation means.

## Safety properties

- Only profiles marked `SOFTWARE_QUALIFIED` can be executed.
- Executable paths must be absolute, regular non-symlink files whose SHA-256 matches the profile.
- The executable's runtime version output must match the approved profile.
- The operation must be declared by that profile.
- Input files are re-hashed before execution.
- Output paths must be inside the execution workspace; symlink outputs are rejected.
- No shell is invoked; arguments are passed as an argv array.
- Execution time is bounded; timeout kills the complete process group.
- Process output is spooled to disk to avoid unbounded pipe buffering; complete stdout/stderr streams are hashed while only a bounded diagnostic tail is returned.
- Protected process environment variables cannot be overridden by request data.
- A non-zero exit or missing declared output is never returned as success.
- Provenance binds the organization/workflow/execution identifiers to exact tool and resource identities and artifact hashes.

This contract is an execution boundary, not a tenant authorization system. The scheduler/agent must independently authorize organization, case, artifact and profile access before it creates a request. Resource digests in the request are identity assertions; the resource staging/verification layer must verify the actual mounted resource bytes before execution.

## Migration sequence

1. Introduce the shared contract and local executor (this change).
2. Add a BCFtools adapter that maps registered BCFtools profiles to `ToolIdentity` and routes normalization/splitting through the executor without changing scientific arguments or output semantics.
3. Add a VEP adapter that maps its existing binary/cache contract to the same interface, preserving cache-manifest verification, assembly policy, transcript options and output validation.
4. Persist the resulting tool execution provenance with the existing workflow step/dispatch records and immutable analysis toolchain snapshot.
5. Add container executor and remote laboratory-agent transport behind the same `ToolExecutor` protocol.
6. Add profile registry resolution, image/build recipe identity, resource compatibility checks and lab approval.

## Explicit limitations

This change does not yet:
- replace existing BCFtools or VEP subprocess call sites;
- establish a production registry for all scientific tools;
- create or sign container images, SBOMs or attestations;
- provide cgroups/container isolation, CPU/memory quotas or network policy;
- implement a remote agent, Kubernetes or Slurm executor;
- provide durable execution records in the database;
- authorize cross-tenant access;
- establish scientific workflow or clinical qualification.

Do not advertise universal execution or independent lab execution as complete until the adapters, durable records, isolation and remote agent are implemented and qualified.


## Runtime and resource attestation hardening

The executor contract now additionally enforces:

- `ToolIdentity.platform` must equal the actual worker platform/architecture (`linux-64`, `linux-aarch64`, `osx-64`, `osx-arm64`, or `win-64` as supported). A mismatched profile is rejected before process start.
- The tool profile owns the runtime `PATH` and approved environment variables. Request data cannot replace protected variables or override profile-pinned values. `HOME` and temporary directories are scoped to the execution workspace.
- Every `ScientificResourceBinding` must name an absolute local path. The executor hashes the actual file bytes or, for a directory, a deterministic sorted manifest of every regular file's relative path, byte size and SHA-256. Symlink entries, special files, empty resource directories and digest mismatches are rejected.
- `ToolExecutionProvenance` records the actual platform, optional declared runtime image digest, and a digest of the effective execution environment. A declared image digest is format-validated and recorded; the executor does not itself attest the container runtime's image identity.
- Runtime failures after process start (timeout, non-zero exit, missing outputs) carry execution provenance, including exit code, timing, stream hashes and any produced output hashes. Partial output hashes are diagnostic only and are never a successful artifact publication.

For VEP, the VEP adapter must retain its release-specific cache-manifest verification: the cache manifest is verified against every file in the cache tree and against the pinned cache release/species/assembly. The shared executor's resource binding can verify the manifest file itself and FASTA/index bytes; it must not claim that hashing the manifest alone verifies the cache tree.

## A2-specific integration constraints

The VEP adapter must construct `ToolIdentity` from the organization-approved VEP execution contract, including the exact executable digest, expected version output, worker platform, approved Perl/module search path and (for container execution) runtime image digest. It must construct input/output/resource bindings from staged, verified artifacts. All VEP process invocations—including version and offline-cache preflight—must use the shared executor; no direct `subprocess` fallback remains.

The current executor does not impose per-process CPU, memory, PID or scratch quotas. Those limits must be enforced by the worker container/cgroup and selected resource class, then measured in the WES/WGS batch qualification. `runtime_image_digest` is a recorded declaration until the worker/container launch layer supplies independent image attestation.
