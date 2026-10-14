# SIRALOOM — Phase 1 Results Checkpoint

**Baseline main:** `2efbe032e0320c717b00a6724b1022bf76621c77`

**Working branch:** `audit/phase1-acmg-variant-scope`

## Completed in this checkpoint

1. Read the Phase 1 execution specification and treated it as an implementation/audit instruction rather than a proposal request.
2. Inspected the current repository baseline, release acceptance matrix, latest commits, open PRs and the current queue/workflow implementation.
3. Confirmed that the latest merged main work is the controlled reanalysis output-comparison CLI (`scripts/compare_reanalysis_outputs.py`).
4. Reconciled the open release blockers, including worker-loss recovery, tenant authorization evidence, deployed end-to-end validation, durable storage/restore and scientific truth-set benchmarking.
5. Confirmed a concrete ACMG integrity defect: the explicit ACMG assessment route verified access to the analysis but did not verify that the requested canonical variant belonged to that analysis before creating versioned ACMG/classification state.
6. Implemented a fail-closed analysis-scoped annotation membership guard in `backend/app/api/v1/acmg.py`.
7. Added regression coverage in `tests/test_acmg_variant_scope.py`; the test asserts 404, zero persistence and no evidence query for an out-of-scope variant.
8. Added the required persistent Phase 1 master ledger and end-to-end workflow matrix.

## Changes

- `backend/app/api/v1/acmg.py`
  - Added `Annotation` import.
  - `assess()` now requires an `Annotation` row matching both `analysis_id` and `variant_id` before any ACMG evidence/classification mutation.
  - The guard returns `404 Variant is not part of this analysis` and therefore fails closed without creating audit/classification state.
- `tests/test_acmg_variant_scope.py`
  - New regression test for the exact integrity boundary.
- `docs/engineering/MASTER_AUDIT_AND_REMEDIATION.md`
  - Persistent remediation ledger with evidence, severity, status and next task.
- `docs/engineering/END_TO_END_WORKFLOW_AUDIT.md`
  - Account-to-logout trace matrix with implementation boundaries and evidence status.

## Verification status

### Repository evidence

- Current main revision inspected: `2efbe032e0320c717b00a6724b1022bf76621c77`.
- Current main release documentation still explicitly leaves the release gate open.
- PR #216 provides dispatch-fence regression coverage but is not merged.
- PR #215 provides reanalysis comparison CLI regression coverage but is not merged.
- PR #179's annotation recovery test failed on its tested merge head. The failure must be repaired without weakening its assertions.

### New code test

**NOT RUN locally.** The execution environment could not clone `https://github.com/SayedaRehmat/SIRALOOM.git` because DNS resolution for `github.com` was unavailable. No local pass is claimed.

Required authoritative command in CI/development checkout:

```text
pytest -q tests/test_acmg_variant_scope.py
```

Then run the complete backend suite and the PostgreSQL/Celery integration suite before merge.

## No unsupported claims

This checkpoint does not claim:

- deployed signup/email verification/session-expiry success;
- live cross-tenant denial;
- live GeneBe/gnomAD execution;
- full VCF→report/sign-out completion in a deployed laboratory environment;
- backup/restore success;
- scientific truth-set concordance;
- clinical validity, accreditation or regulatory compliance.

## Exact next task

**Repair and verify stage-body crash/replay, starting with annotation recovery.** Use the current main workflow, not the older PR #179 base, and make the deterministic test reach the actual provider → durable annotation-row commit → injected worker loss boundary. Then redeliver the same durable dispatch and prove one provider call, one logical annotation row, one successful checkpoint and one successful partition completion. After annotation is green, continue the same pattern for population, evidence, ACMG, review, reportability, report/sign-out, provenance export and reanalysis.

In parallel, enumerate every Celery system task and explicitly classify its tenant scope. Dispatch IDs are execution fences, not tenant authorization. Do not mark Phase 1 complete until those checks and the external deployment/scientific gates have evidence.
