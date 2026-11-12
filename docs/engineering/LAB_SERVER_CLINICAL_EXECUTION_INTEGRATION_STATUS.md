# Lab Server execution + clinical integration branch

**Date:** 2026-11-12  
**Status:** Draft integration branch; source integration is partial and not yet tested  
**Clinical source:** PR #321, head `f9cb4cd11ea4f8c5c9cf58b4061b774e87ae98b2`  
**Execution source:** dependent execution stack through PR #315, head `8869c11e8868eed92bd6e9ef7faa3206acc52927`

## 1. Integration strategy

This branch is based on the exact PR #321 head so its clinical intake, assay validation, runtime attestation, evidence-response retention and source-release changes remain present. Execution-stack files were transplanted from the final stacked execution branch. The original draft PRs remain unchanged; no branch was force-pushed and no PR was merged.

## 2. Integrated in this branch

- Environment contract and tool compatibility domain.
- Immutable environment registration and durable tool-execution persistence service.
- Case-scoped execution service/model changes.
- Linux OCI executor and persistent executor service.
- Scientific tool identity, profile registry and toolchain profile configuration.
- BCFtools execution helpers, ARM64 candidate build definitions and profile lock files.
- Execution environment, persistence, container, tool-profile and runtime qualification test files.
- Execution architecture/design documentation.

## 3. Model reconciliation

The clinical branch's complete `backend/app/infrastructure/db/models.py` was retained. The two execution models from the execution-stack head were appended:

- `ExecutionEnvironmentRegistration`
- `ToolExecutionRecord`

The case-scoped model shape is preserved: required `case_id`, nullable `analysis_id`, environment registration foreign key, immutable request/environment/input snapshots, output manifest, lease fields, status constraints and indexes. This is a textual/model reconciliation only; metadata creation and migration parity have not yet been executed.

## 4. Alembic revision reconciliation

The clinical chain is preserved unchanged through:

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

The execution migrations have been added as:

```text
0070_resource_release_artifacts
 -> 0071_execution_environment_provenance
 -> 0072_case_scoped_tool_executions
```

The revision IDs and `down_revision` declarations were changed in the new files. The original `0063` and `0064` execution migration files were not copied into this branch, so the clinical revisions retain their existing IDs. The case-scoped migration body, data backfill, nullable-analysis change, foreign key, and database-specific execution-ledger triggers were carried forward from the execution stack.

## 5. Overlap reconciliation

All four source-stack overlaps have now been reconciled without replacing the clinical branch wholesale:

1. `backend/app/infrastructure/db/models.py` — retained the clinical models and appended `ExecutionEnvironmentRegistration` and `ToolExecutionRecord`.
2. `backend/app/workflows/variant.py` — applied the persistent-execution integration hunks from #307 onto the clinical version. Clinical authorization, runtime attestation, response-retention and source-release logic were preserved by applying context-matched hunks rather than replacing the file. The persistent helper remains transitional/opt-in; this does not yet satisfy ENV-LS-02/03 mandatory routing.
3. `backend/app/adapters/annotation/vep.py` — merged persistent VEP execution and execution-record provenance while retaining the clinical exact raw-response-byte capture and metadata required by the response-retention gate.
4. `tests/test_vep_provider.py` — applied the persistent VEP test additions onto the clinical raw-response-retention tests.

The three runtime/provider/test overlaps are now present together in the integration branch. This is source-level reconciliation; it is not proof that the merged behaviors pass tests or that all VCF intake/scientific callsites are routed through the persistent executor.

## 6. Verification still required

No tests have been run on this combined branch yet. A migration test assertion was added for required `case_id` and nullable `analysis_id`; it still requires execution in CI. Before ENV-LS-01 can be closed:

- Inspect the complete migration graph from the supported baseline and assert one head/no duplicate revisions.
- Run Alembic upgrade on PostgreSQL and SQLite from empty and supported prior-release databases.
- Verify migration/model parity and case backfill with representative rows.
- Verify PostgreSQL and SQLite append-only/state-transition triggers.
- Run backend unit, integration, migration and container-runtime suites on the exact branch head.
- Semantically merge the three remaining overlapping workflow/provider/test files, then repeat CI.
- Review all other changed-file collisions and exact dependency ancestry before proposing any merge.

This branch is an integration workspace, not a release candidate. It must not be merged or deployed based on the current state.
