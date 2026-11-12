# Scientific tool execution inventory

**Audit baseline:** PR #312 head `e18b4111157d11bb4b0baee5683f61cb74f9705a`, with ARM64 workflow run `42457501199` and full SIRALOOM CI run `42457501166`, inspected 2026-11-08.

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

The three independent source-built profiles are 1.24.1, 1.23.3 and 1.22.3/HTSlib 1.22.4. Their existing qualification is Linux AMD64. Native ARM64 workflow run `42457501199` passed source compilation, reference-backed normalization, multiallelic splitting, BGZF/CSI, shared-library checks, pinned base-image architecture checks, ARM64 worker-image builds, version attestation, non-root identity, in-image profile/queue resolution and container scientific smoke tests for all three exact version pairs. Their generated `linux-aarch64` build-environment locks were committed at the three profile paths listed in the registry; each lock has SHA-256 `34f859b1851551a1dc80fa4ce49f91be1430a8a3f9f43b9c1b3a082121594bcf`. The three registry records deliberately remain `CANDIDATE` and are not production-selectable pending review and additional routing/recovery qualification. The default 1.25 profile is a fourth active profile and uses a different package-based build path; it is not covered by this source-build ARM64 matrix.

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
- `backend/app/adapters/annotation/vep.py` retains VEP-specific scientific argument construction, cache/assembly verification and response validation. When a persistent execution service is configured, it constructs `ToolIdentity`/`ToolExecutionRequest` and calls the common persistent executor; a legacy direct-subprocess fallback still exists unless the workflow sets `persistent_execution_required`. VEP is therefore partially integrated, not yet enforced through the common executor in every production mode.
- BCFtools scientific call sites in `backend/app/domain/vcf_tools.py` still invoke BCFtools-specific subprocesses; they have not yet been migrated through a BCFtools adapter using the common executor.

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
- The three independent source-built BCFtools profiles have Linux AMD64 source/lock/runtime/software qualification.
- Native ARM64 workflow run `42457501199` completed successfully for all three source-built version pairs on `ubuntu-24.04-arm`. Each job passed exact source archive SHA-256 verification/build, reference-backed normalization, multiallelic splitting, BGZF/CSI indexing, shared-library resolution, pinned builder/runtime image architecture inspection, ARM64 OCI image build, executable/library version attestation, non-root UID, profile/queue resolution inside the image, and a container-level scientific normalization/indexing smoke test.
- The ARM64 build environment pins `sysroot_linux-aarch64=2.28`. This corrected the earlier GLIBC_2.38 ABI mismatch. The initial `bcftools faidx` test-fixture defect was corrected by writing a valid FASTA `.fai` directly; the subsequent full ARM64 matrix passed.
- The three generated ARM64 explicit build-environment locks are now committed. Their identical content is expected because they lock the shared compiler/build environment; BCFtools and HTSlib source versions and SHA-256 identities remain independently pinned in each profile registry record and build invocation.
- Full SIRALOOM CI run `42457501166` passed frontend, backend, PostgreSQL/Celery integration and real Docker/Podman container qualification. ARM64 profile lock-generation run `42457501092` passed.
- The separate x86_64 source-profile matrix run `42457501082` was still in progress at the last status check: 1.24.1 and 1.23.3 jobs had passed; 1.22.3/1.22.4 remained in progress. Do not claim the entire x86_64 matrix has passed until that run completes.
- All three ARM64 records remain `CANDIDATE`, intentionally non-production-selectable. Their source-build and image evidence is green, but production promotion still requires the broader cross-version dispatch, worker isolation, retries/redelivery, reanalysis inheritance and recovery gates.
- The default BCFtools 1.25 package-based profile is not covered by this source-build ARM64 matrix and needs a separate native ARM64 package-lock/image/scientific qualification.
- Direct native-process execution, rootless Podman, Kubernetes, cloud scheduling and remote-agent execution remain separate qualification targets.

## Promotion rule

A profile remains unavailable for production until its own platform-specific lock, source/package integrity, build, executable/library attestation, scientific regression, runtime-image qualification, queue routing and failure/retry behavior have passed. ARM64 work must not modify or replace existing x86_64 locks or status records.
