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
