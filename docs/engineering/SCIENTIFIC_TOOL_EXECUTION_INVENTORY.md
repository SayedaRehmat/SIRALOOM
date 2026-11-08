# Scientific tool execution inventory

**Audit baseline:** PR #310 head `e3738228b67995bf085102f5bf0e5e592a6cf3c1`, inspected 2026-11-08.

## BCFtools profile inventory

The registry is `configs/bioinformatics/toolchain-profiles.v1.json`.

| Registry profile | BCFtools | HTSlib | Platform | Status | Interpretation |
|---|---:|---:|---|---|---|
| `bcftools-1.25-htslib-1.25-linux-64` | 1.25 | 1.25 | linux-64 | SOFTWARE_QUALIFIED | Default packaged profile |
| `bcftools-1.24.1-htslib-1.24.1-linux-64-source` | 1.24.1 | 1.24.1 | linux-64 | SOFTWARE_QUALIFIED | Independent source-built profile |
| `bcftools-1.23.3-htslib-1.23.3-linux-64-source` | 1.23.3 | 1.23.3 | linux-64 | SOFTWARE_QUALIFIED | Independent source-built profile |
| `bcftools-1.22.3-htslib-1.22.4-linux-64-source` | 1.22.3 | 1.22.4 | linux-64 | SOFTWARE_QUALIFIED | Independent source-built profile; patched HTSlib pair is intentional |
| `bcftools-1.21.3-htslib-1.21.3-linux-64-source` | 1.21.3 | 1.21.3 | linux-64 | BLOCKED_COMPATIBILITY | VCF 4.5 FORMAT/LEN reference-block regression remains unresolved |
| `bcftools-1.19-htslib-1.19-linux-64-legacy` | 1.19 | 1.19 | linux-64 | QUARANTINED_LEGACY | Historical compatibility only; not production-selectable |

The three independent source-built profiles are 1.24.1, 1.23.3 and 1.22.3/HTSlib 1.22.4. Their existing qualification is Linux AMD64 only. The default 1.25 profile is a fourth active profile and uses a different package-based build path. None of these records establishes ARM64 qualification. Three separate ARM64 candidate records now exist with distinct profile IDs, platform locks, and `.arm64` worker queues. They remain `CANDIDATE` and are not production-selectable.

## VEP and other scientific components

| Component | Current implementation evidence | Classification | Required distinction |
|---|---|---|---|
| VEP | `backend/app/adapters/annotation/vep.py` | Executable annotation provider | Has its own Perl/runtime, binary, cache, FASTA, assembly, plugin and cache-manifest requirements; no VEP version × architecture profile registry was found in the BCFtools registry |
| GeneBe | `backend/app/adapters/annotation/genebe.py` | External annotation/provider integration | Treat as a provider/API integration unless a local executable is explicitly introduced |
| ClinVar | `backend/app/adapters/evidence/clinvar.py` | Evidence/data provider | Version and checksum data; not a native binary image profile |
| gnomAD | `backend/app/adapters/population/gnomad.py` | Population data/API provider | Version and checksum datasets/responses; not a native binary image profile |
| HPOA/HPO OBO | `backend/app/adapters/phenotype/hpoa.py`, `hpo_obo.py` | Phenotype data adapters | Version and checksum datasets; not executable binaries |
| ClinGen | `backend/app/adapters/clingen/` | Evidence/rule/provider integrations | Version rule/data provenance independently; not BCFtools-style binary profiles |
| VCF utilities | `backend/app/domain/vcf_tools.py` | BCFtools-specific scientific executable call sites | Migrate through a BCFtools adapter without changing scientific semantics |

This inventory distinguishes executable tools from APIs and datasets. ARM64 binary builds are relevant to executable tools. Data resources require content identity, versioning and integrity verification; they do not automatically need separate architecture builds.

## Shared execution architecture: implemented versus integrated

- `backend/app/domain/tool_execution.py` defines a tool-neutral identity, request, provenance and local-process executor.
- `backend/app/domain/container_tool_execution.py` implements a Linux Docker/Podman executor for immutable OCI images.
- `backend/app/domain/execution_environments.py` defines environment contracts and compatibility checks.
- `backend/app/domain/toolchain_profiles.py` remains BCFtools/HTSlib-specific: it requires BCFtools and HTSlib versions and routes to BCFtools queues.
- `backend/app/adapters/annotation/vep.py` retains VEP-specific execution and resource logic. The universal execution design document states that the common executor is not yet integrated into production BCFtools/VEP call sites.

The universal executor is therefore a foundation, not evidence that all tools already use it. VEP must not be routed through BCFtools profile resolution.

## Independent execution dimensions

1. Tool identity: BCFtools, VEP or another executable.
2. Tool release profile: exact version and compatible dependency/runtime set.
3. Scientific resource profile: assembly, FASTA/index, VEP cache, plugins and dataset checksums.
4. Architecture/build profile: linux-64 versus linux-aarch64, with independently resolved locks and verified artifacts.
5. Execution environment: native process, Docker, Podman, Kubernetes job, cloud VM or remote lab agent.
6. Qualification evidence: exact combinations tested; never infer one dimension's qualification from another.

The same compatible OCI image can run under Docker and Podman. Kubernetes also consumes OCI images but needs separate scheduler, volume, identity, resource-limit, retry and lifecycle qualification. An x86_64 executable is not an ARM64 executable.

## Qualification boundary

- PR #310 qualified Docker and Podman on Linux x86_64 using the same BCFtools 1.25 worker image digest.
- The three source-built BCFtools profiles have Linux AMD64 source/lock/runtime/software qualification.
- Three ARM64 candidate profiles are registered for the independent source-built version pairs. A native `ubuntu-24.04-arm` workflow resolves their own explicit locks, builds each exact source pair, runs reference-backed normalization/CSI checks, inspects the pinned builder/runtime image digests, and attempts a non-root ARM64 OCI image qualification.
- The ARM64 candidates remain non-production until all matrix jobs and review gates pass. The default BCFtools 1.25 profile is not yet covered by this source-profile matrix.
- Direct Linux, rootless Podman, Kubernetes, cloud and remote-agent qualification remain separate.

## Promotion rule

A profile remains unavailable for production until its own platform-specific lock, source/package integrity, build, executable/library attestation, scientific regression, runtime-image qualification, queue routing and failure/retry behavior have passed. ARM64 work must not modify or replace existing x86_64 locks or status records.
