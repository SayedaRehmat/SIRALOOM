# Tool-neutral scientific tool profiles

## Purpose

SIRALOOM has a shared execution request/result/provenance contract, but its original profile registry and analysis routing are BCFtools/HTSlib-specific. This registry introduces a tool-neutral description layer without conflating tool-specific installation, ABI, resource, or scientific qualification rules.

Registry: `configs/bioinformatics/scientific-tool-profiles.v1.json`

Resolver: `backend/app/domain/scientific_tool_profiles.py`

## Profile identity

Every profile declares:

- `tool_id` and exact tool `version`.
- Target `platform` and CPU `architecture`.
- Independent `execution_methods` (local process, OCI container, or remote agent).
- Tool-specific dependencies and their version/ABI relationships.
- Executable identity attestation arguments, expected version text, and executable SHA-256 policy.
- Resource requirements, including reference/cache mounts and network policy.
- Installation contract, dependency lock/build inputs, and cache manifest where applicable.
- Routing identity and explicit qualification state/evidence scope.

The registry is descriptive and validates structural consistency. It does not manufacture executable digests, locks, software qualification, clinical validation, or laboratory approval.

## Current registry contents

### BCFtools

The registry mirrors the existing BCFtools/HTSlib records, preserving the original registry as the detailed source for source archive hashes, security review, exact build-lock paths, and queue assignments.

- BCFtools 1.25 / HTSlib 1.25, package-based Linux AMD64.
- BCFtools 1.24.1 / HTSlib 1.24.1, source-built Linux AMD64 and ARM64 candidate.
- BCFtools 1.23.3 / HTSlib 1.23.3, source-built Linux AMD64 and ARM64 candidate.
- BCFtools 1.22.3 / HTSlib 1.22.4, source-built Linux AMD64 and ARM64 candidate.
- BCFtools 1.21.3 / HTSlib 1.21.3 remains compatibility-blocked.
- BCFtools 1.19 / HTSlib 1.19 remains quarantined legacy.

The existing BCFtools resolver now cross-checks the generic profile ID, tool ID, platform, version and HTSlib pair before allowing selection. Existing BCFtools security review and lock verification remain in force.

### Ensembl VEP

The registry contains an independent `vep-115-linux-amd64` candidate for Ensembl VEP 115.2, with cache release 115 and GRCh37/GRCh38 assembly-scoped cache requirements.

VEP does not inherit BCFtools' HTSlib pair, conda lock, build script, executable name, or worker queue. Its dependencies are explicitly identified as Perl runtime, Ensembl VEP Perl modules, version-matched cache, and optional assembly-matched FASTA.

The profile remains `CANDIDATE`: a reproducible Perl/module environment lock and complete VEP image qualification have not been produced. The VEP adapter now takes its qualification status from this registry rather than hardcoding `SOFTWARE_QUALIFIED`. A candidate VEP profile therefore fails the common `ToolIdentity.validate()` production execution gate. Once a VEP profile ID is configured, the adapter also refuses to fall back to its legacy unregistered local-process path when no persistent execution service is assigned.

## Resolution policy

`resolve_scientific_tool_profile()` fails closed on:

- Unknown or duplicate profile IDs.
- Invalid tool/platform/architecture identity.
- Unsupported execution method.
- Missing execution, resource, installation, or executable identity declarations.
- Candidate, blocked, quarantined, or retired profiles when production qualification is required.
- Missing dependency lock for a qualified profile when a lock is declared.

The generic resolver does not replace the BCFtools-specific compatibility/security checks; the BCFtools resolver cross-checks both registries. VEP uses its own tool ID and profile version.

## Execution architecture

```text
Scientific tool
  -> exact tool/version profile
  -> platform/architecture profile
  -> tool-specific dependency and resource contract
  -> approved executor (local process / OCI / remote agent)
  -> executable + resource attestation
  -> scientific operation validation
  -> immutable execution provenance
```

The executor remains tool-neutral. Scientific adapters remain tool-specific: BCFtools owns VCF normalization/index semantics; VEP owns Ensembl cache, assembly, plugin and transcript-consequence semantics.

## Qualification still required

1. Complete latest CI for PR #312 and the VEP cache-mount fix.
2. Complete all x86_64 source-profile matrix jobs and retain ARM64 source/image evidence.
3. Build and pin VEP's Perl/module environment independently for each target architecture.
4. Qualify VEP cache release × assembly combinations and plugin dependencies.
5. Run real VEP annotation fixtures inside the OCI image for GRCh37 and GRCh38, with and without optional FASTA/HGVS.
6. Verify container resource mounts are read-only and cache-manifest/tree digests match the bytes visible inside the container.
7. Exercise failure injection, retry/redelivery, worker loss and durable provenance for VEP.
8. Promote a VEP profile only after independent software/image qualification and review.

A passing unit test or successful image build is not clinical or laboratory validation. No VEP profile is production-qualified by this change.
