# SIRALOOM Master Audit and Remediation

**Updated:** 2026-10-15
**Current branch / commit:** `main` at `324283be87d28d209d7319e1e599ab898266853d` (`Correct authentication session routing and record Phase 1 audit`).
**Working tree note:** an unrelated pre-existing untracked backup artifact is present; it has been preserved.
**Scope:** Phase 1 account-to-signout product workflow audit and repair.
**Overall status:** IN PROGRESS — do not treat Phase 1 as complete or the product as clinically/production ready.

## Verified current batch

| Finding | Root cause | Correction | Evidence | Status |
|---|---|---|---|---|
| Scheduled scientific-resource discovery was absent from the production Celery registry. | `discover_scientific_resources` had been declared only in the `Celery is None` branch, while the Beat schedule referenced it in all deployments. | Registered the named task in the normal Celery-enabled branch; retained an unavailable placeholder for environments without Celery. | `tests/test_celery_dispatch_fence_audit.py` + `tests/test_resource_discovery.py`: 13 passed. GitHub Actions run [#1533](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38723206952): backend, PostgreSQL/Celery integration, and frontend jobs succeeded. Commit `6b11afd`. | FIXED, tested, pushed to main |

## Verification limits observed

- The local Windows full suite at `6b11afd` reported 807 passed, 37 skipped, and one failure in `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`. The runtime could not load WeasyPrint native `libgobject-2.0-0`/Pango libraries. This is an environment limitation, not evidence that PDF rendering passes locally.
- The matching GitHub Actions run succeeded in all three jobs, including PostgreSQL/Celery integration and frontend production checks.
- No configured Firebase browser identity, live cloud bucket, or laboratory deployment was used for browser-based signup, email verification/recovery, real tenant separation, or report signout. Those checks remain NOT RUN here.
- The repository's existing detailed history is retained in [`PHASE_A_AUDIT_LEDGER.md`](PHASE_A_AUDIT_LEDGER.md); it contains prior fixes and remaining worker, deployment, and scientific qualification boundaries. This file supplements, rather than replaces, that record.

## Current workflow checkpoint

Source inspection has confirmed the Next.js/Firebase browser identity flow, FastAPI `/api/v1` routes, SQLAlchemy persistence, Celery/Redis workers and Beat, artifact stores, review/report APIs, and the existing workflow and integration test suites. The detailed stage-by-stage status is in [`END_TO_END_WORKFLOW_AUDIT.md`](END_TO_END_WORKFLOW_AUDIT.md).

## Remaining work, in dependency order

1. Complete the account lifecycle trace, including inactive/suspended identities, invitation and membership changes, browser session revocation, and error/retry behavior. Add browser/component-level coverage for user-visible paths where the current test stack permits.
2. Complete API-by-API object authorization and tenant isolation review, including every artifact/report/export and background task entrypoint; execute PostgreSQL integration tests rather than relying only on SQLite doubles.
3. Complete the case/specimen/VCF intake and analysis path audit against actual UI requests, persisted state, and failure recovery. Preserve the declared VCF scope and unsupported-input behavior.
4. Complete the evidence, review, reportability, artifact generation, signout, amendment, and audit-lineage trace. Verify each critical guard in route and service tests.
5. Complete frontend contract, stale-state, loading/error, accessibility, navigation, and authenticated-download review; run available frontend tests/build and a real browser journey if configured infrastructure exists.
6. Complete the reanalysis and resource-release lifecycle audit, including failure and duplicate-delivery cases.
7. Run the Phase 1 acceptance gate and update every matrix row with actual evidence; keep any unavailable external checks explicitly BLOCKED/NOT RUN.

## Phase decision

**Phase 1: PARTIAL.** The current code has broad automated coverage and several previously repaired workflow controls, but a complete source-level trace and authenticated end-to-end browser-to-persistence-to-signout verification have not been demonstrated. This is not a clinical validation, regulatory, or production-readiness determination.

## 2026-10-15 additional verified correction

- **A1 sign-in state misrouting (High):** an inactive or otherwise unauthorized provisioned Firebase identity received the same 403 as a new identity, and frontend redirect handling could send failed session checks to a requested internal route. Fixed with a stable unprovisioned-state response header, explicit CORS exposure, fail-closed frontend routing, and localized access/service messages. Unprovisioned accounts can continue to onboarding or invitation acceptance only; protected routes require a valid session.
- **Tests:** auth/principal/route/tenant focused suite 68 passed; frontend redirect/session-state Node tests 7 passed; i18n guard and JavaScript syntax checks passed. Local Next build unavailable because `next` is not installed. GitHub Actions run #1534 passed the backend, PostgreSQL/Celery integration, and frontend jobs, including the production frontend build/container and Compose validation.
- **Current branch state:** commit `324283b` is pushed to `main`. GitHub Actions run #1534 completed successfully across all three jobs; see [run details](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38724143912). Do not mark Phase 1 complete based on focused checks.
