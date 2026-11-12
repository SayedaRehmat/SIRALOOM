# SIRALOOM Variant — Execution Platform Audit for Lab Server Release

**Audit date:** 2026-11-12  
**Product:** SIRALOOM Variant — germline SNV/small-indel interpretation  
**Deployment target:** Lab Server first  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Status:** Source/PR evidence review; no local integrated build or test execution performed  
**Related architecture:** `docs/product/SIRALOOM_VARIANT_DEPLOYMENT_AND_UPGRADE_ARCHITECTURE.md`  
**Related baseline:** `docs/engineering/MASTER_DEFECT_REGISTER_AND_DEPENDENCY_MAP.md`

This audit distinguishes code present in open pull requests from code integrated into the product baseline. The reviewed execution PRs are open drafts, mostly stacked on one another; their existence is not proof that the current integration branch contains or executes them. Tests described below are tests present in PR diffs, not tests run during this audit.

## 1. Executive finding

SIRALOOM already has meaningful building blocks for the execution platform: scientific tool profiles, a lab execution-environment contract, immutable environment registration, a durable tool-execution ledger, BCFtools/VEP adapters and a fail-closed Linux OCI executor.

**It does not yet have a complete Lab Server installation-to-qualified-execution lifecycle.** The most important gaps are:

1. Persistent execution is opt-in; legacy workflow execution remains available unless a per-analysis configuration flag is set.
2. The persistent adapter work covers BCFtools normalization and VEP annotation, not every scientific execution or pre-analysis VCF intake path.
3. The environment registry is a domain contract plus persistence functions; a complete authenticated administration/registration/qualification lifecycle is not established by the reviewed changes.
4. Environment snapshots are substantial, but the reviewed request snapshot does not itself bind the scientific-tool registry file/version/digest or a first-class workflow definition version/digest. Resource bindings contain ID/version/SHA/assembly, but complete immutable release identity must be verified across all workflow paths.
5. The OCI executor is a real foundation, but remote agents, Kubernetes, Slurm and a general cluster control plane are not established.
6. The execution PR stack has migration-number collisions with the clinical integration PR and cannot simply be merged as currently numbered.

The correct next step is a controlled integration and gap-closure program, not another registry or a second execution engine.

## 2. Reviewed source and PR evidence

### 2.1 PR #305 — environment contract

**PR:** [#305](https://github.com/SayedaRehmat/SIRALOOM/pull/305), open draft  
**File:** `backend/app/domain/execution_environments.py`  
**Test:** `tests/test_execution_environments.py`

The contract models:
- Environment ID and profile version.
- Owner scope (SIRALOOM or laboratory) and organization binding.
- Executor kind (local process, container, remote agent).
- OS, platform, architecture and kernel.
- Runtime kind/version and pinned runtime image digest.
- Scheduler, capacity, workspace, storage profile IDs.
- Explicit supported tool-profile IDs.
- Network/egress policy and remote-agent identity/heartbeat.
- Qualification status.

Compatibility checks require a qualified environment and software-qualified tool, explicit tool-profile allowlisting, matching platform and runtime image digest. The in-memory registry checks tenant access and tool compatibility. A snapshot method captures environment identity and configuration.

**Limit:** The module's own docstring says it is a domain contract, not a remote execution agent or provisioner; persistent registration and agent heartbeats are separate work. A helper to check heartbeat freshness is not agent enrollment, authenticated heartbeat, revocation or remote command transport.

**Tests in PR:** tenant isolation, environment qualification, tool-profile allowlist, container image digest, heartbeat freshness and offline-egress constraints. These are source-level test additions; not executed in this audit.

### 2.2 PR #306 — persistent registration and execution ledger

**PR:** [#306](https://github.com/SayedaRehmat/SIRALOOM/pull/306), open draft  
**Files:** `backend/app/domain/execution_persistence.py`, `backend/app/infrastructure/db/models.py`, `migrations/versions/0063_execution_environment_provenance.py`  
**Tests:** `tests/test_execution_persistence.py`, `tests/test_execution_persistence_migration.py`

The persistence layer:
- Registers an environment profile as a tenant-bound immutable snapshot.
- Fingerprints canonical profile JSON.
- Makes identical registration idempotent and rejects changed content under the same environment/version.
- Persists tool identity, version, profile ID, executable digest, platform and operation.
- Persists request/environment snapshots, input/output manifests and execution provenance.
- Records PENDING/RUNNING/SUCCEEDED/FAILED/INTERRUPTED states, attempts, fenced worker leases, timestamps and error details.
- Checks environment ownership, qualification, allowlisted tool profile, platform and runtime image identity at registration of an execution.

**Important model observation:** In the PR #306 initial migration/model, `ToolExecutionRecord.analysis_id` is non-nullable. PR #309 later changes execution to support case-scoped records with optional analysis ID. That change is required for VCF intake before an Analysis exists.

**Limit:** This is persistence and validation logic, not a complete environment-management API/UI, credentialed host discovery, qualification evidence review, suspend/revoke workflow, capacity reservation service or installer.

**Snapshot completeness gap:** The request snapshot in `PersistentToolExecutionService._canonical_request_snapshot()` includes workflow ID, operation, arguments, timeout, request environment and resource bindings (resource ID/version/SHA/assembly). The reviewed code does not demonstrate a first-class immutable workflow definition digest/version, a pinned scientific-tool registry release digest, or a complete source-resource release artifact identity in every execution record. The environment snapshot is persisted separately. These bindings must be completed and checked at dispatch and use time.

### 2.3 PR #307 — persistent BCFtools/VEP adapters

**PR:** [#307](https://github.com/SayedaRehmat/SIRALOOM/pull/307), open draft  
**Files:** `backend/app/domain/persistent_tool_executor.py`, `backend/app/domain/vcf_tools.py`, `backend/app/adapters/annotation/vep.py`, `backend/app/workflows/variant.py`  
**Design note:** `docs/engineering/PERSISTENT_EXECUTION_ADAPTER_INTEGRATION.md`

The common executor service validates request/profile, resolves a registered environment, persists the execution record, claims a fenced lease, executes, verifies output checksums and records terminal provenance. When no executor is supplied, the persistent service reconstructs the registered environment snapshot and selects an environment-aware executor.

The workflow helper `_persistent_tool_execution_service()` reads:
- `execution_environment_registration_id`
- `require_persistent_tool_execution`

If the mandatory flag is true and no environment registration is assigned, the workflow fails closed. If the flag is false and no registration is assigned, the helper returns `None` and legacy execution remains possible. The PR design note explicitly documents this transitional compatibility mode.

Adapter coverage in the PR:
- BCFtools VCF normalization and related operations can use the persistent executor when supplied.
- VEP annotation can use the persistent executor when supplied.
- Execution record IDs are attached to selected normalized/output artifacts and annotation checkpoints.

**Release blocker:** This is not a universal execution boundary. It does not prove every scientific executable, intake validation worker, reference/resource staging operation or future workflow is routed through the persistent executor. The VCF intake/validation path must be traced separately because it can run before an Analysis exists.

**Tests in PR:** fake-executor adapter tests and request-construction tests are present. The design note itself says these do not establish real laboratory executable digests, OCI image qualification, scheduler behavior, resource limits or clinical suitability.

### 2.4 PR #309 — case-scoped execution

**PR:** [#309](https://github.com/SayedaRehmat/SIRALOOM/pull/309), open draft  
**Files:** `backend/app/domain/execution_persistence.py`, `backend/app/domain/persistent_tool_executor.py`, `backend/app/infrastructure/db/models.py`, `migrations/versions/0064_case_scoped_tool_executions.py`

This extends the persistence identity to include a required case ID and optional analysis ID. It is necessary for intake/validation executions that occur before analysis creation.

**Limit:** The schema capability alone does not prove the VCF intake worker is actually routed through the persistent executor. That requires call-site wiring and tests for pre-analysis execution, case/organization authorization and retries.

### 2.5 PR #310 — Linux OCI executor

**PR:** [#310](https://github.com/SayedaRehmat/SIRALOOM/pull/310), open draft  
**Files:** `backend/app/domain/container_tool_execution.py`, `backend/app/domain/persistent_tool_executor.py`, `tests/test_container_tool_execution.py`, `tests/integration/test_linux_container_runtime_qualification.py`  
**Design note:** `docs/engineering/LINUX_OCI_CONTAINER_EXECUTION.md`

The PR adds a Docker/Podman Linux executor foundation with pinned image identity, no runtime image pull, read-only root filesystem, explicit input/output/resource mounts, offline networking, non-root execution, resource limits, timeout cleanup and output verification. The persistent service is adapted to choose an environment-aware executor when one is not injected.

The PR adds mocked executor tests and a real-runtime qualification workflow for Docker/Podman on a defined Ubuntu Linux x86_64 CI host. That is useful runtime evidence, but it is not a qualification matrix for arbitrary customer kernels, rootless Podman, storage drivers, cgroup modes, SELinux/AppArmor policies or hardware.

**Not implemented by this PR:** remote-agent transport/enrollment, Kubernetes job execution, Slurm dispatch, cloud object-store staging/recovery or a general cluster scheduler/control plane. The environment contract's scheduler enum is not evidence those adapters exist.

### 2.6 PR #315 — scientific tool-profile registry

**PR:** [#315](https://github.com/SayedaRehmat/SIRALOOM/pull/315), open draft  
**Files:** `configs/bioinformatics/scientific-tool-profiles.v1.json`, `backend/app/domain/scientific_tool_profiles.py`, `tests/test_scientific_tool_profiles.py`

The registry represents tool ID/version, platform/architecture, execution methods, dependencies, executable identity/digest policy, installation/lock metadata, resource requirements, routing and qualification state.

The registry has BCFtools and Ensembl VEP profiles. Tests describe software-qualified Linux x86_64 BCFtools profiles, candidate ARM64 BCFtools profiles and a candidate VEP 115.2 profile. Candidate profiles are rejected by the normal qualified resolver.

**Important distinction:** software qualification is not environment qualification, assay validation or clinical validation. Tool-profile resolution and environment resolution are separate checks connected by the tool profile ID; the overall execution plan must compose them in one mandatory orchestration boundary.

**Versioning gap:** the reviewed resolver loads a JSON registry from a path. The execution snapshot must record the exact registry artifact digest/release ID and resolved profile content, not merely a profile ID that may resolve differently after a registry file changes.

## 3. Integration collision and dependency findings

### 3.1 Stacked execution PRs

The reviewed chain is:
- #305 environment contract.
- #306 persistent environment registration and execution ledger.
- #307 BCFtools/VEP adapters.
- #308 expanded BCFtools operations.
- #309 case-scoped execution.
- #310 OCI executor.
- #312 ARM64 qualification candidates.
- #313 VEP cache mount.
- #315 tool-neutral profile registry (based on the #313 stack).

These are dependent changes. They should be reconciled and tested as one ordered integration series, not merged independently into the product baseline.

### 3.2 Migration-number collision with PR #321

This is a concrete integration blocker:
- PR #306 introduces `migrations/versions/0063_execution_environment_provenance.py`.
- PR #309 introduces `migrations/versions/0064_case_scoped_tool_executions.py`.
- PR #321 independently includes `0063_clinical_requests_accession.py` and `0064_accession_procedure_approval.py`, followed by further migrations.

Therefore the stacked execution migrations cannot be applied unchanged alongside the PR #321 migration chain. Before integration, create one ordered Alembic history, renumber/rebase the execution migrations after the clinical integration migrations (or otherwise reconcile the dependency graph), verify every `down_revision`, and run upgrade from the supported baseline plus upgrade from the previous release. Never resolve this by deleting a migration or bypassing migration checks.

### 3.2.1 Exact revision graph and safe target sequence (verified 2026-11-12)

The current PR #321 integration branch is at `f9cb4cd11ea4f8c5c9cf58b4061b774e87ae98b2`. Its migration chain, as present on that exact branch, is:

```text
0061_analysis_toolchain_profiles
  -> 0062_artifact_validation_dispatches
  -> 0063_clinical_requests_accession
  -> 0064_accession_procedure_approval
  -> 0065_case_accession_reconciliation
  -> 0066_assay_version_governance
  -> 0067_assay_validation_lifecycle
  -> 0068_evidence_response_artifacts
  -> 0069_provider_retention_approvals
  -> 0070_resource_release_artifacts
```

The execution stack's current migration declarations are:

- #306: `revision = "0063_execution_environment_provenance"`, `down_revision = "0062_artifact_validation_dispatches"`.
- #309: `revision = "0064_case_scoped_tool_executions"`, `down_revision = "0063_execution_environment_provenance"`.

The migration files are not semantically interchangeable with the clinical revisions at 0063/0064. The collision is in the Alembic revision namespace and graph, not simply a Git filename issue. The clinical branch already uses 0065–0070, so renumbering the execution migrations to 0065/0066 would also collide.

**Proposed target when the two stacks are reconciled:** preserve the clinical chain unchanged through 0070, then append:

```text
0070_resource_release_artifacts
  -> 0071_execution_environment_provenance
  -> 0072_case_scoped_tool_executions
```

The execution migration files must be renamed and their `revision`/`down_revision` declarations changed consistently. All references to the old revision IDs in migration tests, migration fixtures, docs and CI scripts must be searched and updated. The #309 migration's data backfill and database-specific trigger recreation must be retained. The #306 migration's tables, constraints, indexes and append-only/immutability triggers must be preserved.

**Critical sequencing constraint:** do not simply edit the #315 stacked branch's migrations to depend on 0070 while that branch's own parent history lacks PR #321. That would make the execution stack un-upgradable on its own and would hide a dependency on a different PR. The integration must be a deliberate combined tree/branch based on #321 (or a new integration branch whose ancestry includes both stacks), with the execution code and models reconciled against the #321 versions. The #321 `models.py` and execution-stack `models.py` changes overlap and must be merged semantically, not copied wholesale.

**Required migration verification before integration is accepted:**

1. Enumerate every revision in the combined tree and assert unique revision IDs and exactly one intended head.
2. Assert the full `down_revision` chain is resolvable from the supported baseline.
3. Compare SQLAlchemy model metadata with the resulting schema, including nullable `analysis_id`, required `case_id`, both foreign keys and execution-ledger constraints.
4. Upgrade an empty database from the supported baseline to head on PostgreSQL and SQLite.
5. Upgrade a database stamped at the previous supported release to head on PostgreSQL and SQLite.
6. Exercise the #309 case backfill against representative existing execution rows before making `case_id` non-null.
7. Verify PostgreSQL and SQLite trigger behavior after both migrations.
8. Run downgrade only where the migration's data-safety guards permit it; do not claim rollback if historical execution records prevent downgrade.

No migration has been rewritten or applied by this audit update. This section records the verified graph and the safe target sequence; code integration and database execution remain pending.

### 3.3 PR #321 runtime attestation is related but not a replacement

PR #321 adds `runtime_attestation.py` and a six-component runtime identity/assay binding for clinical execution. That is a separate and important clinical authorization layer. It does not replace environment registration, durable tool execution records, container isolation, tool-profile resolution or scheduler/worker lifecycle. The two mechanisms must be composed without contradictory identity sources.

## 4. Current Lab Server readiness assessment

| Requirement | Evidence found | Assessment for first Lab Server release |
|---|---|---|
| Linux x86_64 deployment documentation | `docs/DEPLOYMENT.md`, Docker backend/Compose deployment foundation | Partial; not a customer installer |
| Containerized API/worker services | Existing deployment guide and production Compose concepts | Foundation present; clean-host installation/qualification not proven |
| PostgreSQL and Redis configuration | Deployment guide documents required services, Redis AUTH and production secrets | Partial; customer lifecycle and restore validation needed |
| Customer-controlled artifact/reference storage | Deployment guide documents local/cloud targets and reference FASTA/FAI | Partial; backup, restore, capacity and access-boundary qualification needed |
| Environment profile contract | PR #305 | Implemented in open PR; not integrated |
| Persistent environment registration | PR #306 | Implemented in open PR; migration collision |
| Case-scoped intake execution | PR #309 | Schema/service foundation in open PR; callsite routing unverified |
| Mandatory persistent execution for every workflow | PR #307 uses opt-in configuration | Not satisfied |
| BCFtools persistent adapter | PR #307, expanded in #308 | Partial adapter coverage |
| VEP persistent adapter | PR #307 and cache mount #313 | Partial; candidate VEP profile remains unqualified in #315 |
| Linux Docker/Podman isolation | PR #310 | Foundation; defined CI host qualification only |
| Complete resource/tool/workflow snapshot | PR #306 request/environment snapshot | Partial; registry release and workflow definition digests need explicit binding |
| Installer and preflight | No customer-facing Lab Server installer evidenced in reviewed deployment guide | Missing |
| Signed release bundle/SBOM | Not evidenced in reviewed deployment docs or PRs | Missing |
| Upgrade compatibility manager | Migrations exist; no signed product/capability manifest and promotion manager evidenced | Missing |
| Backup/restore and rollback qualification | Operational docs are not sufficient evidence of tested customer restore/rollback | Unverified / release gate |
| Customer environment lifecycle UI/API | Persistence helpers exist; complete authorized administration workflow not evidenced | Missing/partial |
| Support matrix and clean-host acceptance | Not evidenced | Missing |

## 5. Required Lab Server support profile — proposed first qualification target

Start with one deliberately narrow support profile:
- Linux x86_64 host.
- One dedicated physical server or VM.
- Docker Engine initially; Podman added only when the same installation and lifecycle suite passes.
- PostgreSQL and Redis on the same host for the first small-lab profile, with persistent volumes and documented backup.
- Separate API and background worker containers.
- Local customer-owned artifact/reference storage with explicit filesystem ownership and backup policy.
- Offline-by-default scientific execution; provider network access only through explicit approved egress configuration.
- A single organization/site per initial installation unless multi-tenant isolation is separately qualified.
- One exact BCFtools profile initially; VEP enabled only after its complete tool/cache/container qualification matrix passes.
- No Kubernetes, Slurm, remote agents or hosted SIRALOOM dependency in the first Lab Server acceptance profile.

CPU, RAM, disk minima, maximum concurrency, maximum VCF size and performance claims must be derived from reproducible representative benchmarks; do not invent minimum hardware specifications before measurement.

## 6. Required closure work and acceptance criteria

### ENV-LS-01 — Integrate execution PR chain safely
- Reconcile PR dependency chain with PR #321.
- Resolve migration 0063/0064 collisions and Alembic lineage.
- Verify model/migration parity and clean upgrade paths.
- Run complete backend, migration, integration and container-runtime CI on the exact integrated SHA.

**Acceptance:** no duplicate migration revisions; upgrade succeeds from the supported prior baseline; rollback/restore strategy is documented and tested; exact-head CI evidence retained.

### ENV-LS-02 — Mandatory execution-plan resolver
Create one orchestration boundary that resolves and freezes:
- Organization/case/analysis identity.
- Workflow ID/version/source digest.
- Scientific tool profile ID plus exact registry artifact digest/profile content.
- Environment registration ID/version/fingerprint and environment snapshot.
- Tool executable/container digest and dependency identity.
- Resource release ID/version/digest/source artifact identity/assembly.
- Reference package ID/version/digest and relevant index/contig identity.
- Policy/configuration version and request/input manifest.

**Acceptance:** no scientific executable starts if any required identity is absent, unqualified, expired, revoked, incompatible or fails byte verification. Legacy fallback is removed from clinical execution; research-only compatibility must be explicit and separately gated.

### ENV-LS-03 — Route all scientific work through the mandatory boundary
Build a workflow/call-site matrix covering at least:
- VCF upload and pre-analysis structural validation.
- Sample/header/reference checks.
- BCFtools normalization, sorting, compression and indexing.
- VEP or alternative annotation.
- Population providers and their staging/execution tools.
- Evidence acquisition/response processing where executable tools are involved.
- ACMG/manual resume/retry/reanalysis paths.
- Report/provenance export where source artifacts are read.
- Worker redelivery, worker loss and recovery.

**Acceptance:** every executable invocation has a durable execution record and immutable input/output manifests; negative tests prove no legacy process launch occurs when persistent execution is required. Pre-analysis work uses case-scoped identity.

### ENV-LS-04 — Complete registration and qualification lifecycle
- Authenticated organization-scoped registration API and administrator workflow.
- Discovery is not qualification.
- Qualification evidence tied to exact host/runtime/kernel/storage/network/tool profiles.
- Approval, activation, suspension, expiry, retirement and revocation.
- Capacity and concurrency reservation; reject oversubscription.
- Freshness/health monitoring for any remote worker before enabling it.
- Audit actor, reason, evidence and timestamps for every lifecycle transition.

**Acceptance:** unqualified, suspended, retired, stale or cross-tenant environments cannot receive new clinical work; lifecycle race and authorization tests pass.

### ENV-LS-05 — Lab Server installer and release bundle
- Signed release manifest and OCI image digests.
- SBOM, vulnerability evidence and build provenance.
- Preflight for OS/kernel/runtime/resources/network/storage/secrets.
- Installer with explicit confirmation before database initialization/migrations.
- Health/readiness checks for API, worker, DB, queue, artifact and reference resources.
- Secret management and no secrets in images, logs or browser configuration.
- Offline installation bundle and signature verification.
- Customer-owned backup, restore and disaster-recovery runbook.

**Acceptance:** clean supported host can install, restart, upgrade, backup, restore and recover using documented commands; tampered bundle/image and missing dependency tests fail closed.

### ENV-LS-06 — Controlled upgrade manager
- Signed product release and capability manifests.
- Compatibility evaluation for platform/schema/topology/tools/resources/workflows.
- Dry-run migrations and backup gate.
- Staging deployment and golden-dataset regression.
- Separate technical and laboratory approval for clinical-impacting changes.
- Atomic/observable promotion and rollback classification.
- Historical analyses remain bound to original releases; reanalysis creates a new linked record.

**Acceptance:** incompatible upgrade is blocked; rejected promotion leaves production unchanged; approved upgrade is fully audited; rollback is demonstrated for every migration class where rollback is claimed.

### ENV-LS-07 — Scientific and commercial release blockers
- Resolve commercial-use, retention, caching and redistribution terms for GeneBe and every provider/resource.
- Select a commercially permitted annotation strategy.
- Freeze golden datasets and independently reviewed expected outputs.
- Complete intended-use performance and failure-mode validation.
- Publish exact supported VCF/reference/variant-class scope and limitations.

**Acceptance:** no unlicensed provider is required for paid operation; all claimed supported workflows have traceable independent expected-output evidence and laboratory validation materials.

## 7. Explicit non-goals for Lab Server v1

Do not implement or market these as part of the first Lab Server qualification:
- SIRALOOM-hosted SaaS.
- Kubernetes or Slurm.
- Remote execution agents.
- Multi-region high availability.
- Automatic clinical sign-out.
- Automatic reinterpretation of historical reports.
- Unsupported variant classes or unvalidated clinical use.

These can be added later as separately qualified capabilities without changing the core product contract.

## 8. Audit conclusion and next action

The repository contains useful execution-platform components, but the current evidence supports **architecture foundations in open PRs**, not a completed production Lab Server platform. The highest-risk issues are the opt-in execution bypass, incomplete workflow/intake coverage, incomplete release/workflow/resource identity binding, lack of an installer/upgrade manager, and the migration revision collision with PR #321.

**Next engineering sequence:**
1. Reconcile the execution PR stack and Alembic history with PR #321.
2. Close the mandatory execution boundary and case-scoped VCF intake routing.
3. Complete exact execution snapshots and qualification lifecycle.
4. Build the Lab Server signed installer/release bundle and backup/restore workflow.
5. Build controlled upgrade/staging/promotion.
6. Run exact-head CI and clean-host acceptance before calling Lab Server supported.

No source runtime code, tests, migrations, merge or deployment were changed by this audit document. No tests were run in this audit session.
