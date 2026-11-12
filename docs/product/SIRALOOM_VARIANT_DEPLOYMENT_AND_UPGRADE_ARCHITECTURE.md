# SIRALOOM Variant — Deployment, Installation and Upgrade Architecture

**Status:** Proposed product architecture and implementation roadmap  
**Product:** SIRALOOM Variant (Service 01)  
**Baseline:** `integration/stage1-referral-provenance-20261110`  
**Decision:** One product, one governed release line, three controlled customer deployment topologies  
**Important:** This is an architecture proposal. It does not declare the current repository clinically validated, commercially cleared, or ready for production deployment.

## 1. Product and commercial objective

SIRALOOM Variant is the first independently sellable SIRALOOM product. Its initial intended software boundary is germline SNV/small-indel interpretation beginning with VCF intake and ending with reviewed, governed interpretation and reporting.

The product must be installable in infrastructure controlled by the customer, because SIRALOOM does not currently have the capital to operate a hosted cloud. The customer should be able to buy and operate the product without sending identifiable genomic data to SIRALOOM.

The product must also evolve without requiring a replacement installation for every new feature. A customer receives controlled, compatible releases and can enable separately governed capabilities while preserving prior analyses and audit history.

**Core product rule:** one application and scientific workflow product; three deployment adapters; independently versioned capabilities, scientific resources and workflows.

The initial product must not be sold as clinically validated solely because the software installs or automated tests pass. Each laboratory must validate the intended assay/workflow and authorize clinical use under its own quality system and applicable jurisdiction.

## 2. The three supported deployment topologies

These are three deployment topologies of the same product, not separate code forks or feature editions. All three use the same API contracts, data model, authorization, audit model, workflow definitions, release manifests and upgrade protocol.

### 2.1 SIRALOOM Lab Server

**Target:** a smaller laboratory, university group or research unit that wants a dedicated, locally operated installation.

- One customer-owned physical server or dedicated virtual machine.
- Containerized application services: web/API, background worker, scheduler where required, PostgreSQL and Redis.
- Customer-controlled artifact and reference-data storage.
- Local execution through a qualified container runtime.
- One deployment administrator with documented backup, restore, monitoring and patch responsibilities.

**Initial supported topology:** a single Linux x86_64 host using Docker Engine or a supported Podman configuration, with persistent database/artifact volumes. Exact minimum CPU, RAM, disk and supported OS versions must be set only after representative benchmark and installation testing.

This is the first topology to qualify because it is the least operationally complex and fits the current funding constraint.

### 2.2 SIRALOOM Lab Cluster

**Target:** a larger laboratory or institution with multiple analysts, higher sample volume or an existing HPC environment.

- Customer-owned multi-node Linux environment.
- Separate API/control-plane services and execution workers.
- Shared, access-controlled artifact/reference storage.
- Resource-aware scheduling, worker leases, retries and durable execution records.
- Scheduler adapters introduced only when implemented and tested (for example Slurm); do not describe Slurm or Kubernetes as supported merely because an environment contract has a scheduler field.
- Explicit worker identity, health, capacity and execution-environment qualification.

The first cluster release may use a controlled set of container workers before adding a Slurm adapter. Scheduler-specific execution is a later acceptance gate, not an assumed property of the current partition scheduler.

### 2.3 SIRALOOM Private Cloud

**Target:** an institution that operates its own cloud account, private cloud or managed Kubernetes/container infrastructure.

- Deployed into the customer's account/subscription/project.
- Customer retains control of network, identity, encryption keys, storage and backups.
- SIRALOOM supplies versioned deployment charts/templates and configuration validation.
- Workload identity and secrets are supplied through the customer's supported secret manager.
- Private networking and egress allowlists are configurable and tested.
- Cloud-specific managed services are optional adapters, not mandatory dependencies of the product.

AWS, Azure, GCP and other providers must be listed as supported only after provider-specific installation, storage, identity, backup/restore and upgrade qualification. Kubernetes support likewise requires a tested deployment adapter and operational runbook.

### 2.4 Explicitly deferred: SIRALOOM-hosted SaaS

SIRALOOM-hosted cloud is not a prerequisite for Product 01. It should be a later fourth commercial delivery model only after financing, security operations, tenant isolation, data residency, support, incident response, backup/restore and regulatory obligations can be funded and validated.

## 3. What a laboratory receives

A laboratory should receive a release bundle, not an unstructured source-code checkout.

Each release bundle must include:

1. Signed release manifest with product version, build identity and supported deployment profiles.
2. Immutable OCI image references by digest for every service and worker.
3. Database migration bundle with forward-compatibility and rollback classification.
4. Deployment templates for the qualified topology.
5. Preflight installer/validator and post-install health checks.
6. Configuration schema and a generated deployment-specific configuration report.
7. Tool, workflow and scientific-resource compatibility matrix.
8. Backup, restore, upgrade, rollback and disaster-recovery runbooks.
9. Software bill of materials (SBOM), vulnerability scan results and release test evidence.
10. Release notes, known limitations, security advisories and support/maintenance policy.
11. Offline installation option for disconnected laboratories, with a verifiable signature and digest chain.
12. Customer acceptance checklist and laboratory qualification evidence template.

Do not include customer secrets, patient data, private reference data or provider credentials in the release bundle.

## 4. Installation and customer onboarding lifecycle

The supported lifecycle is:

1. **Commercial agreement:** define licensed organization/site, users, permitted use, support, maintenance window, upgrade entitlement and data responsibilities.
2. **Deployment selection:** Lab Server, Lab Cluster or Private Cloud.
3. **Preflight:** validate OS/kernel/architecture, container runtime, CPU/RAM/disk, storage, DNS/TLS, outbound network policy, identity integration, backup destination and time synchronization.
4. **Install:** verify release signature and image digests; install the selected topology; initialize database and secrets; run migrations under controlled service identity.
5. **Register environment:** create a tenant-bound environment registration containing immutable runtime, platform, storage, capacity, network and executor identity snapshots.
6. **Configure product:** configure reference assembly packages, scientific resources/providers, supported tool profiles, workflow profiles, assay scope, QC rules, roles and review policy.
7. **Technical qualification:** run installation self-tests, executor qualification, reference/resource integrity checks, workflow conformance and representative benchmark datasets.
8. **Laboratory validation:** laboratory personnel execute approved validation protocols, assess intended-use performance, document deviations and approve the validated scope.
9. **Go-live authorization:** an authorized laboratory role explicitly activates clinical use for the approved assay, workflow, resource and software scope.
10. **Operate and maintain:** monitor health/capacity, patch security issues, back up/restore, review audit events and manage resource/workflow updates.

Installation success must never automatically set an assay to clinically validated or authorize report sign-out.

## 5. Product architecture: stable core plus controlled capabilities

### 5.1 Stable platform core

The core provides:
- Organization/tenant and identity boundary.
- Case, specimen, request and artifact records.
- Workflow orchestration and durable execution.
- Scientific resource and tool-profile registries.
- Environment registry and executor adapters.
- Evidence provenance, immutable manifests and audit records.
- Review, report, sign-out and reanalysis governance.
- Licensing/entitlement checks and deployment administration.
- Upgrade manager and compatibility evaluator.

The core should expose versioned internal APIs and migration contracts. Product capabilities must not bypass identity, audit, provenance, authorization or evidence-use gates.

### 5.2 Capability packages

New specifications should be delivered as versioned capabilities, not one-off customer code forks. A capability package declares:

- Stable capability ID and semantic version.
- Product compatibility range.
- Required platform API and database schema versions.
- Dependencies on other capabilities.
- Workflow/tool/resource dependencies.
- Configuration schema and defaults.
- Entitlement/licence requirement.
- Security permissions and data-access scope.
- Feature activation and deactivation behavior.
- Migration and rollback classification.
- Unit, integration, conformance and regression evidence.
- Whether laboratory revalidation or approval is required.

Examples of future capabilities (not promises of current implementation): expanded phenotype matching, additional population resources, new report templates, CNV/SV interpretation as a separate validated scope, family-based analysis enhancements and additional clinical knowledge sources.

A capability must be disabled by default until installed, compatible, entitled and explicitly activated by an authorized customer administrator. Clinical capabilities additionally require laboratory approval for their intended scope.

### 5.3 Scientific resources and tools are separate release objects

A new ClinVar/ClinGen/HPO/gnomAD release is not the same thing as an application upgrade. It must have its own source identity, version, acquisition date, checksum/signature evidence, licence/retention policy, qualification state and activation decision.

Likewise, a tool upgrade (BCFtools, VEP, HTSlib or other tool) requires a pinned executable/container identity, compatibility and qualification evidence. A workflow release binds exact tool profiles and scientific resource releases.

## 6. Upgrade and change-control protocol

Every customer upgrade follows this controlled sequence:

1. **Discover:** customer administrator sees available release, security advisories, new capabilities and required actions.
2. **Evaluate:** compatibility engine compares current platform, schema, deployment topology, tool profiles, resources, workflow versions, capacity and licence entitlements.
3. **Classify impact:** routine software change, security patch, scientific resource update, workflow/tool change, schema migration or intended-use/clinical change.
4. **Prepare:** verify backups and restore point; stage exact images/manifests; produce a dry-run migration and compatibility report.
5. **Stage:** install in a non-production environment with a copy or synthetic/de-identified validation dataset.
6. **Verify:** run health, migration, security, workflow conformance, golden-dataset regression and customer acceptance tests.
7. **Approve:** customer administrator approves technical promotion; laboratory quality/clinical authority separately approves any change affecting validated intended use.
8. **Promote:** deploy the exact signed bundle; record approver, time, previous and new versions, migration IDs, image digests and test evidence.
9. **Observe:** monitor service, queue, execution, artifact and workflow health; keep a defined rollback window.
10. **Close:** record acceptance or rollback, with immutable change history.

### 6.1 No silent reinterpretation

A new resource, annotation provider, tool or workflow version must never silently rewrite a completed analysis or report. Reanalysis creates a new linked analysis/reanalysis record with its own exact versions and provenance. Existing reports remain reproducible against their original evidence and software snapshot.

### 6.2 Rollback

- Application images can be rolled back only when schema compatibility permits.
- Database migrations must declare whether they are backward-compatible, forward-only or require restore-based rollback.
- Scientific resource activation can be reverted to a prior qualified release only if policy and provenance permit; historical analyses retain their original release binding.
- A clinical workflow/assay change may require revalidation and cannot be made safe merely by reverting a container.
- Destructive data migrations must require verified backup and an explicit recovery plan; never promise automatic rollback where it is not technically safe.

## 7. Required release and execution manifests

### 7.1 Product release manifest

At minimum:
- Product/service ID and version.
- Release channel (development, validation, stable, security).
- Source commit and build provenance.
- Image names and immutable digests.
- SBOM and signature references.
- API and schema compatibility.
- Deployment topology compatibility.
- Capability package versions.
- Required configuration changes.
- Migration list and rollback classification.
- Security/test/benchmark evidence references.
- Known limitations and support window.

### 7.2 Analysis execution snapshot

Every analysis must preserve the exact identities needed to reproduce and audit it:
- SIRALOOM product/platform release and source/build identity.
- Workflow definition ID, version and digest.
- Tool profile ID/version, executable/container digest and runtime dependencies.
- Environment registration ID/version and immutable environment snapshot.
- Scientific resource IDs, release versions, digests, assemblies and source provenance.
- Reference package identity/digest and relevant indexes/contig metadata.
- Input artifact identity/digest and sample/specimen/case linkage.
- Configuration and policy versions.
- Executor/scheduler identity and relevant runtime attestation.
- Output artifact manifest/digests and execution status/retry lineage.

The existing environment/tool/resource registries and persistent execution work are foundations. The integration audit must verify that every field above is actually captured and enforced at all workflow call sites, including pre-analysis VCF intake—not merely present in schemas or a subset of adapters.

## 8. Product 01 initial commercial scope

The first product is **SIRALOOM Variant — Germline SNV/Indel Interpretation**.

Initial supported scope must be deliberately bounded and documented:
- Germline SNVs and small insertions/deletions in explicitly supported VCF/reference/assay contexts.
- VCF intake, structural validation, sample identity checks and reference-aware normalization.
- Annotation and population context using legally permitted, versioned resources.
- Phenotype, gene–disease, literature and inheritance/segregation context as governed decision support.
- ACMG/AMP and ClinGen-aware evidence assessment with human review.
- Technical QC, reportability, confirmation/follow-up and secondary-finding governance where configured.
- Clinical and analytical reporting with provenance and audit export.
- Reanalysis candidate tracking and controlled reanalysis.

Explicitly out of scope until separately specified, implemented and validated: autonomous diagnosis, automatic clinical sign-out, unvalidated variant classes (including CNVs/SVs), unsupported mitochondrial/mosaic contexts, and claims of universal assay coverage.

**Commercial blocker to resolve before sale:** the current repository release-status document identifies the configured GeneBe provider as research/educational and non-commercial in its current configuration. SIRALOOM must not sell a product relying on a provider or dataset without confirming commercial-use, caching, retention, redistribution and clinical-use terms. Select and qualify a permitted annotation/resource strategy before commercial launch.

## 9. Three deployment topologies: support policy

| Capability | Lab Server | Lab Cluster | Private Cloud |
|---|---|---|---|
| Product/API and web UI | Required | Required | Required |
| PostgreSQL and durable queue | Required | Required, HA strategy as qualified | Required, managed or self-operated |
| Local/customer-controlled artifacts | Required | Shared governed storage | Customer cloud storage |
| Container executor | Initial qualification target | Worker executor | Container service/cluster adapter |
| Multiple execution workers | Optional, bounded | Required | Scalable |
| Scheduler adapter | Not required initially | Required for each advertised scheduler | Depends on topology |
| Offline installation | Required option | Required option | Depends on customer network |
| Central SIRALOOM telemetry | Off by default; explicit opt-in only | Off by default; explicit opt-in only | Off by default; explicit opt-in only |
| Upgrade control | Customer-approved bundle | Customer-approved staged rollout | Customer-approved staged rollout |

Do not market a cell as supported until the matching installation and acceptance suite passes on a declared support matrix.

## 10. Commercial packaging and revenue model

Start with a simple quote rather than premature complex usage billing:
- Annual or term-based product licence per laboratory/site, with defined user/workload bands.
- One-time installation and qualification-support fee where appropriate.
- Annual maintenance and upgrade entitlement.
- Optional paid implementation, migration, workflow configuration, training and support.
- Separately priced future capability packages, where the commercial and validation boundaries are clear.

Do not charge customers for a capability that is merely on the roadmap. Define what happens to customer data, audit records and software access at contract expiry. Ensure licence checks cannot block safe access to historical records or exports required by the customer's obligations.

## 11. Delivery roadmap and acceptance gates

### Gate A — architecture and gap reconciliation
- Reconcile this design with the master defect register, deployment docs and existing environment/tool/resource registry work.
- Produce an evidence-backed map of existing code, tests, incomplete integrations and deployment assumptions.
- Decide the exact first supported Lab Server hardware/OS/runtime matrix.
- Resolve commercial provider/data licences.

**Exit:** approved architecture and traceable gap register; no unsupported deployment claims.

### Gate B — installable Lab Server release
- Reproducible signed images and release manifest.
- Installer/preflight/configuration validation.
- Persistent volumes and customer-owned secrets.
- PostgreSQL/Redis/API/worker lifecycle.
- Backup/restore and upgrade/rollback runbooks.
- Installation and post-install smoke tests.
- Offline installation bundle.

**Exit:** clean install, restart, backup, restore, upgrade and recovery demonstrated on a clean supported host.

### Gate C — governed execution and product qualification
- Mandatory persistent execution boundary for every scientific workflow, including VCF intake.
- Complete immutable execution snapshot and use-time artifact/resource verification.
- Tool/environment qualification and lifecycle enforcement.
- Golden dataset and independent expected-output validation.
- Security, tenant isolation, access control and audit tests.
- Lab validation pack and clear intended-use limitations.

**Exit:** software acceptance evidence complete; laboratory independently approves its own validation before clinical use.

### Gate D — first customer deployment
- Contract, deployment assessment and named customer administrator.
- Customer-controlled installation.
- Configuration, qualification and acceptance records.
- Support/maintenance process and incident escalation.
- Controlled production release authorization by customer.

**Exit:** first customer installation accepted; no implication that one customer's validation automatically validates another laboratory.

### Gate E — cluster and private-cloud expansion
- Cluster worker/control-plane separation and supported scheduler adapter(s).
- Capacity, quota, worker enrollment, health and recovery.
- Private cloud deployment templates and identity/storage adapters.
- Topology-specific installation, upgrade and disaster-recovery tests.

**Exit:** separate qualification for each advertised infrastructure profile.

## 12. Immediate engineering work sequence

1. Finish the registry-to-execution-platform audit and reconcile it with the master defect register.
2. Establish the Product 01 deployment/upgrade architecture as a controlling specification.
3. Build the Lab Server installer and release-bundle pipeline first.
4. Close mandatory execution routing, environment lifecycle, immutable execution snapshots and resource/tool release binding.
5. Build the upgrade manager around signed release manifests, compatibility evaluation, staged promotion and migration safety.
6. Validate on clean reproducible hosts and representative benchmark datasets.
7. Only then qualify Lab Cluster and Private Cloud adapters.

Do not create three divergent application codebases. Do not start Kubernetes/Slurm/cloud automation before the Lab Server path is reproducible and governed. Do not merge stacked execution PRs independently; reconcile their dependency chain and verify the integrated branch.

## 13. Current evidence versus target state

| Area | Current repository evidence | Target / remaining proof |
|---|---|---|
| Variant workflow | Phase-1 release candidate described in README and release-status docs | Intended-use scientific validation and customer laboratory qualification |
| Docker deployment | Existing deployment guide and production Compose foundation | Clean-host installer, signed bundle, support matrix, restore/upgrade qualification |
| Environment registry | Environment contract and persistence work in open stacked PRs | Integrated, merged, tested lifecycle and mandatory dispatch on all workflows |
| OCI execution | Docker/Podman executor foundation in open PR chain | Exact integrated release qualification and customer host compatibility matrix |
| Tool/resource registries | Versioned registries and profile work exist | Full immutable release binding and use-time verification across every path |
| Cluster | Resource-aware partitions and execution foundations | Multi-node control plane, worker enrollment, scheduler adapters and recovery |
| Private cloud | Existing storage/deployment concepts | Provider-specific identity, storage, network, installation and lifecycle qualification |
| Upgrades | Database migrations and release documentation exist | Signed product/capability manifests, compatibility engine, staging/promotion and rollback |
| Commercial readiness | Product boundary identified | Provider/data commercial terms, licence/support terms, security and validation package |

## 14. Non-negotiable product principles

1. Customer data remains under customer control by default.
2. No hidden transfer of patient/genomic data to SIRALOOM.
3. No clinical use solely because installation or software tests pass.
4. No unqualified tool, resource, environment or workflow enters a clinical analysis.
5. No silent changes to historical analyses or reports.
6. No bypass of tenant authorization, evidence integrity, audit or clinical review gates.
7. No capability activation without compatibility, entitlement and authorized approval.
8. No advertised infrastructure support without reproducible acceptance evidence.
9. No dependency on SIRALOOM-hosted cloud for the first commercial release.
10. Every release and customer-specific configuration must be traceable and supportable.

---
**Decision requested before implementation beyond documentation:** confirm whether the three proposed topologies—Lab Server, Lab Cluster and customer-owned Private Cloud—are the intended three. The recommendation is to qualify Lab Server first, then Cluster, then Private Cloud. This document itself does not authorize merging or deployment.
