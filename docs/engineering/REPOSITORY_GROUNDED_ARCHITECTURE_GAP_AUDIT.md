# Repository-Grounded Architecture Gap Audit

**Audit date:** 2026-11-07  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Audited production baseline:** `main` at `226dd645d5ac4047e3478fd67b6b550af9633b55`  
**Related architecture PR:** #295  
**Scope:** registries, database models, germline workflow contracts, executable invocation boundaries, deployment/environment support, missing integration and implementation order.  
**Status semantics:** “Implemented” means a corresponding artifact exists on the audited ref; it does not imply end-to-end qualification. “Partial” means some of the contract exists but the runtime or operational integration is incomplete.

## 1. Executive assessment

SIRALOOM is not a BCFtools-only scientific application. The repository contains a real germline interpretation workflow with multiple scientific providers, a governed resource lifecycle, analysis resource profiles, a BCFtools/HTSlib software-profile system, a local Ensembl VEP executable provider, ACMG/ClinGen interpretation, phenotype/pedigree support, human review and reporting.

The main architectural gap is **integration across these existing systems**:

- The executable profile registry is BCFtools/HTSlib-specific.
- The provider registry describes scientific adapters and resource capabilities, not all native executables.
- The resource registry governs datasets, reference packages, evidence sources, qualification, lab approval and organization bindings; it is not a host/environment registry.
- Workflow-stage and analysis-resource profiles describe scientific resource needs, but the live orchestration still contains direct BCFtools and VEP paths.
- `ToolRun` and `ResourceExecutionRecord` capture different kinds of provenance; neither is yet a complete, unified record for every executable process.
- The laboratory deployment contract describes required services/storage and policy, but it does not provision a remote execution agent or qualify multiple execution backends.
- The common tool execution contract exists in open PR #301, not in `main`; it is not yet wired into production BCFtools or VEP paths.
- PR #300 proposes the API/scientific-worker image boundary, but is open and stacked on PR #297. PR #297 is open and addresses synchronous API-side validation. Do not treat either as deployed.

**Conclusion:** Do not create a second resource registry, a second VEP provider, or a generic “tool list” disconnected from workflow execution. The next architecture step is to connect the existing contracts and models through a single versioned execution-profile and execution-request boundary, then add lab execution agents as an execution backend.

## 2. Existing registries and contracts: inventory and responsibility

| Existing component | Repository location | What it governs | Assessment / boundary |
|---|---|---|---|
| BCFtools/HTSlib toolchain profile registry | `configs/bioinformatics/toolchain-profiles.v1.json`; `backend/app/domain/toolchain_profiles.py` | Exact BCFtools/HTSlib pair, profile status, Linux platform, lock/environment files, source archive checksums, security review, worker queue and production eligibility | Implemented and materially qualified for registered Linux AMD64 profiles. **Not** a generic registry for VEP, callers, aligners or arbitrary tools. |
| Scientific provider registry | `backend/app/domain/provider_registry.py` | Explicit provider ID/version → factory + capability descriptor | Implemented for the adapters listed in §3. Provider is not synonymous with executable: API providers may be remote, local-data or local-process adapters. |
| Resource capability catalogue | `backend/app/domain/resource_capabilities.py` | Scientific capabilities, provider compatibility, deployment policy and resource-type vocabulary | Implemented. Capability declarations do not themselves qualify or authorize a resource. |
| Workflow-stage resource contracts | `backend/app/domain/workflow_resource_contracts.py` | Stage order, inputs, outputs, required/optional resource classes, continuation and review expectations | Implemented as declarative contracts. They are not, by themselves, the complete workflow engine or a scheduler DAG. |
| Analysis resource profiles | `backend/app/domain/analysis_resource_profiles.py` | WES/WGS + GRCh37/GRCh38 resource requirements and preferred providers | Implemented (profile version 2 in the inspected definitions). They describe resource capability envelopes, not executable software environments. |
| Resource source/execution contracts | `backend/app/domain/resource_source_contract.py` | Publisher/source identity, release, license/checksum status, provider/version, access method, endpoint/location/dataset and execution scope/toolchain metadata | Implemented. This is a **resource/provider execution contract**, not the common OS process contract. |
| Resource discovery/lifecycle/staging/qualification | `resource_discovery.py`, `resource_lifecycle.py`, `resource_staging.py`, `resource_qualification.py` | Discovery, staging, integrity checks, technical qualification and lifecycle transitions | Implemented in multiple modules. Must be kept distinct from tool-image/software qualification and from lab approval. |
| Resource execution resolver/plan | `resource_execution.py`, `resource_execution_plan.py`, `resource_profile_resolver.py` | Resolve a qualified resource contract; enforce organization bindings; choose compatible provider/resource candidates; create deterministic analysis plans | Implemented. It resolves **scientific resources/providers**, not a general host/runner or native tool profile. |
| Deployment policy/profile | `resource_deployment.py`; DB `ResourceDeploymentProfile` | Trial-public versus laboratory resource-selection policy | Implemented. It is a deployment *policy type*, not a machine/cluster environment description. |
| Laboratory deployment contract | `laboratory_deployment.py` | Required API/worker/PostgreSQL/Redis services, durable artifacts, temporary workspace, TLS and required scientific capabilities | Implemented as a contract/hash. It explicitly does not provision infrastructure. |
| Storage profiles/capacity | `storage_profiles.py`, `storage_capacity.py`, `resource_capacity.py`, artifact-store adapters | Organization artifact-storage routing, storage preflight and disk capacity | Implemented in parts. Not a full compute/scheduler environment registry. |
| Reference package contract | `reference_package.py`, `reference.py`, resource records | FASTA/FAI/contig identity, checksums and sequence access | Implemented. Reference package is a governed scientific resource, not a generic software profile. |

### Important distinction

The current system already has several registries. They must remain separate by responsibility:

1. **Provider registry** = how a scientific source/provider is called and interpreted.
2. **Resource registry** = which data/reference/evidence release exists, its identity, license, integrity, qualification and lab approval.
3. **Tool profile registry** = which exact executable build/image is allowed to run.
4. **Environment registry** (not yet implemented as a complete first-class contract) = where/how that tool profile can run: host, architecture, container runtime, scheduler, CPU/RAM/GPU, storage, network and security constraints.
5. **Workflow registry** = what stages exist, their dependency graph, inputs/outputs and capability requirements.

Do not collapse these into one table. Link them by immutable IDs and compatibility constraints.

## 3. Scientific provider inventory (what the repository actually registers)

The built-in provider registry currently registers:

| Provider | Capability | Execution character / note |
|---|---|---|
| Ensembl VEP | Annotation | Local executable + offline cache provider; governed binary/cache contract exists in `backend/app/adapters/annotation/vep.py`. |
| GeneBe | Annotation, population frequency | Trial/evaluation-only by deployment policy; not a laboratory provider. |
| gnomAD GraphQL | Population frequency | Remote API provider; registered as trial-only in `TRIAL_ONLY_PROVIDERS`. |
| Local gnomAD Tabix | Population frequency | Local indexed dataset provider. |
| ClinGen Variant Pathogenicity | Clinical variant assertion | Scientific evidence provider. |
| ClinGen Gene-Disease Validity | Gene-disease validity | Scientific evidence provider. |
| ClinGen CSpec | ACMG specification | Specification/evidence provider. |
| HPO OBO | Phenotype ontology | Local ontology provider. |
| HPOA | Disease-phenotype association | Association dataset provider. |
| NCBI ClinVar | Clinical variant evidence | Specialized implementation path; explicitly listed in `SPECIALIZED_PROVIDER_IMPLEMENTATIONS`, not an ordinary registry factory entry in the same way as the others. |

Source: `backend/app/domain/provider_registry.py::register_builtin_providers`.

The resource capability vocabulary also reserves classes for computational prediction, splicing, literature, functional evidence, family segregation, internal lab evidence, disease ontology, gene panels, dosage sensitivity and secondary populations. These vocabulary entries are **not proof that a corresponding production provider is implemented**. The registry intentionally does not fabricate implementations for catalog entries.

### Current profile examples

The inspected analysis profiles include:

- `WES_GRCh38_STANDARD`
- `WGS_GRCh38_STANDARD`
- `WES_GRCh37_STANDARD`

They require a reference package, annotation engine, population resource and ACMG rule specification. Secondary population, ClinVar, OMIM, HPO/HPOA, CADD/REVEL/dbNSFP/AlphaMissense, SpliceAI, literature, internal lab evidence and ClinGen assertions are represented as optional resource requirements in the common profile definition. Optional in a profile means the workflow can represent a limitation/gap; it does **not** mean those providers are already installed, qualified or available in every lab.

## 4. Database model inventory and what each model is for

The relevant SQLAlchemy models are in `backend/app/infrastructure/db/models.py`.

### 4.1 Tenant and deployment

- `Organization`, `User`, `OrganizationMembership`, `OrganizationEntitlement`: tenant and user membership/entitlement.
- `Case`, `CaseAccessGrant`: case ownership/access controls.
- `OrganizationStorageProfile`: organization storage configuration.
- `ResourceDeploymentProfile`: trial/laboratory resource-selection policy.
- `Installation`, `License`, `LicenseEntitlement`: installation/license-related state.

These are meaningful tenant foundations. They do not alone prove isolation across every storage backend, execution worker, cache, secret or remote host. Those require cross-tenant integration tests at each boundary.

### 4.2 Executable/tool and workflow provenance

- `Analysis`: analysis identity and persisted BCFtools profile/version/queue/snapshot fields.
- `AnalysisDispatch`: durable analysis dispatch lifecycle.
- `ToolRun`: generic-looking tool run row with analysis ID, tool name/version, optional container digest, command fingerprint, parameters, status, start/end, exit code and stdout/stderr artifact IDs.
- `WorkflowStep`, `AnalysisPartition`: workflow-stage and partition execution state.
- `AnalysisResourceSnapshot`: analysis-pinned resource identity/version/checksum/build/metadata.
- `ResourceExecutionRecord`: immutable resource-provider execution snapshot with stage, attempt, batch, resource and qualification IDs, provider/version, access method, endpoint/location/dataset, contract hash/JSON, request fingerprint, response digest, status and errors.

**Gap:** `ToolRun` is not yet shown as the universal execution ledger for every process launched by BCFtools, VEP or future tools. `ResourceExecutionRecord` is specifically resource/provider provenance and should not be overloaded as the executable process record. The new common executor provenance in PR #301 is returned in memory; its durable mapping into `ToolRun` (and its relationship to `ResourceExecutionRecord`) remains to be implemented.

### 4.3 Resource governance

- `Resource`: resource release identity, provider/type/version/build/access/license/checksum/location/status/metadata and optional organization scope.
- `ResourceDiscovery`: publisher, source/artifact URLs, release identity, access/license/checksum evidence and discovery status.
- `ResourceStaging`: source/destination, storage backend, expected/observed checksum/size, attempt and staging status.
- `ResourceQualification`: qualification version/status/checks and actor/time.
- `ResourceApproval`: organization-specific approval of a qualified resource.
- `ResourceApprovalAction`: append-only approval decision history.
- `OrganizationResourceBinding`: currently adopted resource release for one lab.
- `AnalysisResourceSnapshot`: immutable resource snapshot attached to an analysis.
- `ResourceExecutionRecord`: runtime use of the selected resource.

This is already a substantial resource-governance lifecycle. Do **not** rebuild it as a new resource registry. The likely extension is to add missing fields/contracts and ensure every stage uses the same pinned plan.

## 5. Canonical germline workflow map

The declarative stage contract in `backend/app/domain/workflow_resource_contracts.py` defines ten stages. The following table joins that contract to the currently identifiable implementation.

| Order / stage | Scientific purpose | Existing implementation | Executables/providers/resources | Gap or qualification boundary |
|---|---|---|---|---|
| 1. `validate_input` | VCF structure, semantics, supported scope, case/specimen constraints | `api/v1/artifacts.py`, `domain/ingestion.py`, strict VCF validators; durable worker validation is proposed in PR #297 | BCFtools `view` is currently invoked by API-side ingestion on `main`; application strict parser also runs | Upload request still depends on BCFtools in API image on `main`; durable dispatch is not merged. |
| 2. `normalize` | Reference-aware canonical representation, multiallelic splitting, sorting, CSI | `workflows/variant.py`, `domain/vcf_tools.py`, `domain/reference_package.py` | BCFtools + HTSlib; selected FASTA/FAI/reference package | BCFtools profile/queue fencing exists. Common executor is not wired into this path. Variant classes requiring specialized handling must retain explicit routing/limits. |
| 3. `annotate` | Consequence, transcript, HGVS and assembly-aware annotation | `adapters/annotation/vep.py`, `adapters/annotation/genebe.py`, provider registry and annotation stage | Local Ensembl VEP + offline cache; GeneBe is trial-only | VEP owns its own subprocess, binary/cache checks and result semantics. PR #302 is another agent's VEP annotation-contract work; do not duplicate or edit its files. Common executor adapter remains unintegrated. |
| 4. `population` | Allele frequencies/counts with ancestry/dataset context | `adapters/population/gnomad.py`, population stage, resource execution records | gnomAD GraphQL, local gnomAD Tabix, secondary-provider capability vocabulary | Confirm each production lab's dataset release/build/ancestry and local cache qualification. Secondary populations are profile candidates, not proof of available datasets. |
| 5. `build_evidence` | Clinical assertions, gene-disease, phenotype, computational, splicing, functional, literature and internal evidence | `adapters/evidence/clinvar.py`, ClinGen adapters, HPO/HPOA adapters, evidence workflow | ClinVar, ClinGen Variant Pathogenicity, ClinGen Gene-Disease Validity, ClinGen CSpec, HPO OBO, HPOA; GeneBe trial path | Computational/splicing/literature/functional/internal-lab classes exist in capability/profile vocabulary but do not all have registered providers. Missing optional evidence should remain an explicit evidence gap and route to review, not be fabricated. |
| 6. `acmg_assessment` | Apply ACMG/AMP + applicable ClinGen specifications | `backend/app/acmg/*`, ACMG API/workflow, ClinGen specification selection | SIRALOOM ACMG rules/engine plus qualified specification resources | Rule/specification versioning, evidence traceability and criterion-level validation must remain explicit; software output is a proposal, not independent clinical sign-out. |
| 7. `review` | Human reconciliation and sign-out preparation | review API/workflow, ReviewAction and audit models | Human reviewer; evidence and classification records | Verify actual role gates, reviewer separation, immutable review actions and blocked-state behavior end-to-end. |
| 8. `reportability` | Apply lab test/reporting policy | reportability workflow and `ReportabilityDecision` | Lab policy, test scope and human-reviewed decision | Policy version and approval must be pinned per report; do not infer reportability from pathogenicity alone. |
| 9. `report` | Generate immutable report version from approved decisions | reports API, `Report` model, artifact storage | SIRALOOM report renderer + approved findings | Recovery/immutability and exact source-decision linkage need E2E failure-injection evidence. |
| 10. `export_provenance` | Package execution/resource/reference/report provenance | export workflow, `CaseExport`, `CaseExportDispatch`, audit and snapshot models | SIRALOOM exporter and durable artifact storage | Must include every executable process, image digest, tool/profile, resource release, reference, parameters, outputs and checksums; verify restore and redelivery. |

**Important upstream boundary:** SIRALOOM's inspected workflow starts with a VCF. It does not currently claim to generate the query VCF from FASTQ/BAM. Alignment and variant calling (e.g. BWA-MEM2/DRAGEN and GATK HaplotypeCaller/DeepVariant) belong to the upstream sequencing/calling pipeline unless a separately scoped and qualified caller workflow is added. They must not be inserted into the SIRALOOM executable registry as if they were already implemented.

## 6. Native executable invocation inventory

The existing companion document `docs/engineering/NATIVE_EXECUTABLE_INVOCATION_AUDIT.md` records the detailed BCFtools and VEP command paths. The key production invocations are:

| Executable | Production location | Use | Current boundary |
|---|---|---|---|
| BCFtools | `domain/ingestion.py::_bcftools_validate` | Version/HTSlib attestation and `bcftools view` VCF structural parse | API process, synchronous upload path on `main` |
| BCFtools | `domain/vcf_tools.py::validate_vcf_index_concordance` and related index helpers | `bcftools index --stats`, indexed `bcftools view` queries | API process for uploaded TBI/CSI concordance on `main` |
| BCFtools | `domain/vcf_tools.py::split_multiallelic_vcf` | `bcftools norm -m -any` multiallelic split | Celery analysis worker |
| BCFtools | `domain/vcf_tools.py::normalize_vcf_with_bcftools` | Version attestation, GVCF wildcard handling, `norm -f`, sort, CSI index and index-concordance checks | Celery analysis worker |
| Ensembl VEP | `adapters/annotation/vep.py::VEPProvider` | `--version`, offline cache verification and local annotation | Celery analysis worker, provider-owned subprocess contract |
| BCFtools / hap.py | `scripts/validation/run_giab_benchmark.py`, `run_giab_concordance.py` | Explicit truth-set benchmark/VCF concordance | CI/operator qualification, not routine case execution |
| BCFtools / runner scripts | `run_vcf_scale_benchmark.py`, `run_vcf_qualification_matrix.py`, source-build scripts | Scale, VCF conformance and software qualification | CI/operator/build time |

The source audit is not a claim that every shell command in every optional developer script has been exhaustively classified. A future automated inventory test should scan process-launch sites and require each production invocation to declare its owner, tool identity, operation, profile and execution boundary. Do not silently convert benchmark-only tools into runtime requirements.

### Tools not currently established as production SIRALOOM workflow executables

- **Aligners:** BWA-MEM2, DRAGEN, minimap2 — upstream pipeline tools, not current SIRALOOM production workflow tools.
- **Variant callers:** GATK HaplotypeCaller, DeepVariant, DRAGEN caller — upstream query-VCF producers; no production caller stage established by the inspected workflow.
- **SV/CNV/repeat callers:** specialized callers and validators — not a fully qualified end-to-end interpretation path merely because input routing can preserve or route those records.
- **Other annotation/prediction tools:** CADD, REVEL, AlphaMissense, SpliceAI — resource/profile vocabulary exists; production provider coverage must be proven separately before enabling.
- **Benchmark tools:** hap.py is for truth-set comparison; it does not generate a query callset.

## 7. Common execution and lab-agent architecture: current state

### 7.1 What exists on `main`

- BCFtools profile IDs, exact versions, lock files, source checksums, security review and worker queues.
- Analysis-pinned BCFtools profile/version/queue/snapshot.
- Worker-side profile matching and queue routing.
- Reanalysis profile inheritance.
- VEP's independent local binary/cache verification and process lifecycle.
- `ToolRun` model (generic fields, but not demonstrated as the universal process ledger).
- Resource-provider execution records and resource snapshots.
- Celery dispatch/outbox/recovery for analysis and several other durable tasks.
- Deployment, storage, capacity and reference contracts.

### 7.2 What is proposed in open PRs (not `main`)

| PR | Scope | Dependency / status at audit |
|---|---|---|
| #295 | Existing architecture/native invocation audit documents | Open draft; this audit extends its scope and updates its baseline. |
| #297 | Durable artifact-validation dispatch; move VCF/index validation out of synchronous upload API path | Open draft; required dependency before tool-neutral API image. |
| #299 | VCF 4.0/4.5 conformance fixes owned by another agent | Open draft; do not edit its files or merge on behalf of its owner. |
| #300 | Tool-neutral API/Beat image and separate scientific worker image boundary | Open draft, explicitly stacked on #297; do not merge before #297. |
| #301 | Tool-neutral execution request/identity/artifact/provenance contract and local process executor | Open draft, stacked on #300; not integrated into BCFtools or VEP production calls. |
| #302 | VEP consequence payload/allele reconciliation contract, owned by another agent | Open draft; do not edit its VEP code/tests/docs or create a competing provider. |

PR state was read from GitHub during this audit. Re-check live PR heads and CI before any merge decision.

### 7.3 What is still missing for a real laboratory execution agent

No complete, production-qualified lab agent was identified on `main`. A proper agent requires:

- Unique lab/installation identity, registered public key/certificate and revocation.
- Authenticated outbound connection or controlled polling; no publicly exposed arbitrary command endpoint.
- Signed capability attestation: OS, architecture, container runtime, available profiles, CPU/RAM/GPU, scratch/durable storage, reference mounts, network policy and agent version.
- Tenant-scoped job lease with lease expiry/heartbeat, idempotency key, attempt, cancellation and bounded concurrency.
- Agent-side policy enforcement: only approved profile IDs and operation IDs; no arbitrary shell, arbitrary image or user-supplied executable.
- Exact verification of image digest, executable digest/version, input checksums, resource/reference identities and lab approval before launch.
- Isolated per-job workspace, resource limits, restricted filesystem/network, secret handling and process-group cleanup.
- Durable output upload, checksum verification, signed completion receipt and central provenance persistence.
- Crash/reboot recovery, expired-lease recovery, duplicate-delivery protection, cancellation and partial-output cleanup.
- Upgrade/rollback, agent health, security patching, audit and lab-admin control.

PR #301's local executor is a useful first boundary but is not this agent. It does not by itself provide remote transport, host attestation, cgroups/container isolation, scheduler adapters or durable central provenance.

## 8. Deployment and environment inventory

| Component | Existing evidence | What it currently proves | What it does not prove |
|---|---|---|---|
| Development Compose | `docker-compose.yml` | Postgres, Redis, API, worker, Beat, frontend and named volumes can be described together | API/worker image separation on `main`; lab-scale capacity or isolation |
| Production Compose | `docker-compose.production.yml` | Password-protected Redis, durable named/bind storage, reference/cache/scratch mounts, health checks, TLS-at-edge expectation, alternate BCFtools worker profiles | A generic tool scheduler, remote lab agent, HA, tested restore, Kubernetes or HPC |
| Backend image | `docker/backend.Dockerfile` | Locked Python dependencies, pinned BCFtools profile, non-root UID/GID 10001, reference/artifact/cache/scratch directories | Tool-neutral API image; it currently includes BCFtools |
| Alternate BCFtools source image | `docker/backend-bcftools-source.Dockerfile` and profile configs | Source-built BCFtools/HTSlib profiles for registered Linux AMD64 variants | Other tools' images, ARM64/HPC portability |
| Render manifest | `render.yaml` | A staging-style web service + managed Postgres/Redis declaration | A separate durable scientific worker fleet/agent and production lab topology |
| Azure infrastructure | `infra/azure/main.bicep`, `cloud-init.yaml`, `scripts/azure/deploy-infrastructure.ps1` | A validation VM, network security group, public IP, SSH allowlist, managed data disk, Docker bootstrap and CI syntax/compile checks | Managed production platform, autoscaling workers, private agent plane, managed database/object store, Kubernetes/Slurm, multi-region DR or a tested production deployment |
| Laboratory deployment contract | `domain/laboratory_deployment.py` | Service/storage/capability/TLS/durable-state requirements and deterministic contract hash | Actual provisioning or host-level capability attestation |
| Storage profiles | organization-specific artifact storage routing and adapters | Lab-owned artifact target abstraction | A complete isolation proof across local filesystems, object storage, cache, scratch and backups |
| Resource cache/reference mounts | production Compose and resource staging contracts | Separate persistent reference/resource-cache/scratch storage paths | Automated host registration, capacity scheduler and per-lab cache isolation proof |

### Environment model that is still needed

Create a **versioned environment/runner registration contract**, not another resource catalogue. It should capture:

- Environment ID, owner organization, installation ID, lifecycle/approval state.
- OS distribution/version, kernel, architecture and libc/runtime constraints.
- Container runtime/version, image digest policy, registry trust and signature verification.
- CPU, memory, GPU, local scratch, durable storage capacity and I/O class.
- Scheduler/runner type: local Compose worker first; later Kubernetes, Slurm/HPC or managed cloud runner.
- Network egress/ingress policy, proxy, offline mode and approved endpoints.
- Reference/cache mount identities, read-only/read-write scope and storage backend.
- Secret provider/identity, key rotation and workload identity.
- Supported tool profile IDs, provider capabilities, resource profiles and genome builds.
- Environment qualification evidence, benchmark scope, last verified time, expiry/review and revocation.
- Agent heartbeat/capacity/lease state if the environment is remote.

A lab can have multiple environments (e.g. secure on-premises, cloud burst, offline analysis enclave). A tool profile may be eligible on one environment and blocked on another. That relationship should be a compatibility resolver, not a single global setting.

## 9. Missing integrations and design decisions

| Gap | Why it matters | Reuse before adding | Required integration |
|---|---|---|---|
| Generic executable/tool profile | VEP and future tools cannot be represented by the BCFtools-only profile model | Existing BCFtools JSON profile, VEP execution contract, provider registry | Add generic immutable tool profile and BCFtools compatibility adapter; do not replace current profiles in one migration. |
| Workflow-to-tool mapping | Stage requirements name resource capabilities but not a complete set of executable operations | Workflow stage contracts + provider descriptors | Add stage operation contracts: allowed tool/profile/provider, inputs/outputs, required resources, retry and failure semantics. |
| Environment/runner registry | No complete host/cluster capability inventory | Deployment contract, storage profiles, resource capacity | Add lab-owned environment registration and qualification, with multiple environments per lab. |
| Generic executor integration | Direct BCFtools/VEP subprocesses bypass common execution contract | PR #301 executor; existing BCFtools/VEP safeguards | Adapt existing callers one at a time; preserve scientific command semantics and provider-owned parsing/validation. |
| Durable executable provenance | ToolRun is sparse; PR #301 provenance is currently in-memory | ToolRun + artifacts + audit events + ResourceExecutionRecord | Persist request/result, executable/image digest, args fingerprint, env/profile, resource bindings, input/output hashes, full log hashes, retry/lease and timestamps. |
| Unified dispatch interface | Celery queue is coupled to BCFtools profile routing | AnalysisDispatch/outbox and Celery | Define executor-neutral job request/receipt; keep Celery as backend #1. |
| Remote lab agent | No verified remote agent lifecycle | Installation/license models, tenant auth, dispatch/outbox, common executor | Implement enrollment, attestation, heartbeat, lease, controlled execution, signed receipt and recovery. |
| Multi-environment resource resolver | Resource resolver picks data providers/resources, not compute environments | AnalysisResourcePlan and resource profile resolver | Resolve tool + provider + resource + environment compatibility and lab approval before dispatch. |
| Capability/qualification dimensions | Software, resource, environment, scientific and clinical qualification are different | Existing ResourceQualification and toolchain profile statuses | Separate qualification types and evidence; do not reuse RESOURCE_QUALIFIED to imply software or clinical qualification. |
| Security boundary | Process executor alone does not isolate hostile or buggy tools | Non-root images, API/worker separation PR, existing protected process execution | Per-job sandbox, resource limits, filesystem/network policy, secrets isolation, signed images and agent identity. |
| Operational recovery | Durable dispatch exists in some workflows; remote execution requires lease and output reconciliation | Outbox/recovery patterns in Celery and export dispatch | Failure-injection tests for worker/agent loss, duplicate delivery, timeout, cancellation, storage outage and partial publication. |
| Clinical/tool qualification | A successful build or smoke test is not analytical validity | GIAB scripts and existing VCF qualification matrix | Known-answer fixtures per tool/profile/variant class, validated truth-set scope, performance limits and lab approval. |
| Tool catalog completeness | Capabilities currently exceed registered provider implementations | Provider registry's deliberate explicit registration | Track implemented vs planned vs disabled provider state; only enable an operation when provider + resource + environment + qualification all resolve. |

## 10. Dependency-ordered implementation plan

This order minimizes duplicate work and avoids weakening existing scientific behavior.

### Phase 0 — Stabilize the shared baseline and owned PRs

1. Re-check #299 VCF conformance owner branch and CI; keep ownership with that agent.
2. Re-check #297 durable artifact validation; ensure validation and uploaded-index concordance are fully worker-side, persisted, idempotent and recoverable.
3. Re-check #302 VEP annotation contract; preserve the other agent's ownership and merge sequence.
4. Rebase/reconcile architecture branches after their dependencies land. Do not merge #300/#301 while their base PRs remain unmerged or backend CI is red.

**Exit gate:** mainline baseline is green; upload validation has durable retry/recovery; VEP contract changes are settled; no owned branch is overwritten.

### Phase 1 — Complete the service boundary

5. Land #300 only after #297 and VCF conformance dependencies are resolved. Verify API/Beat contain no scientific binaries; worker images contain only the approved toolchain assigned to them.
6. Ensure API upload, index checks, report generation and scheduled tasks do not accidentally invoke scientific executables synchronously.
7. Separate API, scheduler/Beat and scientific workers in deployment topology; define service identity, mounts and permissions.

**Exit gate:** API image is tool-neutral; all native process invocations occur in declared worker/qualification contexts; existing scientific results are unchanged.

### Phase 2 — Generic tool profile and environment contracts

8. Define generic `ToolProfile` schema: tool ID, exact version, immutable image digest, executable identity, build/source/lock/SBOM, platform, operations, resource constraints, reference compatibility, security review, software qualification evidence and status.
9. Keep `toolchain-profiles.v1.json` as the BCFtools compatibility source initially. Adapt BCFtools profiles to the generic contract without changing their current status, queue fencing or reanalysis behavior.
10. Define `ExecutionEnvironment`/runner registration and organization approval: host identity, architecture, runtime, scheduler, capacity, storage, network, secrets and supported profiles.
11. Add a deterministic compatibility resolver: workflow stage + operation + tool profile + scientific provider + resource plan + lab environment + approvals → READY / READY_WITH_LIMITATIONS / BLOCKED with explicit reasons.

**Exit gate:** an analysis is pinned to compatible tool/profile/resource/environment IDs before execution; unsupported combinations fail closed and are explainable.

### Phase 3 — Generic execution request/result and durable provenance

12. Stabilize PR #301's contract and local executor. Preserve no-shell argv, executable identity checks, operation allowlist, input/output checksums, timeout/process-group handling, bounded log capture and full log hashes.
13. Adapt `ToolRun` into the durable executable ledger (or add a migration only if a schema gap is proven). Link each process to analysis, stage, attempt, dispatch, environment, profile, input/output artifacts and resource snapshots.
14. Keep `ResourceExecutionRecord` for provider/resource data access. Link it to the executable ledger only when a provider actually launches a local executable; remote API providers should not receive fabricated process records.
15. Add executor-neutral dispatch/result interfaces; implement Celery as the first dispatch backend. Prove idempotency, retry classes, cancellation, redelivery, lease expiry and atomic output publication.

**Exit gate:** every production process and provider resource access has the appropriate durable provenance; a lost worker cannot create a false success or duplicate published artifact.

### Phase 4 — Adapt existing tools, not rewrite them

16. Adapt BCFtools operations to the common executor through a thin adapter. Keep BCFtools scientific command construction and VCF/reference semantics in the existing BCFtools domain adapter.
17. After PR #302 is stabilized and coordinated with its owner, adapt the existing `VEPProvider` to the common runner. Do not create another VEP provider. Preserve offline mode, cache/manifest verification, binary digest/version checks, assembly/HGVS/MANE policy, allele reconciliation and provider result validation.
18. Add source-level invocation inventory tests that fail when a new production `subprocess`/native tool call bypasses an approved adapter.
19. Only then register the next actual executable tool, each with a separate known-answer test set and qualification scope. Do not onboard aligners/callers until the product explicitly includes FASTQ/BAM-to-VCF calling.

**Exit gate:** BCFtools and VEP production calls pass through the common execution boundary without changing their scientific output or failure policy.

### Phase 5 — Lab agent and additional environments

20. Implement agent enrollment/identity, signed capability attestation, heartbeat and revocation.
21. Implement lease-based job pull/dispatch, per-lab concurrency/capacity, secure workspaces, approved profiles only, signed result receipts and output checksum verification.
22. Integrate one lab-local Linux AMD64 Docker/Compose environment first. Prove the complete job lifecycle under worker/agent restart and network/storage failure.
23. Add Kubernetes, Slurm/HPC, air-gapped transfer or ARM64 only as independent adapters with separate installation, security, performance and recovery qualification.
24. Build operational monitoring: environment health, disk/inode pressure, worker queue depth, execution duration, failures, capacity, resource expiry and agent version.

**Exit gate:** one lab can enroll and qualify an environment, run an approved analysis there, recover from interruption and reproduce the result from pinned provenance. Only after that should multi-lab parallel capacity be scaled.

### Phase 6 — Scientific and clinical qualification per workflow scope

25. Define known-answer fixtures for SNVs, indels, multiallelics, GVCF reference blocks, symbolic SVs, breakends and any explicitly supported variant classes.
26. Qualify each tool/profile/reference combination against the applicable reference and truth-set scope; caller concordance requires an independently generated query callset and matched assay confidence regions.
27. Separately qualify resources (release/checksum/license/build), scientific algorithms (sensitivity/limitations), laboratory procedures and clinical interpretation/sign-out.
28. Validate end-to-end report and provenance recovery, tenant isolation, backup/restore, audit immutability and reanalysis inheritance.

**Exit gate:** claims are limited to the exact assay, variant classes, versions, references, environment and validation evidence actually tested.

## 11. Non-duplication and ownership rules

- Do not replace `Resource`, `ResourceDiscovery`, `ResourceStaging`, `ResourceQualification`, `ResourceApproval` or `OrganizationResourceBinding` with a new resource registry.
- Do not label `toolchain_profiles.py` as universal; it is BCFtools/HTSlib-specific.
- Do not create a second VEP provider; adapt the existing provider only after PR #302 is coordinated and stable.
- Do not edit the VCF conformance files/tests owned by the PR #299 agent.
- Do not treat `ToolRun` and `ResourceExecutionRecord` as interchangeable.
- Do not treat `ResourceDeploymentProfile` as a compute environment.
- Do not treat a lab deployment contract or Azure validation VM as proof of a deployed remote agent.
- Do not register BWA/GATK/DeepVariant/DRAGEN as SIRALOOM production tools unless the product scope includes and qualifies their upstream pipeline stage.
- Do not equate software qualification, resource qualification, scientific performance qualification and clinical validation.

## 12. Audit limitations

This audit maps the principal registries, models, workflow-stage contracts, production executable paths and deployment manifests identified from the repository tree and targeted source inspection on the stated baseline. It is not a formal exhaustive static analysis of every process-launch statement in every optional script, nor a live test of an Azure or laboratory deployment. The companion native invocation audit should be complemented by automated source scanning and runtime integration tests before any executable is removed from an image or moved to a new runner.

## Final engineering decision

The next code milestone should **not** be “build a second registry” or “add a lab agent immediately.” First stabilize the durable upload-validation and VEP/VCF owner PRs, then complete the API/worker boundary. Next, define the generic tool-profile and environment contracts, adapt the existing BCFtools and VEP implementations through the common executor, and persist execution provenance. The remote lab agent should be built only after those contracts and recovery semantics are stable.

That sequence reuses the real systems already in SIRALOOM and turns them into a coherent, auditable multi-laboratory execution platform without pretending that the missing integration already exists.
