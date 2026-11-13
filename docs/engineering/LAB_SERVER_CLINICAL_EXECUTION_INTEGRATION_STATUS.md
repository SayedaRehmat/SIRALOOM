# Lab Server execution + clinical integration branch

**Date:** 2026-11-12  
**Current branch head:** `13f20cc73ef778a28b79b324b734d009b94d2003`  
**PR:** #327, open draft, not merged or deployed  
**Status:** source integration advanced; current head has not yet completed CI verification

## 1. Integration strategy

This branch is based on the exact PR #321 clinical-provenance head
`f9cb4cd11ea4f8c5c9cf58b4061b774e87ae98b2`. It preserves clinical intake,
assay validation, runtime attestation, evidence-response retention and
source-release work while integrating the execution stack from the dependent
execution PRs. The source PRs remain unchanged and unmerged.

## 2. Integrated foundations

- Immutable execution-environment registration and durable tool-execution ledger.
- Case-scoped execution records with required `case_id`, nullable `analysis_id`,
  immutable request/environment/input snapshots, output manifests, leases,
  status constraints and indexes.
- Linux OCI Docker/Podman executor, scientific tool identity/profile registry,
  BCFtools profiles, VEP adapter and ARM64 BCFtools candidate build definitions.
- Case-level environment assignment/revocation, restricted to `lab_admin`,
  with audit events.
- A case-bound execution resolver that verifies tenant ownership, registration
  identity, qualification status and profile snapshot consistency.
- Lab Server case execution is restricted to Linux Docker/Podman, offline
  networking, supported single-host schedulers, immutable image digests and
  explicit non-root per-job CPU/memory/PID limits. CPU and memory limits are
  checked against concurrency-adjusted capacity and passed into the OCI
  executor.
- The API/Beat image is separated from the scientific worker image so the
  control plane does not need the scientific toolchain installed.

## 3. Scientific execution routing changes

- Artifact upload persists bytes and queues durable validation; it does not
  perform scientific validation in the API process.
- The artifact-validation worker resolves the case's assigned execution
  environment before VCF or index validation. Missing, unqualified, mismatched,
  cross-tenant, host-process, remote-agent, network-enabled or otherwise
  unsupported environments fail closed.
- VCF validation, index concordance, BCFtools normalization and multiallelic
  splitting require the persistent execution context. Direct BCFtools
  subprocess fallback paths were removed from `vcf_tools.py`.
- VEP annotation and runtime/cache checks require the persistent executor.
  The unregistered VEP subprocess fallback and its transitional opt-in flag
  were removed.
- The workflow resolves a case-bound persistent service before BCFtools
  normalization and injects it into VEP.

This establishes the governed route for the reviewed VCF intake/normalization
and VEP call sites. It does **not** yet prove every scientific provider and
workflow is covered. Population/phenotype providers, evidence retrieval,
ACMG assessment, retries/resume, reanalysis, report export and worker-recovery
routes still require a complete call-site and provenance audit.

## 4. Migration reconciliation

The clinical migration chain is preserved through:

```
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

The integrated execution chain is:

```
0070_resource_release_artifacts
 -> 0071_execution_environment_provenance
 -> 0072_case_scoped_tool_executions
 -> 0073_case_execution_environment
```

Revision `0073` adds the nullable case-to-environment foreign key inline with
the `ALTER TABLE ADD COLUMN` operation. This avoids rebuilding populated
SQLite `cases` tables and disturbing their many inbound foreign keys. The ORM
foreign-key name is aligned with the migration. The prior-release SQLite and
PostgreSQL fixtures seed the actual pre-`0073` schema instead of inserting
through the newer ORM mapping.

Migration/model parity, the backfill, and trigger behavior still need a fresh
run on the current head against both supported databases.

## 5. Test and CI evidence

The first available CI run was on an earlier pre-fix head
(`6ee9d9457fb9c0f2f99d894aa9abaf7de961caa9`), **not** the current branch head:

- Backend suite: 2,313 passed, 68 skipped, 101 failed.
- PostgreSQL migration upgrade step passed, but its dependent integration run
  was cancelled when newer commits were pushed; it is not a completed
  PostgreSQL migration-and-trigger qualification.
- SQLite migration failed because revision `0073` attempted to add a
  foreign key outside batch mode. This has since been corrected in source,
  but not rerun.
- API image build failed because the Debian snapshot source entries were
  incorrectly escaped. This has since been corrected in source, but not rerun.
- Frontend tests/build and Compose validation passed on that earlier head.

The backend failures were largely related to existing unit tests and
qualification fixtures that did not supply the now-required execution context.
A test-only injected executor and updated VEP, BCFtools, artifact-validation,
resource-qualification and migration fixtures have since been added. A
PostgreSQL integration test now creates an isolated database, upgrades a
populated revision-0070 schema through head, verifies case backfill and checks
append-only/state-transition triggers. These changes have **not** yet been
executed on the current head. No passing status is claimed for the updated
code.

## 6. Known release blockers and remaining work

1. Run the complete backend suite on the exact current head; fix failures
   without restoring ungoverned execution.
2. Run PostgreSQL and SQLite upgrades from empty databases and supported
   revision `0070` databases; verify one Alembic head, migration/model parity,
   case backfill, nullable analysis semantics and append-only/state triggers.
3. Run the OCI runtime qualification suite on a real Docker/Podman runner.
4. Finish the repository-wide subprocess and workflow call-site inventory,
   including population/evidence/ACMG/reanalysis/report/retry/recovery paths.
5. Complete environment registration, measured qualification evidence,
   lifecycle/revocation, capacity reservation and health/heartbeat operations.
6. Implement and qualify per-job scratch-disk/storage quotas; the current
   profile records scratch capacity but does not enforce a per-job quota.
7. Deliver the signed Lab Server installer/release bundle, SBOM, preflight,
   offline installation, backup/restore qualification and controlled upgrade
   manager.
8. Resolve commercial-use, caching, retention and redistribution terms for the
   configured GeneBe provider or select a commercially permitted alternative.

The branch is an integration workspace, not a release candidate. It must not
be merged or deployed based on the current state. No merge or deployment
authorization has been given.
