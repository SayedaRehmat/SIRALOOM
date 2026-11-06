# Universal Toolchain and Execution Architecture Audit

**Audit date:** 2026-11-06  
**Audited ref:** `main`  
**Audited commit:** `840a4487cc7e61111a1347d321fdddd402679496`  
**Scope:** repository architecture and deployment contracts; this is not a clinical validation statement.

## Executive finding

SIRALOOM already has a substantial, reproducible **BCFtools-specific execution system**. It is not yet a universal, laboratory-portable tool execution platform. The next work must generalize the execution contract without weakening or replacing the qualified BCFtools implementation.

The current mainline CI and BCFtools source-profile qualification matrix both passed for the audited commit. Those checks qualify the tested Linux AMD64 software paths only; they do not establish portability to other CPU architectures, Kubernetes, HPC schedulers, offline sites, or clinical use.

## Evidence-based current-state inventory

| Capability | Current evidence on main | Assessment |
|---|---|---|
| Exact BCFtools/HTSlib versions and profile status | `configs/bioinformatics/toolchain-profiles.v1.json` | Implemented, BCFtools-specific |
| Explicit dependency locks and checksummed source builds | `configs/bioinformatics/profiles/*`, `scripts/build_bcftools_from_profile.sh` | Implemented for registered source profiles |
| Immutable per-analysis toolchain snapshot | migration `0061_analysis_toolchain_profiles.py`, analysis domain and API | Implemented for BCFtools profile identity |
| Queue routing and worker-side profile fencing | Celery configuration, `scripts/start_worker.sh`, analysis dispatch and worker tests | Implemented for BCFtools queues |
| Reanalysis inherits parent toolchain profile | reanalysis domain and regression tests | Implemented for BCFtools profile |
| Separate worker images for alternate source profiles | `docker-compose.production.yml` optional workers | Partially implemented |
| Separate default-version worker image | default `worker` uses `docker/backend.Dockerfile`; that image also contains BCFtools 1.25 | Not independently isolated |
| API image independent of native scientific tools | `docker/backend.Dockerfile` installs BCFtools; default API and worker use that image | Not implemented |
| Generic registry for VEP, aligners, callers, annotation tools, etc. | current registry and resolver model BCFtools/HTSlib | Not implemented |
| Generic execution contract independent of Celery/Docker | worker commands and queues are Celery/container-oriented | Not implemented |
| Multiple execution backends | laboratory installation guide requires Linux + Docker Compose | Not implemented as a qualified capability |
| Kubernetes, HPC/Slurm, offline installation qualification | no corresponding production execution adapters/qualification gates found in audited deployment path | Not demonstrated |
| Lab-specific custom toolchain onboarding | registered profiles are repository-controlled; resource qualification is a different domain | Not implemented as a complete governed tool onboarding flow |
| Cross-architecture qualification | current Dockerfiles explicitly require x86_64/Linux AMD64 | Explicitly not supported by current qualification |

## Important architectural distinction

The existing resource-governance system manages **data resources** such as reference packages, annotation datasets and external evidence providers. It is valuable and should be reused where appropriate, but a qualified data resource is not an executable toolchain.

Likewise, `toolchain_profiles.py` currently resolves BCFtools/HTSlib profiles. It must not be treated as a generic tool registry merely because its name contains “toolchain”.

## Critical gaps to close

### G1 — Separate application services from scientific execution

The API image currently installs BCFtools 1.25, and the default API/worker deployment uses a combined backend image. The default worker is therefore not isolated in the same manner as the alternate source-built profiles.

Target:
- A tool-neutral API image with no native scientific executable dependency.
- A distinct, immutable default BCFtools 1.25 worker image.
- Alternate version workers remain independently built and routed.
- API processes do not consume scientific execution queues.
- Migration/Beat/API responsibilities are explicit; no accidental embedded worker in an API service.

This change must be preceded by a repository-wide audit of every native executable invocation and the task boundary that owns it. Do not remove BCFtools from the API image until synchronous API dependencies have been migrated or explicitly justified.

### G2 — Generalize the executable profile contract

Introduce a versioned, tool-agnostic execution profile model. A profile should describe, at minimum:
- stable tool identifier and exact version;
- profile identifier and immutable image digest;
- source/build provenance and dependency lock or SBOM reference;
- platform/architecture constraints;
- executable entry points and capabilities;
- reference/data compatibility constraints where relevant;
- security/advisory review;
- qualification status, scope, evidence and expiry/review policy;
- queue/runner capability requirements;
- tenant/laboratory approval and activation state.

BCFtools should become the first adapter using this common contract. Preserve the existing BCFtools registry as a compatibility source during migration; do not perform a risky all-at-once schema replacement.

### G3 — Decouple workflow dispatch from one queue implementation

Define a stable execution request and result contract containing tenant/lab scope, analysis and stage identity, immutable profile snapshot, input artifact references/checksums, resource requirements, idempotency key, attempt, outputs and provenance.

Celery queues can remain the first execution adapter. The domain contract must not require every future executor to be Celery.

### G4 — Add laboratory-controlled profile onboarding and approval

A laboratory may register a custom image or tool build, but registration alone must not make it production eligible. Require immutable image identity, provenance, platform declaration, security review, qualification evidence and explicit organization approval. A lab's profile must be tenant-scoped and must not alter another lab's choices.

### G5 — Add deployment adapters and qualify them separately

Keep Docker Compose as the currently documented deployment path. Add adapters only with real installation and failure-recovery tests:
- Kubernetes;
- HPC scheduler (for example Slurm);
- offline/air-gapped installation and artifact transfer;
- additional CPU architectures only after native build/runtime qualification.

Do not label an adapter supported merely because its configuration file exists.

### G6 — Preserve reproducibility across upgrades

Every analysis must retain the immutable tool profile, image digest, dependency provenance, parameters, reference package identity and resource snapshots. Updating a lab's default profile must affect only new analyses. Reanalysis must explicitly choose whether to inherit the parent profile or use a newly approved profile, with the decision recorded.

## Implementation sequence

1. **Architecture contract and inventory** — this document records the current state and target boundaries.
2. **Executable invocation audit** — enumerate every native tool invocation, caller, process boundary, input/output contract and retry behaviour.
3. **Tool-neutral API + dedicated default worker** — separate API, worker, scheduler and migration responsibilities without changing analysis semantics.
4. **Generic execution profile contract** — introduce a generic schema/model and adapt BCFtools as the first implementation.
5. **Generic execution request/result contract** — retain Celery as adapter one; prove retries, idempotency, cancellation and durable artifact publication.
6. **Lab profile registration/approval** — add tenant-scoped custom profiles and qualification gates.
7. **Deployment adapters** — implement and qualify Kubernetes, HPC and offline modes independently.
8. **Multi-tool qualification** — onboard the next scientific executable only after its own reference tests, provenance and failure contracts exist.

## Non-regression and acceptance rules

- Do not modify or silently reclassify existing BCFtools profile statuses as part of generalization.
- Keep current BCFtools source checksums, explicit locks, source build verification, queue fencing, analysis snapshots and reanalysis inheritance.
- Keep the existing main CI and BCFtools profile matrix green.
- Add tests proving the API image does not contain or require scientific executables once G1 is implemented.
- Add tests proving each worker consumes only its assigned immutable profile and rejects/requeues mismatched work before claiming it.
- Add tenant-isolation tests for lab-owned profiles and execution artifacts.
- Verify failure/retry/redelivery does not duplicate scientific outputs or lose provenance.
- Record platform scope explicitly; Linux AMD64 qualification must never be represented as ARM64, HPC, Kubernetes or clinical qualification.
- No production profile may be activated solely because it builds successfully.

## Current decision

Proceed in small pull requests. The first code change after this audit should be the **native executable invocation inventory and service-boundary test suite**. Only after that inventory identifies all API-side BCFtools calls should the default API image be made tool-neutral. This sequencing avoids breaking existing scientific workflows while moving toward a genuinely universal execution architecture.
