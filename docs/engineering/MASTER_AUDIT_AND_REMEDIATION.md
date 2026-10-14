# SIRALOOM — Phase 1 Master Audit and Remediation Ledger

**Audit scope:** account creation → organization/tenant isolation → dashboard/navigation → case lifecycle → VCF intake → durable analysis orchestration → annotation/population/evidence → human review → reportability/report → sign-out → audit/provenance → reanalysis → logout.

**Repository:** `SayedaRehmat/SIRALOOM`

**Baseline main SHA:** `2efbe032e0320c717b00a6724b1022bf76621c77` (2026-10-14), `Add CLI for controlled reanalysis output comparison (#213)`.

**Working remediation branch:** `audit/phase1-acmg-variant-scope`

## Evidence policy

PASS is reserved for behavior supported by executed evidence. Repository inspection, source review, and existing CI evidence are recorded separately from live laboratory validation. No clinical-validation or production-deployment claim is inferred from software tests.

## Confirmed findings

| ID | Severity | Area | Finding | Status | Evidence / action |
|---|---|---|---|---|---|
| ACMG-001 | High | ACMG mutation integrity | `POST /analyses/{analysis_id}/variants/{variant_id}/acmg/assess` validated the analysis tenant/role but did not independently establish that the canonical/global `Variant` belonged to the requested analysis before creating versioned ACMG/Classification records. | FIX IMPLEMENTED; TEST NOT RUN LOCALLY | Branch commit `0e4e3749fd78749a608f7124c050df200ffb02be` requires an analysis-scoped `Annotation` row before mutation; regression test added in `tests/test_acmg_variant_scope.py`. CI execution remains required. |
| DISPATCH-001 | Verification gap | Celery dispatch | Durable dispatch fencing exists for analysis, case-export and resource-staging execution, but release evidence is still dependent on the open dispatch regression PR and live qualification. | PARTIAL | PR #216 adds registration/late-ack/stale-dispatch regression coverage; it is open and not merged. |
| REANALYSIS-001 | Verification gap | Reanalysis reproducibility | Controlled comparison CLI exists, but no real laboratory parent/child comparison has been executed against approved pinned resources. | BLOCKED EXTERNAL | PR #213 is merged; PR #215 adds CLI outcome tests and remains open. |
| RECOVERY-001 | Verification gap | Stage-body recovery | Annotation stage recovery test PR #179 did not pass on its tested merge head; the failure occurred before the injected post-commit boundary (`provider_calls=0`, `persistence_calls=0`). | OPEN | Do not weaken the assertion. Reconcile the fixture against the current workflow before merging. |
| DEPLOY-001 | External blocker | Deployment | Current release documentation states live PostgreSQL/Redis/Celery/Firebase/GeneBe execution and durable artifact/reference storage remain deployment gates. | BLOCKED EXTERNAL | Requires an actual controlled deployment and evidence capture. |
| SCI-001 | External blocker | Scientific validation | No pinned truth-set benchmark artifact with declared reference, confident regions, TP/FP/FN and concordance has been captured. | NOT TESTED | Requires an approved benchmark input and controlled environment. |

## Existing strengths verified by source inspection

- Backend is FastAPI + SQLAlchemy + PostgreSQL with Celery/Redis; the frontend is Next.js/React/TypeScript.
- Long-running analysis is persisted on the backend rather than being treated as a frontend-only operation.
- VCF intake distinguishes validation from analysis initiation and stores SHA-256 artifact identity.
- Analysis execution has durable workflow steps and partition scheduling/fencing.
- Backend authorization resolves a case through trusted authentication context for accessible analysis/artifact/report operations.
- Evidence context and clinical-governance endpoints use analysis-scoped variant checks.
- Reportability/sign-out, audit/provenance, and reanalysis lineage are represented as versioned domains in the current release candidate.

## Existing release evidence reconciled

- `docs/PHASE1_ACCEPTANCE_MATRIX.md` records the release gate as open and explicitly lists live E2E, scientific benchmark, tenant-isolation, recovery, storage, backup/restore and deployed-revision gaps.
- Current README describes the repository as a Phase-1 release candidate, not a clinically validated diagnostic product.
- Main CI evidence cited by the repository includes backend, PostgreSQL/Celery integration, frontend production build/container and Compose validation on earlier main revisions; the current direct commit `2efbe032...` has a Vercel status but no combined GitHub Actions result attached in the inspected repository status.

## Required next concrete tasks

1. Reconcile and merge only the passing dispatch-fence/reanalysis CLI regression work after review; do not merge failed recovery assertions.
2. Repair PR #179's annotation-stage recovery fixture against the current main workflow and rerun the actual stage-body test without weakening its boundary.
3. Enumerate every Celery task and Beat entry point and prove tenant/system-task scope with direct tests; dispatch fencing is not itself tenant authorization.
4. Add PostgreSQL integration coverage for stage-body crash/replay at population, evidence, ACMG, review, reportability, report/sign-out, provenance export and reanalysis boundaries.
5. Run the controlled lab qualification, deployed VCF→report/sign-out workflow, storage/backup/restore tests and approved scientific benchmark. Keep the release gate open until evidence exists.

## Current branch state

The remediation branch contains the narrow ACMG integrity correction and its regression test. It has not been merged to `main`.

**Local test execution:** unavailable in this environment because a direct repository clone could not resolve `github.com`; therefore the new regression test is explicitly **NOT RUN** here. GitHub CI must provide the authoritative execution result before merge.
