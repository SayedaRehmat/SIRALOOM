# SIRALOOM Environment Platform — Production Infrastructure Research and Gap Matrix

**Status:** Research and requirements baseline; not an implementation approval  
**Date:** 2026-11-12  
**Scope:** Scientific workflow execution environments for research and clinical genomics, with a portable platform design for other life-sciences workloads  
**Initial deployment constraint:** Customer-owned Linux infrastructure; SIRALOOM-hosted cloud is deferred  
**Evidence labels:** Documented institutional infrastructure, vendor-documented architecture, SIRALOOM repository evidence, or recommendation/inference

---

## 1. Executive findings

There is no single “genomics laboratory server.” Production genomics is run on several distinct infrastructure patterns:

1. **Institutional HPC:** Linux login/control services, heterogeneous CPU/GPU compute nodes, a batch scheduler, high-speed interconnect, shared or parallel filesystems, data-transfer nodes, and container execution that does not require users to run a privileged Docker daemon.
2. **Customer-owned Linux servers:** one or more Linux hosts or a small cluster, often using Docker or Podman for isolated tasks, local NVMe or NAS/SAN storage, and a workflow engine.
3. **Managed cloud batch:** a workflow engine decomposes a workflow into tasks; a cloud batch service provisions task-sized virtual machines or workers; containers execute the task; object storage holds inputs, intermediates, outputs and logs.
4. **Hybrid environments:** sequencers and some data remain on-site, while compute is performed on local HPC, private cloud, or public cloud depending on data policy and capacity.
5. **Specialized appliances/accelerators:** for example, Illumina DRAGEN systems for specific secondary-analysis workloads. These are not a substitute for a general workflow execution platform.

**Key architectural conclusion:** SIRALOOM must separate workflow orchestration, scheduler/backend, container runtime, compute host, data staging/storage, and environment qualification. Docker is a useful first customer-owned deployment target, but it is not a universal execution runtime. HPC customers may use Slurm or LSF with Apptainer; cloud customers may use managed batch services. The same workflow/task contract should be dispatched through different qualified adapters.

**Do not prescribe one universal CPU/RAM/server specification.** Workload requirements differ substantially by tool, sample type, sequencing depth, reference/cache size, concurrency, and whether the task is CPU-, memory-, I/O-, network-, FPGA-, or GPU-bound. SIRALOOM should collect and enforce resource requirements per task and publish measured, workload-specific sizing guidance.

## 2. Evidence from real institutional and commercial systems

### 2.1 NIH Biowulf — biomedical research HPC

The NIH Biowulf documentation describes a Linux-based, heterogeneous, shared HPC system. Its published hardware inventory includes 1,541 compute nodes, 76,572 physical cores, 153,144 logical CPUs, 1,024 GPUs, very-large-memory nodes up to 3 TB, and more than 75 PB of high-performance storage. It uses Slurm, has dedicated login/service and data-transfer nodes, and uses high-speed InfiniBand fabrics. Its documentation explains that users submit jobs through the scheduler rather than directly connecting to compute nodes.

Sources:
- https://hpc.nih.gov/systems/hardware.html
- https://hpc.nih.gov/docs/ExpUserGuide.html
- https://hpc.nih.gov/apps/apptainer.html

**Implications:** a genomics platform must not assume a single homogeneous server, direct SSH to compute nodes, privileged Docker, or local disk as the only storage. It must understand scheduler queues/partitions, resource requests, shared filesystems, transfer nodes, and site policies.

### 2.2 Wellcome Sanger Institute — The Farm

Sanger publicly describes multiple HPC farms with more than 20,000 CPU cores and 275 GPUs connected by 400 Gb/s networking. Its published Farm documentation identifies Ubuntu 22.04 and IBM Spectrum LSF as the operating system and scheduler for the described farms. It also describes dedicated transfer hosts and internal JupyterHub access. The campus data-centre team describes large compute/storage farms, private-cloud storage, multi-petabyte storage platforms, off-site disaster-recovery data centres and high-bandwidth connectivity.

Sources:
- https://hpc.sanger.ac.uk/services/hpc/
- https://www.sanger.ac.uk/group/data-centre-services/

**Implications:** scheduler support must be adapter-based. Slurm is common, but it is not universal; LSF is a real production institutional choice. Data-transfer services and disaster recovery are infrastructure concerns in their own right, not just workflow-engine details.

### 2.3 Terra / Broad Institute — cloud workflow execution

Terra documents a service chain in which the user-facing platform submits workflows to Rawls/Cromwell; Cromwell interprets WDL and dispatches individual tasks to Google Batch; Batch provisions Compute Engine VMs, runs containers with task commands and inputs, uploads outputs to cloud storage, and terminates the VMs. Cromwell coordinates task dependencies and records workflow outputs/status.

Sources:
- https://support.terra.bio/hc/en-us/articles/360055105051-Overview-How-the-workflow-system-works
- https://support.terra.bio/hc/en-us/articles/360036379771-Overview-Running-workflows-in-Terra

**Implications:** orchestration service and execution workers are separate. A workflow platform should not require scientific executables to be installed in the API/orchestration image. Task-sized workers, explicit input/output staging, container identity, logs and durable outputs are essential.

### 2.4 AWS HealthOmics — managed bioinformatics workflow execution

AWS documents private workflows using WDL, Nextflow or CWL, with container images available from registries such as ECR and task-level compute/memory requirements declared in workflow definitions. HealthOmics manages infrastructure and coordinates workflow execution, data movement, resource allocation, monitoring and failure/retry behavior.

Sources:
- https://aws.amazon.com/documentation-overview/healthomics/
- https://docs.aws.amazon.com/omics/latest/dev/workflows-setup.html

**Implications:** SIRALOOM should support standard workflow definitions and explicit per-task CPU/memory requirements, while keeping its own tenant, authorization, evidence, provenance and audit policies outside the workflow engine.

### 2.5 DNAnexus — job/worker cloud execution

DNAnexus documents a job as the unit of execution. When a job is runnable, a cloud worker is started, the job code is downloaded and executed, and the job may make API calls or spawn other jobs. Its app execution environment documents Ubuntu Linux worker environments and selectable compute instance types.

Sources:
- https://documentation.dnanexus.com/developer/api/running-analyses
- https://documentation.dnanexus.com/developer/apps/execution-environment

**Implications:** durable job identity, parent/child execution lineage, worker lifecycle, resource selection and platform APIs are central to a commercial scientific execution platform.

### 2.6 HPC container execution — Apptainer

NIH Biowulf recommends Apptainer for cluster use. Apptainer is designed to run without root privileges or a separate daemon, and can execute many Docker/OCI images. Nextflow documents Apptainer integration and notes that it invokes tasks through Apptainer on the target system. Apptainer's own documentation describes read-only SIF images and compatibility considerations.

Sources:
- https://hpc.nih.gov/apps/apptainer.html
- https://docs.seqera.io/nextflow/container/apptainer/
- https://apptainer.org/docs/user/latest/docker_and_oci.html

**Implications:** a Docker image may be portable to HPC, but Docker Engine itself may not be available on the cluster. SIRALOOM needs a runtime adapter and an HPC-compatible execution mode, not a Docker-only assumption.

### 2.7 Illumina DRAGEN — specialized genomics appliance

Illumina's DRAGEN Server v3 site-preparation guide describes a specific 2U appliance configuration with dual Intel Xeon CPUs, 256 GB RAM, 6.4 TB NVMe scratch, OS SSDs and a DRAGEN FPGA card. The cited guide is for that model/version and is explicitly marked Research Use Only; it must not be treated as a current universal server recommendation or as clinical-use authorization.

Source:
- https://sapac.illumina.com/content/dam/illumina-support/documents/documentation/software_documentation/dragen-bio-it/1000000097923_03_DRAGEN-server-v3-site-prep-and-installation-guide.pdf

**Implications:** SIRALOOM should model accelerators and specialized tool environments as qualified execution profiles. It should not hard-code FPGA/DRAGEN assumptions into the general executor.

## 3. Common infrastructure layers and what each does

| Layer | Typical real-world choices | Responsibility | SIRALOOM requirement |
|---|---|---|---|
| Host OS | Linux distributions (Ubuntu, RHEL-family, site-managed Linux) | Kernel, users, filesystem, device and security policy | Detect and record OS, distribution/version, kernel, architecture and relevant host capabilities |
| CPU architecture | x86_64; ARM64 in some fleets | Instruction set and binary compatibility | Architecture-specific immutable tool/image profiles; never assume x86 binaries run on ARM |
| Compute | Physical servers, VMs, HPC nodes, cloud workers | CPU, RAM, local scratch, accelerators | Resource request and observed usage per task; capacity and compatibility checks |
| Scheduler | Slurm, IBM Spectrum LSF, PBS, HTCondor, Kubernetes, AWS Batch, Google Batch | Queueing, placement, resource allocation, job state | Pluggable scheduler adapter with submit/poll/cancel/reconcile semantics |
| Workflow engine | Nextflow, Cromwell/WDL, Snakemake, CWL runners | DAG/task dependencies, retries and workflow-level state | Integrate standards-based engines; do not confuse workflow orchestration with host scheduling |
| Container runtime | Docker Engine, Podman, Apptainer/Singularity, containerd/CRI-O via Kubernetes | Isolated task software environment | Runtime adapter; exact image digest and runtime identity; per-runtime qualification |
| Storage | NVMe, NFS, Lustre/GPFS/Spectrum Scale, VAST, NAS/SAN, S3/GCS/Azure Blob | Inputs, scratch, shared resources, outputs, archive | Storage profiles and data-plane adapters; byte-level integrity and atomic publication |
| Network | Ethernet, InfiniBand, private network, controlled egress | Data movement and distributed execution | Explicit egress policy, transfer paths, throughput and locality metadata |
| Registry | OCI registry, private registry, local SIF repository | Immutable software images | Approved registry sources, digest pinning, signature/provenance verification and offline cache |
| Operations | Monitoring, logs, metrics, audit, backup/DR | Availability and support | Durable run logs, health/capacity status, event audit, recovery and operator controls |

The workflow engine and scheduler are different layers. Nextflow explicitly abstracts pipeline logic from the execution environment; its documented executors include Slurm, LSF, PBS, HTCondor, Kubernetes, AWS Batch, Azure Batch and Google Cloud Batch. Nextflow's Slurm executor submits task jobs using `sbatch`; its Apptainer integration runs task containers without requiring Docker on the compute node.

Sources:
- https://docs.seqera.io/nextflow/overview/
- https://docs.seqera.io/nextflow/reference/executor/
- https://docs.seqera.io/nextflow/reference/executor/slurm/
- https://docs.seqera.io/nextflow/container/apptainer/

## 4. Environment profiles SIRALOOM must understand

| Profile | Host/compute | Scheduler | Runtime | Storage/data pattern | Product priority |
|---|---|---|---|---|---|
| E1 — Single customer Linux host | One or more customer-owned x86_64 Linux servers | Local process queue initially | Docker or Podman | Local NVMe plus mounted customer storage | Initial deployment target |
| E2 — Customer-owned Linux worker pool | Multiple Linux hosts | SIRALOOM-managed remote dispatch/agent pool | Docker or Podman | Shared filesystem or explicit staging | Initial commercial expansion |
| E3 — Institutional HPC | Login/service nodes plus heterogeneous compute nodes | Slurm | Usually Apptainer; site-dependent | Parallel/shared filesystem plus transfer nodes | High-priority institutional adapter |
| E4 — Institutional HPC (LSF) | As above | IBM Spectrum LSF | Usually Apptainer or site runtime | Shared filesystem plus transfer services | Required portability path; evidenced at Sanger |
| E5 — Kubernetes cluster | Worker nodes, potentially mixed hardware | Kubernetes scheduler | containerd/CRI-O through Kubernetes | Persistent volumes and/or object storage | Later platform adapter |
| E6 — Public cloud batch | Ephemeral VMs/worker instances | AWS Batch, Google Cloud Batch, Azure Batch, managed genomics service | OCI containers | Object storage and task staging | Later, customer-controlled cloud |
| E7 — Specialized accelerator host | Qualified server with FPGA/GPU or other accelerator | Local or site scheduler | Vendor/runtime-specific plus containers where supported | Local fast scratch and durable output store | Tool-specific qualification |
| E8 — Hybrid/on-prem + cloud | Customer sequencer/storage plus local and cloud compute | Multiple schedulers/backends | Multiple runtimes | Controlled data transfer and data locality | Strategic target |

These are deployment profiles, not a promise that all are currently implemented in SIRALOOM.

## 5. Workload sizing: what must be measured rather than guessed

A single “minimum genomic server” specification is unsafe and commercially misleading. Requirements must be measured by workload and task.

| Workload class | Dominant constraints to measure | Required benchmark evidence |
|---|---|---|
| VCF validation, normalization, indexing | CPU, memory, file size, random/sequential I/O, reference access | Small/medium/large VCF; compressed/uncompressed; indexed and unindexed |
| Short-read alignment / secondary analysis | CPU throughput, RAM, scratch I/O, reference/index staging; optional FPGA acceleration | FASTQ size/read count, coverage, runtime, peak RAM, scratch and output size |
| Variant annotation (e.g. VEP) | CPU, RAM, cache size, filesystem metadata and read throughput | Cache release/assembly, offline mode, concurrent cache reads, peak RAM and I/O |
| Population-frequency annotation | Network/API availability or local dataset size; cache and provenance | Online/offline behavior, response retention, rate limits, dataset version |
| Large cohort analysis | Aggregate storage, metadata operations, parallel task count, scheduler throughput | Cohort size, fan-out, queue delay, failure rate and aggregate I/O |
| Reanalysis | Historical data access, immutable resource versions, reproducible environment | Re-run with pinned historical tool/reference/cache versions |
| GPU/FPGA workloads | Accelerator model, driver/runtime compatibility, device availability | Exact hardware/software pair, concurrency, correctness and fallback behavior |

**Sizing policy:** publish measured profiles (for example, task-specific small/medium/large resource classes) only after benchmark runs on named hardware/software/storage combinations. Do not advertise an arbitrary CPU/RAM threshold as suitable for all WGS, WES, panel, cohort or clinical workflows.

## 6. Proposed SIRALOOM architecture-neutral contract

This is a requirements proposal, not a change to the current execution architecture.

### 6.1 Separate six identities

1. **Environment identity:** customer/tenant owner, registered version, lifecycle state and qualification evidence.
2. **Host/platform identity:** OS, distribution, kernel, architecture, host/cluster identity and relevant capabilities.
3. **Scheduler identity:** scheduler type/version, cluster/partition/queue and scheduler job ID.
4. **Runtime identity:** Docker/Podman/Apptainer/Kubernetes runtime and exact version/configuration.
5. **Scientific tool identity:** executable or image digest, tool/version/build, reference/cache/profile identities and approved operations.
6. **Storage identity:** storage backend/profile, mount or object-store generation/version, staging policy and data locality.

These identities must be bound to an immutable execution snapshot. A mutable environment registration must not retroactively rewrite the provenance of a completed run.

### 6.2 Execution request and result

Every task request should declare:
- Tenant, case, optional analysis and workflow/task identity.
- Approved environment registration/version and qualification status.
- Exact tool/image identity and allowed operation.
- CPU, memory, wall-time, scratch, PID and accelerator requests.
- Input/resource artifact references with immutable versions and expected hashes.
- Output declarations, publication policy and expected metadata.
- Network/egress policy and scoped secret references (never secret values).
- Idempotency identity, retry policy and cancellation policy.

Every result should record:
- Scheduler job ID and worker/host identity.
- Runtime and image digest actually used.
- Actual tool executable/version/digest and resource identities.
- Start/end timestamps, exit status, signal/timeout/OOM state.
- Requested and observed resource usage where available.
- Input/resource/output hashes and publication receipt.
- Logs, retry/lease history, cancellation and recovery events.
- Environment snapshot and qualification evidence references.

### 6.3 Adapter boundaries

Keep these as independent adapter interfaces:
- **Workflow adapter:** Nextflow, Cromwell/WDL, Snakemake, CWL runner.
- **Scheduler adapter:** local queue, Slurm, LSF, PBS, Kubernetes, cloud batch.
- **Runtime adapter:** Docker, Podman, Apptainer; Kubernetes runtime is mediated by the Kubernetes adapter.
- **Storage adapter:** local/shared filesystem, NFS/parallel filesystem, S3/GCS/Azure Blob and customer object stores.
- **Agent/control-plane adapter:** enrollment, mutual authentication, heartbeat, revocation, job polling and remote cancellation.

A workflow engine should not need to know how SIRALOOM stores clinical evidence; a scheduler should not decide whether a tool version is scientifically qualified; a runtime should not independently authorize a clinical workflow.

## 7. Requirements and gap matrix

**Status vocabulary:** Implemented in open PR = code exists in an unmerged draft; partial = only a subset exists; not evidenced = no sufficient repository evidence yet; externally qualified = must be proven on customer/site infrastructure, not inferred from CI.

| ID | Priority | Requirement / acceptance outcome | External production evidence | SIRALOOM evidence at research baseline | Gap / closure evidence |
|---|---|---|---|---|---|
| ENV-R01 | P0 | Separate API/orchestration services from scientific workers | Terra separates UI/workflow services from Batch workers | #300 draft separates tool-neutral API image from scientific worker images | Integrate and verify stack; test API image cannot execute scientific binaries |
| ENV-R02 | P0 | One tool-neutral execution contract for all scientific tools | Nextflow/Cromwell dispatch tasks to different backends | #301 draft defines tool/request/resource/artifact/provenance contracts and local executor | Audit every scientific subprocess; no bypass when governed execution is required |
| ENV-R03 | P0 | Immutable, tenant-owned environment registration and versions | Commercial platforms maintain project/worker execution contexts | #305/#306 drafts define environment contracts and append-only registrations | Complete lifecycle APIs, RBAC, qualification evidence, suspension/revocation/decommission and audit |
| ENV-R04 | P0 | Case-scoped execution before Analysis exists | Clinical VCF intake occurs before analysis creation | #309 draft adds case-scoped ledger schema | Prove actual intake worker resolves organization environment and creates/updates execution records end to end |
| ENV-R05 | P0 | Mandatory governed execution for controlled workflows | Managed platforms dispatch all workflow tasks through managed execution | #307 integration is opt-in; legacy subprocess fallback remains for non-mandatory callers | Enumerate all process launches; enforce policy centrally; fail closed for clinical/qualified workflows |
| ENV-R06 | P0 | Input staging and output publication are integrity checked and atomic | Terra/Batch and cloud platforms stage inputs and persist outputs | #306/#310 provide parts; repository roadmap records object-store byte verification and atomic publication as open | Verify bytes after staging and before use; generation-pinned object reads; atomic publish/commit; recovery tests |
| ENV-R07 | P0 | Exact container/runtime/tool identity and qualification | OCI images and task-specific execution environments are standard | #301/#305/#310 drafts; #321 runtime attestation work | Bind actual host/runtime/image/tool/resource identity to signed qualification evidence; broaden beyond CI runner |
| ENV-R08 | P1 | Docker/Podman customer-owned execution with strong isolation | Common customer-managed Linux container model | #310 draft includes digest pinning, non-root, read-only mounts/rootfs, offline network and cgroup limits | Qualify customer OS/kernel/rootless modes, storage drivers, resource policies and operational recovery |
| ENV-R09 | P1 | Apptainer execution for HPC without privileged Docker | NIH uses Apptainer; Nextflow documents Apptainer execution | No completed Apptainer scheduler/runtime adapter established in current PR chain | Add and qualify Apptainer adapter, OCI-to-SIF provenance, bind-mount semantics, non-root identity and site-policy tests |
| ENV-R10 | P1 | Scheduler adapter for Slurm | NIH Biowulf uses Slurm; Nextflow submits via sbatch | Contract names scheduler identity; no completed SIRALOOM Slurm dispatch adapter evidenced | Submit/poll/cancel/reconcile, partitions, CPU/memory/time, arrays, job accounting, duplicate/retry and scheduler outage tests |
| ENV-R11 | P1 | Scheduler adapter for IBM Spectrum LSF | Sanger Farm documents LSF | No completed SIRALOOM LSF adapter evidenced | LSF submit/status/cancel, queue/resource mapping, job identity, retries and integration tests |
| ENV-R12 | P1 | Additional schedulers/cloud batch adapters | Nextflow and managed cloud platforms support multiple backends | Not established as complete | Prioritize PBS/HTCondor/Kubernetes/cloud batch based on customer demand; adapter conformance suite |
| ENV-R13 | P1 | Resource reservations, quotas and fair scheduling | HPC/cloud batch allocate resources per task and queue | #305 capacity contract; #310 per-container CPU/memory/PID limits; centralized leases not evidenced | Atomic CPU/RAM/scratch/GPU/concurrency reservations; quotas; expiry/fencing; tenant fairness and exhaustion tests |
| ENV-R14 | P1 | Shared filesystem and parallel filesystem support | NIH/Sanger use high-performance shared storage | Storage profile declarations exist in #305; end-to-end storage adapters not established | Validate NFS and representative parallel FS semantics, permissions, symlinks, locks, throughput and scratch cleanup |
| ENV-R15 | P1 | Object storage and cloud data staging | Terra and HealthOmics use cloud object storage | Cloud staging and object-byte re-verification remain open in roadmap | Versioned object reads, multipart upload, checksum verification, atomic publication, retries and lifecycle cleanup |
| ENV-R16 | P1 | Secure remote agents and customer-site connectivity | Customer-owned HPC requires a controlled submission/agent boundary | #305 excludes enrollment/mTLS/signed heartbeat; #321 host broker does not equal fleet control plane | Enrollment, workload identity, mTLS, key rotation/revocation, signed heartbeat, replay protection and offline behavior |
| ENV-R17 | P1 | Scoped secret/credential delivery | Cloud services use identity/permissions to access storage and registries | Complete secret delivery not evidenced | Short-lived task-scoped credentials; no argv/env/log leakage; rotation/revocation and audit |
| ENV-R18 | P1 | Cancellation, retries, idempotency and worker-loss recovery | Terra/HealthOmics/DNAnexus maintain task/job lifecycle | #306 ledger includes fenced leases; #310 says worker-loss recovery remains separate | Kill worker/host mid-run; prove stale worker cannot publish; reconcile orphaned scheduler jobs; retry safely |
| ENV-R19 | P1 | Multi-architecture qualification | SIRALOOM has ARM64 candidate work; HPC fleets may be heterogeneous | #312 draft has three ARM64 candidate BCFtools profiles | Keep candidate until cross-version dispatch, isolation, retry/recovery, scientific concordance and performance qualification pass |
| ENV-R20 | P1 | Tool-specific data/cache/reference binding | VEP and genomics tools require exact caches/references | #313 draft mounts verified VEP cache; BCFtools profiles exist | VEP version × assembly × cache × architecture matrix; reference identity and cache byte checks at use time |
| ENV-R21 | P1 | Environment lifecycle and qualification expiry | Institutional systems maintain controlled operational configurations | Immutable registration/status primitives exist; full lifecycle not evidenced | Register → qualify → activate → suspend/revoke → decommission; invalidate qualification on OS/kernel/runtime/tool/storage changes |
| ENV-R22 | P1 | Monitoring and audit | Institutional HPC and cloud systems expose job status, usage and logs | Execution ledger records provenance primitives; full environment operations surface not evidenced | Environment health, capacity, queue, worker heartbeat, runtime drift, job logs, usage, alerts and immutable audit |
| ENV-R23 | P2 | Customer installation, upgrade, rollback and offline deployment | On-premises customers need controlled lifecycle | Docker/Compose boundary exists; complete installation/upgrade bundle not evidenced | Signed deployment bundle, preflight, backup, migrations, rollback, offline registry/image import and support runbook |
| ENV-R24 | P2 | Performance, capacity and cost attribution | HPC/cloud platforms track resource consumption | Resource contracts exist; representative benchmark suite not evidenced | Publish reproducible WES/WGS/VCF/annotation benchmark data with host/tool/reference/storage details |
| ENV-R25 | P2 | Workflow standards interoperability | Nextflow/Cromwell/HealthOmics support standard workflow languages | Strategic roadmap already calls for CWL, GA4GH TRS/TES/WES/DRS, Nextflow and Snakemake evaluation | Define supported import/export/API conformance and test workflows across multiple backends |
| ENV-R26 | P2 | Disaster recovery and durable long-term storage | Sanger documents off-site data-centre DR and long-term storage | Platform roadmap includes recovery; environment-specific DR not established | Backup/restore, replication, retention, archive retrieval, recovery objectives and periodic restore tests |

## 8. Current SIRALOOM execution work: what exists versus what it does not prove

The following is a reconciliation of the current repository engineering roadmap and draft PR descriptions, not a claim that the PRs are merged or production-qualified.

| PR | Draft scope | Evidence it contributes | What it does not establish |
|---|---|---|---|
| #297 | Durable artifact validation workers | Merged parent foundation for #300 | Complete environment control plane |
| #300 | API/worker image separation | Tool-neutral API image vs scientific worker images | Remote agents, schedulers or multi-host execution |
| #301 | Tool execution contract/local executor | Request, identity, resources, artifacts, provenance, process controls | Persistent production lifecycle or remote execution |
| #305 | Environment/capacity contracts | Tenant-owned environment and compatibility contracts | Provisioning, enrollment, mTLS, capacity enforcement |
| #306 | Environment registration/execution ledger | Versioned snapshots, idempotency, fenced leases, durable provenance | End-to-end dispatch, atomic object publication, admin lifecycle |
| #307 | Persistent BCFtools/VEP adapters | Persistent bridge and workflow adapter integration when assigned environment is configured | Mandatory use everywhere; intake execution; remote scheduler |
| #308 | More BCFtools paths | Additional normalization/index/attestation operations | Intake execution context |
| #309 | Case-scoped execution records | Persistence model for pre-Analysis case work | Proof that intake worker uses it end to end |
| #310 | Linux OCI executor | Docker/Podman isolation and live CI runtime tests on a specific Linux runner | Apptainer, Slurm/LSF, customer host matrix, worker-loss recovery |
| #312 | ARM64 BCFtools candidates | Native ARM64 build/smoke evidence | Production ARM64 promotion or VEP ARM64 |
| #313 | VEP cache mount correction | Verified cache directory passed as read-only resource | Full VEP version × architecture profile registry |
| #321 | Clinical integration and runtime trust work | Some Docker/bare-metal/Kubernetes runtime identity/attestation work | Complete environment provisioning/control plane or Kubernetes/Slurm job execution |

**Stack rule:** #300 → #301 → #305 → #306 → #307 → #308 → #309 → #310 → #312 → #313 is a dependent series; #297 is the merged parent baseline. The roadmap records these PRs as open drafts except #297. They must be reconciled as a coherent series with #321, migrations and existing safeguards. No child PR should be merged independently of its prerequisites.

## 9. Recommended product sequence

### Phase A — Foundation for the first customer-owned deployment

- Keep the tool-neutral API/scheduler service separate from scientific workers.
- Complete the common execution request/result contract and durable ledger.
- Complete Docker/Podman execution on supported Linux x86_64 hosts.
- Make persistent execution mandatory where clinical or qualified-workflow policy requires it; remove silent fallback.
- Route pre-analysis VCF and index validation through case-scoped execution and explicit organization environment assignment.
- Finish storage staging, byte verification, atomic publication, scoped credentials, quotas, cancellation and worker-loss recovery.
- Provide an operator-controlled environment registration, qualification, activation, suspension and revocation lifecycle.

### Phase B — Institutional HPC

- Add a remote, customer-controlled submission/agent boundary.
- Implement Slurm adapter first, then LSF based on institutional demand.
- Add Apptainer runtime adapter; do not require Docker daemon/root on compute nodes.
- Validate shared/parallel filesystem, transfer-node and scratch behavior.
- Test queue wait, scheduler outages, cancellation, requeue, node failure and duplicate submissions.
- Qualify actual customer cluster profiles; CI on a hosted runner is not sufficient.

### Phase C — Kubernetes and cloud batch

- Add Kubernetes dispatch separately from container runtime attestation.
- Add customer-controlled AWS Batch / Google Cloud Batch / Azure Batch adapters where demanded.
- Add object-storage staging, workload identity, data locality, lifecycle and cost accounting.
- Keep SIRALOOM cloud hosting deferred; customers can bring their own cloud account.

### Phase D — Advanced environments

- Qualify ARM64 profiles for specific tools and workflows.
- Add GPU/FPGA profiles only for workflows that benefit and only with tool/hardware validation.
- Add performance/cost benchmark catalogues, environment marketplace and federation after identity, capacity, isolation and provenance are stable.

## 10. Non-negotiable acceptance gates

No environment should be marked **qualified** merely because a container starts or a unit test passes.

1. **Identity:** exact host/OS/kernel/architecture, scheduler, runtime, image, tool, reference/cache and storage profile are recorded.
2. **Integrity:** inputs/resources are hash-verified after staging and immediately before use; outputs are verified before atomic publication.
3. **Isolation:** tenant boundaries, filesystem mounts, network egress, UID/GID, CPU/RAM/PID/scratch and secrets are tested adversarially.
4. **Lifecycle:** environment qualification is invalidated by material changes; suspension/revocation prevents new jobs and has defined in-flight behavior.
5. **Reliability:** scheduler/worker/host loss, timeout, cancellation, retry, duplicate dispatch and stale-worker publication are tested.
6. **Scientific correctness:** reference-backed test data, expected outputs, version concordance and reproducibility are verified for each tool/profile.
7. **Operations:** logs, metrics, audit, backup/restore, upgrades and rollback are tested on the target customer environment.
8. **Clinical boundary:** software qualification is not laboratory validation, assay validation, or authorization for clinical reporting. Those require separate laboratory governance and validation evidence.

## 11. Decisions recommended for SIRALOOM

1. Adopt a **multi-adapter execution architecture**, not Docker-only or cloud-only.
2. Keep **customer-owned Linux/Docker** as the first implementation target because it matches the current funding and engineering direction.
3. Design the contract now so that **Apptainer + Slurm and Apptainer + LSF** can be added without redesigning the common execution ledger.
4. Treat **Kubernetes runtime attestation and Kubernetes scheduler dispatch** as different capabilities.
5. Make **storage and data staging first-class adapters**; filesystem semantics and object-store publication are as important as CPU execution.
6. Do not set universal hardware minimums. Publish measured workload profiles after representative benchmarks.
7. Keep hosted SIRALOOM cloud, global federation and broad marketplace execution as later stages.

## 12. Research limitations and next verification

- Institutional pages describe particular systems and may change; their node counts and hardware inventories are snapshots, not a market-wide specification.
- Vendor platform documentation explains product architecture, not every customer's exact production configuration.
- The DRAGEN v3 guide is a model-specific historical hardware document and is not a recommended baseline.
- The SIRALOOM status column is based on the current engineering master roadmap and draft PR descriptions; every PR's latest head, CI, branch base, changed files and migration compatibility must be refreshed before integration.
- No production customer environment has been inspected or qualified as part of this research.

**Next repository verification:** refresh the latest status and head SHA of #300–#313 and #321; inspect their branch bases, migrations, runtime tests and intake dispatch call sites; then create an integration/qualification plan. Do not merge, deploy, or change the execution architecture as part of this research document.
