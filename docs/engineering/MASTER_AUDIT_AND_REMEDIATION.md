# SIRALOOM Master Audit and Remediation

**Updated:** 2026-10-15
**Audited application-code baseline:** `main` commit `bc22d41` (`Fix report bootstrap cleanup scope`), 2026-10-15. GitHub Actions run [#1546](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38728407140) passed backend, PostgreSQL integration, and frontend jobs, including the corrected production type check.
**Working tree note:** an unrelated pre-existing untracked backup artifact is present; it has been preserved.
**Scope:** Phase 1 account-to-signout product workflow audit and repair.
**Overall status:** IN PROGRESS — do not treat Phase 1 as complete or the product as clinically/production ready.

## Verified current batch

| Finding | Root cause | Correction | Evidence | Status |
|---|---|---|---|---|
| Scheduled scientific-resource discovery was absent from the production Celery registry. | `discover_scientific_resources` had been declared only in the `Celery is None` branch, while the Beat schedule referenced it in all deployments. | Registered the named task in the normal Celery-enabled branch; retained an unavailable placeholder for environments without Celery. | `tests/test_celery_dispatch_fence_audit.py` + `tests/test_resource_discovery.py`: 13 passed. GitHub Actions run [#1533](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38723206952): backend, PostgreSQL/Celery integration, and frontend jobs succeeded. Commit `6b11afd`. | FIXED, tested, pushed to main |

## Verification limits observed

- The local Windows full suite at `6b11afd` reported 807 passed, 37 skipped, and one failure in `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`. The runtime could not load WeasyPrint native `libgobject-2.0-0`/Pango libraries. This is an environment limitation, not evidence that PDF rendering passes locally.
- A fresh full backend run at `dc3be3e` reported **816 passed, 37 skipped, 1 failed**. The only failure was again `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`, caused by the unavailable Windows native `libgobject-2.0-0` dependency. CI status for commits after `324283b` has not been verified in this environment; prior run #1534 is not evidence for these later commits.
- GitHub Actions run [#1541](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38726450883) for `12ed477` completed successfully in backend, PostgreSQL/Celery integration, and frontend jobs. It includes the frontend production build/container and Compose validation. The current local changes have not yet been included in that run.
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

## 2026-10-15 workspace case-switch privacy and stale-response correction

- **Finding:** changing the selected case left the previous case's analysis, specimens, variants, review, report, export, artifacts, and audit entries rendered until the new case request completed. In-flight polling and detail requests could also write the previous case's data after a switch.
- **Correction:** clear case-scoped state when selection changes; render only a loading/retry surface until `caseWorkspace.case_id` matches the selected case; cancel case-detail requests on cleanup; ignore stale responses from analysis, variant, audit, export, and artifact reads. Added a pure readiness-policy regression test.
- **Verification:** frontend `npm run test:session` passed 14 tests; `npm run validate:i18n` passed; `git diff --check` passed. CI run #1542 passed backend, PostgreSQL integration, and frontend jobs for prior commit `a270237`; the current UI correction still requires its own push-triggered CI run. Local Next build cannot run because `frontend/node_modules` is absent.
- **Checkpoint:** correction was committed and pushed as `c409f68`; GitHub Actions run #1543 passed all three jobs. Phase A remains PARTIAL: case switching is guarded in code and helper tests, but interactive browser account/tenant switching, remaining frontend surfaces, and all remaining Phase A workflow checks are still outstanding.

## 2026-10-15 audit timeline case-switch privacy correction

- **Finding:** the standalone audit page retained the prior case's events in the timeline while another case was selected; overlapping requests could allow an older response to overwrite the current selection.
- **Correction:** associate loaded events with their case identity, hide the timeline unless that identity matches the current selection, clear prior events on selection changes, and ignore canceled or superseded audit/list responses.
- **Verification:** frontend `npm run test:session` passed 14 tests; `npm run validate:i18n` and `git diff --check` passed. The shared case-identity readiness policy test covers the visible-data guard. This page change is not yet included in a production build or CI run.
- **Checkpoint:** correction was committed and pushed as `5519751`; GitHub Actions run #1544 passed all three jobs. Reports were then separately corrected in `c914c44`; run #1545 is in progress. Phase A remains PARTIAL; review still requires the same stale-response audit, and no browser-based journey has been demonstrated.

## 2026-10-15 report-page analysis-scope correction (working tree)

- **Finding:** the Reports page continued rendering decision and report rows from the previous analysis while another analysis ID was selected; racing requests could overwrite the newly selected analysis's data.
- **Correction:** results and selected decision are rendered only when their loaded analysis ID matches the selected ID; overlapping reads are generation-checked; reportability and report-generation actions remain disabled until the selected analysis data is loaded. Changing analyses also clears the prior decision selection, rationale, and disposition.
- **Verification:** frontend `npm run test:session` passed 15 tests, including the analysis-identity readiness policy; `npm run validate:i18n` passed. CI run #1545 caught a TypeScript error in the bootstrap effect cleanup. The scope error was fixed and pushed as `bc22d41`; run #1546 is in progress.
- **Checkpoint:** report-scope correction is committed as `c914c44`, and the build hotfix is committed as `bc22d41`. The review-page correction remains in the working tree and requires its own build verification. Phase A remains PARTIAL.

## 2026-10-15 clinical review analysis and variant context correction (working tree)

- **Finding:** changing analyses or selected variants could leave a previous clinical dossier, governance record, pedigree/segregation data, or reviewer rationale visible or writable while new review detail was loading. Late queue/detail responses could also replace newer selections.
- **Correction:** queue visibility is bound to its loaded analysis ID; dossier visibility additionally requires the selected variant and returned review bundle to match. Queue, review, governance, and family reads ignore superseded requests. Analysis changes reset case-specific reviewer edits, and variant changes clear variant-specific review data and rationale.
- **Verification:** frontend `npm run test:session` passed 16 tests (including analysis readiness and identity-key policy); `npm run validate:i18n` and `git diff --check` passed. The Next production build is unavailable locally because `frontend/node_modules` is absent; push-triggered CI will verify the review-page TypeScript/build integration.
- **Checkpoint:** review-page and Firebase identity remount corrections are in the working tree pending commit/push. CI #1546 passed the preceding report hotfix; current changes still need their own build run. Phase A remains PARTIAL and no browser-based reviewer/account-switch journey has been run.

## 2026-10-15 account-switch in-memory workspace isolation correction (working tree)

- **Finding:** auth-state changes cleared localStorage context but did not remount protected route components. On a direct Firebase UID change, case/report/review data already held in React component state could remain rendered for the next account.
- **Correction:** key the authenticated route subtree by a namespaced Firebase UID (and a distinct signed-out key), forcing route-local state to be discarded when the identity changes. Added a policy regression for distinct identities and signout.
- **Verification:** frontend behavior tests now pass 16 tests and localization validation passes. This app-shell integration has not yet been covered by a real Firebase/browser account switch; production build will be checked by CI after push.
- **Checkpoint:** code and test are pending commit/push with the Review page correction. Phase A remains PARTIAL.

## 2026-10-15 API object-authorization audit batch

| Finding | Root cause | Correction | Verification | Status |
|---|---|---|---|---|
| Audit endpoint distinguished nonexistent case IDs from cases owned by another tenant. | `GET /cases/{case_id}/audit` returned `200 []` when absent, but tenant guard returned `404 Case not found` for a foreign case, allowing ID existence probing. | Absent case now raises the same `404 Case not found`; added a regression asserting the exact status and response detail match for absent and cross-tenant cases. | Focused auth/tenant/analysis-variant/ACMG suite: 26 passed; `ruff --select F401,I` passed on changed Python files; `git diff --check` passed. | FIXED, locally verified |
| ACMG auto-assessment accepted a globally fetched variant without proving its membership in the requested analysis. | `auto_assess` called `db.get(Variant, variant_id)` instead of the existing analysis-scoped `get_analysis_variant` authorization helper. | Route now requires variant membership through the common helper before looking up annotation, population evidence, or persisting a specification assessment; regression proves nonmember variants are rejected with 404. | Focused auth/tenant/analysis-variant/ACMG suite: 26 passed; import lint passed on changed Python files. | FIXED, locally verified |

## 2026-10-15 follow-up authorization and ownership batch

| Finding | Root cause | Correction | Verification | Status |
|---|---|---|---|---|
| Pedigree member could link to a specimen from another case. | `add_member` accepted `specimen_id` from request without checking the specimen's owning case. | Resolve the specimen server-side and require `specimen.case_id == case_id`; otherwise return 404 with a case-scoped message. | Added a regression proving a foreign-case specimen is rejected before mutation; focused authorization, export integrity/download, mutation, variant access and reportability suites passed: 28 tests. | FIXED, locally verified |
| Case-export status/download, reportability signoff, evidence lookup and follow-up update could return different not-found details for absent versus foreign-tenant IDs. | Export routes fetched globally then applied tenant checks whose error detail identified a case; decision/evidence/follow-up routes returned an object-specific missing detail for absence but `Analysis not found` for a foreign tenant. | Centralized export lookup and tenant verification to return `404 Export not found`; remap only 404 analysis access failures to the matching object-specific 404 before continuing. | Regression tests in `tests/test_audit_tenant_authorization.py` compare absent and foreign responses for all four route types. Focused auth, export, variant and reportability suite passed: 31 tests. Updated an existing download test fixture to provide a realistic organization ID. Changed-file import lint (`ruff --select F401,I`) and `git diff --check` passed. | FIXED, locally verified |

The inventory continues. Nested resource/assay/specimen linkage and worker-owned tenant scope still need separate validation. The latest committed and pushed main correction is `dc3be3e`.

## 2026-10-15 browser account-context checkpoint (local, pending push)

- **Finding:** the app stored `siraloom.case_id`, `siraloom.case_identifier`, and `siraloom.analysis_id` globally in browser localStorage. `AppShell` did not clear them when Firebase identity changed or signed out. Server-side tenant checks prevented these IDs alone from granting access, but a different account inherited stale context and UI requests.
- **Change:** introduced `syncWorkspaceContext`, called from Firebase auth-state changes. It clears case/analysis context on signout or UID change, preserves it for the same UID, and tolerates restricted browser storage. Signout failures now display an English/Arabic alert. The `test:session` command now includes case artifact and account-context tests.
- **Verification:** `npm run test:session` passed 13 tests; `npm run validate:i18n` passed; `git diff --check` passed. `frontend/node_modules` is absent, so the TypeScript/Next build cannot run in this checkout.
- **Checkpoint:** implementation and tests are in the working tree and not yet pushed. After committing, continue frontend stale-data/error-state review and then worker tenant scope/recovery. Overall Phase A remains PARTIAL.

## 2026-10-15 API input and frontend regression CI correction (local, pending push)

- **Finding:** `/api/v1/variants/{variant_id}` accepted `str` and manually called `UUID(...)`, so malformed path IDs could raise an uncaught `ValueError` rather than FastAPI's normal 422 validation response.
- **Change:** typed the route parameter as `UUID` and added an API-level malformed-ID regression.
- **Finding:** the frontend CI job installed dependencies and built the app but never ran the existing Node behavior tests, including account-session routing and VCF artifact selection.
- **Change:** added `npm run test:session` to frontend CI. This command now includes safe redirect, session destination, case artifact selection, and account-context policy tests.
- **Verification:** focused backend API/auth tests passed 10; frontend Node behavior tests passed 13; localization guard passed; CI YAML parsed; `git diff --check` passed. These changes are uncommitted and will receive a new GitHub run after the direct-main push.
- **Checkpoint:** push this coherent input-validation/CI batch, then audit the remaining worker tenant/data lineage boundaries. Phase A remains PARTIAL.

## 2026-10-15 additional verified correction

- **A1 sign-in state misrouting (High):** an inactive or otherwise unauthorized provisioned Firebase identity received the same 403 as a new identity, and frontend redirect handling could send failed session checks to a requested internal route. Fixed with a stable unprovisioned-state response header, explicit CORS exposure, fail-closed frontend routing, and localized access/service messages. Unprovisioned accounts can continue to onboarding or invitation acceptance only; protected routes require a valid session.
- **Tests:** auth/principal/route/tenant focused suite 68 passed; frontend redirect/session-state Node tests 7 passed; i18n guard and JavaScript syntax checks passed. Local Next build unavailable because `next` is not installed. GitHub Actions run #1534 passed the backend, PostgreSQL/Celery integration, and frontend jobs, including the production frontend build/container and Compose validation.
- **Current branch state:** commit `324283b` is pushed to `main`. GitHub Actions run #1534 completed successfully across all three jobs; see [run details](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38724143912). Do not mark Phase 1 complete based on focused checks.
