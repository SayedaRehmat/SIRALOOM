# Persistent common-executor integration

Status: implementation in PR #307, stacked on PR #306. This document describes the opt-in contract and does not claim that any physical laboratory host is qualified.

## Enabling persistence for an analysis

An analysis must be assigned an existing, tenant-authorized ExecutionEnvironmentRegistration and explicitly require the common executor:

```json
{
  "execution_environment_registration_id": "<registered-environment-uuid>",
  "require_persistent_tool_execution": true
}
```

The workflow does not create or qualify an environment automatically. If the mandatory flag is true and the registration is missing, belongs to another organization, or is not ENVIRONMENT_QUALIFIED, the stage fails closed before launching the scientific executable.

## Environment profile requirements

The immutable registered profile must:

- Belong to the analysis organization (or be explicitly SIRALOOM-managed).
- Match the executing worker's platform and runtime image digest.
- Be in ENVIRONMENT_QUALIFIED status.
- Explicitly allowlist every tool profile that can execute.
- Include an approved executable digest for every allowlisted profile in tool_executable_sha256.

Example shape of the relevant snapshot fields:

```json
{
  "platform": "linux-64",
  "runtime_image_digest": null,
  "qualification_status": "ENVIRONMENT_QUALIFIED",
  "supported_tool_profile_ids": [
    "bcftools-1.25-htslib-1.25-linux-64",
    "vep-115-linux-amd64"
  ],
  "tool_executable_sha256": {
    "bcftools-1.25-htslib-1.25-linux-64": "<sha256-of-approved-bcftools-binary>",
    "vep-115-linux-amd64": "<sha256-of-approved-vep-binary>"
  }
}
```

For container environments, runtime_image_digest must be the pinned OCI digest and must match the ToolIdentity. For host execution it is null; the executable digest allowlist is still mandatory.

The VEP resource execution contract must also declare toolchain.execution_profile_id. Its value must match the VEP profile ID in the environment allowlist. VEP's cache manifest and optional reference FASTA are verified as executor resource bindings; VEP's existing cache-manifest verifier continues to verify every cache file against its manifest.

## Lifecycle

For each common-executor invocation:

1. Validate ToolIdentity, request, inputs, output paths, environment registration and tenant ownership.
2. Insert or resolve the idempotent PENDING ToolExecutionRecord and commit it.
3. Claim a worker lease with a unique fencing token and commit RUNNING.
4. Execute through LocalProcessToolExecutor without a shell.
5. Verify output checksums and publish declared retained outputs.
6. Commit SUCCEEDED provenance, or record FAILED / INTERRUPTED with the attempt evidence.

The executor request fingerprint replaces worker-local scratch/input/output paths with logical placeholders. A retry that uses a different temporary directory therefore retains the same request identity when the scientific inputs, arguments and output names are unchanged.

## Current adapter coverage

### BCFtools

normalize_vcf_with_bcftools routes GVCF preparation, reference-aware normalization, sorting, source-only compression, CSI indexing, index statistics and per-contig index-concordance queries through the persistent executor when the workflow supplies a registered environment.

The final normalized VCF and CSI artifacts carry the execution record IDs in their artifact metadata. Intermediate command outputs are retained in the execution ledger as checksummed EPHEMERAL_INTERMEDIATE outputs; they are not falsely represented as durable artifacts.

### Ensembl VEP

VEPProvider routes the annotation invocation through the same executor when a persistent execution service is assigned. The raw VEP JSON output is published as a TOOL_EXECUTION_OUTPUT artifact and the workflow response checkpoint records the execution record ID. Existing response normalization and transcript-selection behavior remain in the VEP adapter.

### Legacy behavior

Analyses without an environment registration continue to use the existing legacy execution path unless require_persistent_tool_execution is true. This compatibility mode is transitional and is not equivalent to persistent, environment-qualified execution.

## Qualification not yet claimed

PR #307's tests exercise the persistence bridge with a fake executor and assert adapter request construction. They do not establish a real lab environment's executable digests, OCI digest, cache availability, scheduler behavior, resource limits or clinical suitability. The full production gate still requires:

- An authenticated environment registration/assignment API and audit trail.
- Real host/container registration and independent qualification evidence.
- Real BCFtools and VEP known-answer execution with a qualified registration.
- Durable object-store byte re-verification and recovery of published artifacts after worker loss.
- Remote agent enrollment, signed heartbeat, scheduler/resource leases and capacity enforcement before remote execution is enabled.
