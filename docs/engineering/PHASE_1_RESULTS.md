# SIRALOOM Phase 1 Results

## Latest checkpoint — 2026-10-18

Pushed baseline: `main` at `d61782627787fabc1ea4b9662fb2e12b704bc58d`, locally aligned with `origin/main` after successful push output. The current commit fences resource preflight and runtime execution to the analysis case's tenant. The focused planner/runtime/fallback/registry/preflight/reanalysis/authorization suite passed **101 tests**. The preceding `5785fbb` snapshot and provenance-role change passed **76 focused tests**. At `3385b69`, the full suite excluding only the Windows-native PDF renderer test passed **917 tests, 36 skipped**; it was not rerun at `d617826`. The unfiltered full suite at the prior baseline failed `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes` because WeasyPrint could not load `libgobject-2.0-0` on this Windows host. Python syntax compilation and `git diff --check` passed for the current code change. GitHub Actions for `d617826` are not verified. The annotation production-wrapper test exercises response-checkpoint crash, redelivery/replay, annotation-row crash, and final reconciliation without requiring local `bcftools`.

Further route inspection on 2026-10-18 found a stale-membership privacy and account-mutation boundary: an identity can be reprovisioned after its prior membership is inactive, leaving a historical row in the old organization. The former tenant roster exposed the user's current global profile, and its admin could mutate global status/role through the old row. The roster now filters to the user's current organization, and mutation locks and verifies current account ownership before updating. This fix and the other recovery/manifest changes are included in pushed commit `3385b69`; Phase A remains PARTIAL.

The same direct code audit found `/analyses/{id}/start` could replace a successful/running analysis with `BLOCKED` when capacity preflight failed, and did not explicitly restore capacity-only blocked analyses when capacity returned. The endpoint now locks/refreshes lifecycle state, keeps queued/running starts idempotent, rejects nonstartable terminal/human-gated states, and returns capacity-recovered analyses to `CREATED` before dispatch. Its route/SQLite regression suite passed **9 tests**; this fix is included in `3385b69`.

Phase A remains **PARTIAL**, not complete. Browser-based Firebase signup/verification/password recovery/signout, deployed two-tenant object/storage boundary checks, and a complete live reviewer-to-signed-report and failure-recovery journey have not been run. The local browser surface is disabled and no deployed Firebase/laboratory test environment was supplied in this session. No clinical validation, regulatory authorization, or production-readiness claim is supported. Preserve the unrelated untracked backup artifact.

## Historical checkpoint — before this continuation

Inspected on `main` at `c724bdb`; tracked files were clean before this documentation update, and the unrelated untracked backup artifact was preserved. Four recently pushed backend fixes have regression tests but no observable CI result in this environment: report PDF ownership checks (`96ab9db`), report/analysis/PDF lineage validation in case exports (`127dfa1`), notification read lineage and timestamp idempotency (`b2a31ee`), and stale classification rejection at the reportability human gate (`4eedd33`). Local Python/pytest is unavailable because only the WindowsApps Python stub is present and no repository virtual environment exists.

Actual frontend session/workspace test command, run from `frontend/`:

```powershell
D:\nodejs\node.exe --test lib/safe-redirect.test.mjs lib/session-destination.test.mjs lib/case-artifacts.test.mjs lib/workspace-context.test.mjs lib/validated-upload.test.mjs lib/signout.test.mjs
```

Result: exit 0; 20 passed, 0 failed, 0 skipped. This does not constitute live Firebase, browser, backend-authorization, token-revocation, or deployment verification. Phase 1 remains **PARTIAL**; no production or clinical-readiness claim is supported. See `END_TO_END_WORKFLOW_AUDIT.md` for stage-by-stage status and `MASTER_AUDIT_AND_REMEDIATION.md` for the next task.

Logout source review: `AppShell.handleSignOut` calls Firebase client `signOut`; backend `get_current_principal` verifies Firebase tokens with `check_revoked=True`, but there is no application logout endpoint that invokes Admin token revocation. Firebase documents Admin refresh-token revocation as user-wide across sessions, with existing ID tokens potentially valid until expiry absent revocation checking ([Firebase session management](https://firebase.google.com/docs/auth/admin/manage-sessions)). Do not silently make ordinary logout revoke every device; this product behavior needs a decision and a live Firebase/browser test.

Latest reportability follow-up: reportability finalization previously returned an already-FINAL decision before checking if a newer classification had made it stale, and the list endpoint did not verify decision-to-classification lineage. The service now checks current decision/latest approved classification before idempotent success; list reads fail closed on stale lineage. Regression tests were added for stale FINAL retry and listing. The focused Python command could not start because the WindowsApps Python executable is inaccessible, and no recent CI result is available; this code is not yet verified. Phase 1 remains **PARTIAL**.

## Prior implementation checkpoint — 2026-10-17

**Latest pushed application baseline:** `main` commit `0e2e372`. GitHub Actions run [#1610](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39024386804) passed all jobs: backend **900 passed, 24 skipped**, PostgreSQL/Celery worker-loss integration passed, and frontend behavior/build/container/Compose checks passed. This verifies the report artifact guards and fixtures, storage-independent retry of an already signed report, reviewer assay tenant-lineage rejection, reviewer pedigree-lineage rejection, and compensation after draft-report audit flush failure.

This continuation repaired two real clinical-governance defects: the secondary-finding request schema lacked the `status` field the route dereferenced, and four create routes serialized ORM-generated timestamps before flushing new rows. Regression coverage now exercises confirmation, follow-up, secondary finding, and QC observation creation with a SQLite session and checks their audit snapshots. The status-field regression first caused run #1582 to fail and identified the route defect; the correction passed run #1583.

Additional tenant-lineage fixes in commits `14b819d`, `81a604c`, `a8ccc3f`, and `fcd0efe` cover notification references, secondary-finding variants, quality assay ownership, case-phenotype analysis linkage, and report-to-case linkage; the associated CI runs passed as recorded in the master ledger.

Commit `147062a` constrains governance states; CI #1584 passed. Commits `5a5e788` and `32f8e84` add tests and enforce the implemented resource-staging backend contract. Test-first run #1585 failed with 1 failed, 883 passed, 24 skipped; the fix passed all jobs in run #1586. This session found and fixed a draft report PDF lineage gap (`d6d7ec7`): report access now checks the linked artifact's case, analysis, type, validation state, and any present report identity/version/state metadata; newly generated drafts record report ID/version. New parameterized direct-object regressions cover malformed links. Run #1593 passed all jobs. Python tests could not run locally because the Windows Python launcher is unavailable. Commit `4458859` fixes reportability/report signout UI feedback when the API mutation succeeds but its subsequent refresh fails; it reports a localized recovery message instead of unconditional success. CI #1594 passed. Frontend behavior tests passed 20/20, i18n guard passed, and `git diff --check` passed locally. The unrelated untracked backup artifact remains untouched.

**Phase 1 remains PARTIAL.** The stage matrix still records all 13 journeys as partial; live Firebase/browser signup, verification, recovery, token/session invalidation, deployed direct cross-tenant checks, a complete reviewer-to-signed-report journey, and integrated failure recovery have not been demonstrated. No clinical validation, regulatory authorization, or production-readiness claim is made.

**Current Phase A checkpoint:** report read access now requires a durable draft artifact; report lists and direct reads validate draft and signed PDF lineage. Lost-response signout retries no longer depend on today's storage profile, while first-time signout keeps the original storage/transaction recovery contract. Both draft creation audit-flush and signout finalization failures have deterministic compensation coverage. Review context rejects cases whose linked assay or pedigree records cross organization/case boundaries. These changes pass CI #1610, but live Firebase/browser journeys and deployed two-tenant direct API verification remain open prerequisites for Phase A completion.

**2026-10-17 follow-up lifecycle correction:** route-level audit found that reopening a completed follow-up retained stale completion metadata. The update route now clears `completed_by`/`completed_at` for nonterminal states; the SQLite persistence regression covers complete → in-progress and verifies audit events. Clinical governance plus tenant object authorization tests passed **42**; reviewer/signout/recovery/reportability/reanalysis API suites passed **89**; direct-object/tenant/mutation authorization suites passed **70**. CI #1632 passed. These focused runs do not replace PostgreSQL concurrency, browser, or deployed two-tenant verification. Phase A remains **PARTIAL**.

**2026-10-17 QC artifact lineage guard:** the quality endpoint and review dossier now validate any QC observation artifact against the analysis case and analysis identity before returning dossier data. QC lineage, clinical-governance, and reviewer workflow/queue tests passed **40**; Python syntax compilation and `git diff --check` passed. CI #1633 passed. Phase A remains **PARTIAL** pending live and deployed workflow checks.

Full backend suite locally on `main` at `c2a75eb`: **869 passed, 37 skipped, 1 failed**. The sole failure is the PDF renderer test because the isolated local Python runtime lacks the declared WeasyPrint dependency. CI #1638's `Backend tests` step passed on `8b4db3e`, including the configured backend environment; production renderer/storage operation remains unverified. Phase A remains **PARTIAL**.

**2026-10-17 population query boundary:** population queries now reject variant IDs absent from the requested analysis before reading observations and cap the input list at 500. Population/direct-object/tenant/QC-related suites passed **81**. CI #1636 passed; the ledger update passed CI #1637. Phase A remains **PARTIAL**.

**2026-10-17 integrated reviewer/signout recovery:** a local SQLite integration test now exercises human classification approval, exact reportability linkage, report snapshot, injected signed-artifact persistence failure with DRAFT preservation, successful signout, signed-artifact integrity/audit verification, and idempotent retry. The combined focused authorization/review/signout/recovery suite passed **179** with one dependency deprecation warning, including this journey. CI #1638 passed backend, PostgreSQL integration, and frontend jobs. It uses deterministic artifact persistence and does not establish browser/Firebase, real object storage, deployed tenant isolation, or production rendering. Phase A remains **PARTIAL**.

**2026-10-17 resource approval ownership revalidation:** resource approval decisions now re-check private resource ownership before mutating approval state or tenant binding. The adoption plus staging/API/dispatch/recovery suite passed **48**; `git diff --check` pending final review. Phase A remains **PARTIAL**.

Signup/invitation/membership authorization and concurrency suites passed **33**. CI #1640 for `6a24d13` passed backend, PostgreSQL integration, and frontend. No Firebase/deployment variables or browser E2E harness are configured in this session; the existing SIRALOOM Chrome window could not be inspected because computer-use app approval timed out. No live or deployed journey is claimed. Phase A remains **PARTIAL**.

**Additional review dossier audit (CI verified):** the review service independently assembled pedigree context without checking that included segregation observations, relationship endpoints, and member specimens belonged to the analysis case. It now fails closed on those broken links; three parameterized SQLite regressions passed in CI #1610. This does not replace deployed two-tenant or browser verification.

### 2026-10-17 direct-object and signout recovery continuation

- **Direct-object finding:** `get_accessible_report` validated the report's tenant, case-analysis lineage, and final signed artifact but did not validate a non-null draft `artifact_id`. The report could expose a stale or cross-case PDF reference.
- **Correction:** `has_valid_draft_artifact` now verifies case, analysis, PDF type, validation state, and explicit metadata identity when present. New draft reports persist report ID/version metadata; legacy draft artifacts without those optional fields remain supported if their case/analysis/type are valid.
- **Regression coverage:** six parameter cases reject a draft artifact with wrong case, analysis, type, report ID, version, or state. CI #1593 passed all jobs. Local backend pytest was unavailable (`python.exe` is only a Windows Store stub).
- **Signout UI recovery finding:** reports UI mutation handlers always displayed success after `load()` even though `load()` swallowed refresh errors. Commit `4458859` checks the refresh outcome and shows a new English/Arabic “mutation succeeded, latest status unavailable” message. Frontend behavior tests passed 20/20; i18n validation and `git diff --check` passed. CI #1594 passed.
- **Report list follow-up:** `GET /analyses/{analysis_id}/reports` previously returned draft/signed artifact references after only checking case linkage. Commit `e4573a9` validates draft artifact lineage on every row and rejects finalized rows whose signed artifact fails integrity checks; CI #1596 passed all jobs.
- **Historical report follow-up:** direct reads and lists require valid signed artifacts for `SUPERSEDED` reports as well as `FINAL` reports. Commit `9e29256` adds regression coverage; CI #1598 passed all jobs.
- **Next:** continue route-by-route direct-object review and integrated reviewer-to-signout/retry recovery tests. Live Firebase and deployed two-tenant evidence is still required. Phase A remains PARTIAL.

**Historical baseline recorded below:** 2026-10-15, application commit `324283be87d28d209d7319e1e599ab898266853d`; audit-record follow-up `dd4c1e6`.
**Historical phase status:** IN PROGRESS / PARTIAL. The newer 2026-10-17 status is recorded above.

## Implemented in the current work session

### Case readiness across repeated VCF uploads

- **Defect:** `backend/app/api/v1/artifacts.py` assigned case status from only the newest primary VCF. A rejected re-upload could hide an earlier valid input, while a valid upload could reset a case already in a later lifecycle state.
- **Fix:** Added `backend/app/domain/case_intake.py` to derive readiness from persisted primary VCF validation statuses and preserve non-intake lifecycle states.
- **Regression evidence:** Focused intake, input-validation and artifact-integrity tests, executed with the bundled Python runtime: exit 0, 32 passed. Route-level test and CI verification remain pending.
- **Commit:** `3928ca1` pushed to `main`; CI run #1548 passed backend, PostgreSQL integration, and frontend jobs.

### BGZF parsing and validation-aware upload UI

- **Defects:** `.vcf.bgz` was advertised but parsed as uncompressed text; the workspace enabled analysis and showed success for artifacts whose validation result was `INVALID`, and retained an earlier artifact when a different file was selected.
- **Fixes:** Decode `.bgz` via gzip-compatible parsing; expose the extension in the chooser; allow analysis only for consistent successful API validation; clear stale artifact selection; show validation errors and warnings in English and Arabic.
- **Regression evidence:** Focused backend intake/artifact/input tests: 33 passed. Frontend upload/readiness plus workspace-context tests: 18 passed. `scripts/validate-i18n.mjs`: PASS. Run #1549 failed the production build because the JavaScript helper lacked a TS declaration; declarations have since been added, and build verification is pending CI.
- **Commit:** BGZF and workspace validation behavior pushed in `72f10b9`; the TypeScript declarations and case-wizard replacement handling are in the current local follow-up.

- **CI follow-up:** Run #1549 passed backend, PostgreSQL/Celery integration, and frontend behavior tests, but the production build failed because TypeScript could not find a declaration for `validated-upload.mjs`. Added declarations for the new upload helpers and corrected case-wizard primary/index selection in `082dbd7`. The frontend behavior suite reports 18 passed; run #1550 must verify the production build.

### Report draft artifact commit recovery

- **Defect:** Draft report bytes were persisted to artifact storage before database commit. If commit failed, the route rolled back but left stored bytes without a durable report/artifact row.
- **Fix:** Extracted a shared artifact compensation service and applied it to draft report commits. Cleanup uses a fresh DB session and occurs only when artifact absence is confirmed; uncertain outcomes preserve bytes.
- **Regression evidence:** `tests/test_artifact_commit_compensation.py`, `tests/test_report_artifact_commit_compensation.py`, `tests/test_report_finalization.py`, and `tests/test_report_artifact_replay_idempotency.py`: 16 passed. The route-level failure-injection test confirms rollback, fresh-session absence check, and storage cleanup. CI run #1553 passed all three jobs.
- **Commit:** `c4113fa` plus required ignored-module follow-up `a863097`, pushed to `main`.

### Onboarding and invitation signout failures

- **Defect:** The signout controls on onboarding and invitation acceptance allowed Firebase rejection to become an unhandled promise with no user-visible error.
- **Fix:** Added a shared signout result helper, localized error feedback, and busy-state protection in both screens.
- **Regression evidence:** Frontend behavior suite: 20 passed, including success/rejection behavior; localization guard passed. CI pending.
- **Commit:** Current local batch; awaiting CI.

### Case export integrity and recovery

- **Defects:** Artifact inclusion assumed a local filesystem store, so cloud-backed tenants could not create exports; package bytes could remain after artifact flush or export commit failure because the deterministic artifact ID bypassed generated-ID cleanup.
- **Fix:** Download cloud artifacts through the store's integrity-checked method and verify both local and cloud bytes against persisted SHA-256/size. The worker now removes a package only after a fresh DB read confirms its Artifact row is absent and preserves success when an exception follows a durable commit.
- **Regression evidence:** Case export, injected flush failure, error redaction, download integrity, and dispatch suites: 17 passed locally. CI pending.

### Membership roster privacy

- **Defect:** Any authenticated tenant member could query all member emails and roles even though the settings UI exposes the roster only to organization admins and lab directors.
- **Fix:** Enforced the administrator role policy in the server route and skipped the roster call in settings for other roles.
- **Regression evidence:** `tests/test_membership_roster_authorization.py`, membership mutation, invitation, principal authorization, and API route-auth coverage: 30 passed locally. CI pending.

### Signed report artifact recovery

- **Defect:** Signout uploads the signed PDF before report and audit changes are flushed and committed. A failed audit flush, API commit, or durable resume-intent commit could leave untracked signed bytes.
- **Fix:** The signout route computes the deterministic artifact identity and canonical storage URI before finalization. On exceptions it rolls back, checks a fresh database session, and removes bytes only when artifact metadata is confirmed absent. The direct database commit path now uses shared artifact compensation.
- **Regression evidence:** `tests/test_report_artifact_commit_compensation.py`, `tests/test_report_finalization.py`, and `tests/test_report_signout_resume.py`: 14 passed locally. CI pending.

### Artifact-to-analysis tenant linkage

- **Defect:** Shared artifact authorization checked the artifact case's tenant but did not verify that an optional linked analysis belonged to the same case.
- **Fix:** The accessor now rejects missing analyses and case mismatches with the same not-found response, before download handlers resolve storage.
- **Regression evidence:** `tests/test_tenant_object_authorization.py`, `tests/test_artifact_download_identity.py`, and `tests/test_population_route_tenant_guards.py`: 27 passed locally. CI pending.
- **Commit:** Local batch; awaiting push-triggered CI.

### Celery Beat resource-discovery registration

- **Defect:** Beat scheduled `siraloom.discover_scientific_resources`, but production Celery did not register that task because its declaration existed only in the `Celery is None` branch.
- **Fix:** Moved the actual named Celery task into the Celery-enabled branch in `backend/app/infrastructure/queue/celery_app.py`. The no-Celery branch now exposes an unavailable placeholder consistently.
- **Regression evidence:** `python -m pytest -q tests/test_celery_dispatch_fence_audit.py tests/test_resource_discovery.py` using the bundled Python runtime: exit 0, 13 passed.
- **Broad local verification:** Full `python -m pytest -q`: exit 1, 807 passed, 37 skipped, 1 failed. The sole failure is `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`, because this Windows runtime lacks WeasyPrint native `libgobject-2.0-0`/Pango libraries.
- **Repository CI:** GitHub Actions run #1533 at this commit succeeded: backend, PostgreSQL/Celery integration, and frontend jobs all passed. [Run details](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38723206952).
- **Commit:** `6b11afd` pushed to `main`; no force push or history rewrite.

## Prior implementation retained

Earlier Phase A changes and their evidence remain in [`PHASE_A_AUDIT_LEDGER.md`](PHASE_A_AUDIT_LEDGER.md), including authentication hardening, tenant-aware authorization, invitation/membership concurrency, case/specimen integrity, workflow dispatch/recovery, artifact identity/integrity, report integrity and reanalysis controls. The new master ledger and workflow matrix link those results to the current checkpoint without rewriting that history.

## Open verification and implementation work

- Real Firebase signup, email verification, password recovery, account suspension, token expiry/revocation, and logout/browser-cache paths were not run against a configured identity project.
- Full API-by-API tenant isolation review and direct cross-tenant API execution remain incomplete; existing shared-accessor and route-inventory tests are not proof of all endpoint and worker boundaries.
- Browser E2E for case creation, VCF upload, analysis status progression, review, report generation/download/signout, amendments, and account switching is not configured or executed.
- Local PDF rendering was blocked by missing native libraries, although the repository's Linux GitHub CI passed its configured checks.
- No controlled laboratory deployment, live cloud IAM/storage test, backup/restore, or external-provider qualification was performed as part of this Phase 1 checkpoint.
- Scientific correctness, clinical validity/utility, and regulatory/laboratory authorization are separate work and are not established by Phase 1 application tests.

## Current acceptance decision

**Phase 1 is not complete.** Source and existing test coverage support partial confidence in several backend guards, but the full signup-to-signout journey and all tenant/security boundaries have not been verified end to end. Continue from the ordered remaining work in [`MASTER_AUDIT_AND_REMEDIATION.md`](MASTER_AUDIT_AND_REMEDIATION.md); use [`END_TO_END_WORKFLOW_AUDIT.md`](END_TO_END_WORKFLOW_AUDIT.md) as the live requirement matrix.

### 2026-10-17 report-read lineage correction

- **Finding:** `has_valid_draft_artifact` accepted a report with no `artifact_id`, so direct report access could return a draft that had no immutable PDF. Report generation always creates the draft artifact, and signout already rejects a missing artifact; the permissive read behavior could hide a partial/corrupt record.
- **Correction:** missing draft artifact linkage now fails closed. Added a tenant-authorized direct report read regression in `tests/test_tenant_object_authorization.py`.
- **Verification:** `git diff --check` passed. Local Python execution remains unavailable; run the focused regression and full relevant suites in CI after this push.
- **Status:** code change is pending push-triggered CI. Phase A remains PARTIAL pending end-to-end review/signout recovery and live Firebase/browser and deployed two-tenant validation.

### 2026-10-17 repeated signout recovery correction

- **Finding:** the finalize route resolved the current organization storage profile before recognizing a previously committed FINAL report. A lost-response retry could therefore fail during an unrelated storage-profile outage even though the signed report and its durable artifact record were valid.
- **Correction:** already-final reports return their existing signed state without resolving storage; resumable analysis states still invoke the existing idempotent durable resume path. Non-DRAFT/non-FINAL reports fail before storage resolution. The lost-response regression now injects storage-resolution failure on retry.
- **Verification:** `git diff --check` passed. Python tests cannot execute locally in this Windows checkout. Awaiting push-triggered CI.

### 2026-10-18 working-tree continuation checkpoint

- **Implemented in source:** analysis variant manifests are authoritative across the shared variant guard, review queue, variant listing, complete variant JSON/CSV exports, reportability proposal/finalization, report generation, signout eligibility, and worker human-review/reportability gates. Empty or malformed present manifests cannot be overridden by downstream annotation/classification rows; a completed zero-record normalization is also an explicit empty manifest, and legacy fallback requires absence of current-manifest markers. Reportable secondary findings, classifications, and orphan reportability decisions are rejected when inconsistent with the analysis input; the reportability API returns a conflict for that persisted inconsistency. Worker review gates also require exact annotation/classification coverage of the normalized variant set.
- **Regression tests added:** direct guard malformed and zero-record-manifest cases, review queue, variant listing/report legacy-vs-manifest behavior, reportability proposal/finalization/coverage/orphan decision and route response, report generation/signout eligibility, and worker human-gate mismatch.
- **Verification:** bundled Python `py_compile` and `git diff --check` pass. The complete Python suite excluding `tests/test_report_pdf.py` passed **917 tests, 36 skipped** using dependencies installed temporarily from `pyproject.toml`; the excluded Windows WeasyPrint test cannot load `libgobject-2.0-0`. No CI or live deployment result is claimed.
- **Repository state:** changes are on local `main` working tree and are not committed or pushed; current filesystem permissions deny Git index writes. Phase A remains PARTIAL. Live Firebase/browser, deployed two-tenant API/storage isolation, and integrated real-storage reviewer-to-signout recovery remain unverified.

### 2026-10-17 reviewer assay-tenant lineage guard

- **Finding:** review-bundle construction returned the linked assay's configuration without confirming that the assay belonged to the reviewed case's organization. Analysis creation validates this relationship, but inconsistent persisted lineage could expose another laboratory's assay configuration in reviewer context.
- **Correction:** review-bundle construction now rejects a linked assay whose organization differs from the case. Added a SQLite service regression with a foreign-organization assay.
- **Verification:** awaiting CI; local Python interpreter is unavailable. Phase A remains PARTIAL.

### CI #1603 report-lineage fixture correction

- **Result:** run #1603 failed in two pre-existing authorization fixtures because they represented accessible reports without draft artifact links. This confirmed the new guard is enforced; those fixtures had to be updated to represent valid report records.
- **Correction:** shared-accessor and valid-final-report fixtures now include explicit valid draft artifact metadata. The FINAL fixture separately models both draft and signed artifacts. The negative missing-artifact regression remains unchanged.
- **Next verification:** commits `e424d3b` and `c7fa1ea` are in CI runs #1604 and #1605 respectively. This fixture correction will be pushed as a new main commit for fresh full CI. Do not treat the failed #1603 run as a passing implementation verification.

### 2026-10-17 draft report audit-flush recovery

- **Finding:** draft report generation compensated storage bytes when the final DB commit failed, but not when the earlier audit-event flush failed after PDF upload.
- **Correction:** audit flush failure now rolls back and invokes the existing fresh-session artifact compensation guard. Added a deterministic injected audit-flush failure test asserting that uncommitted draft bytes are deleted.
- **Verification:** `git diff --check` passed. Python execution is unavailable locally; regression awaits CI.
- **CI follow-up:** run #1607 found one existing signout-compensation test stub omitted `status`; it must model the DRAFT state now required by the route. The backend run otherwise had 896 passed and 24 skipped; PostgreSQL/Celery passed. The fixture correction is being pushed for fresh verification.

### Additional sign-in state routing fix

- Changed `backend/app/auth/principal.py`, `backend/app/main.py`, `frontend/lib/session.ts`, `frontend/lib/session-destination.mjs`, `frontend/components/auth-form.tsx`, and English/Arabic auth messages. Added a backend regression for the unprovisioned marker and frontend behavior tests.
- Focused results: auth/principal/route/tenant backend tests **68 passed**; frontend session/redirect tests **7 passed**; localization guard and `node --check` passed.
- `npm run build` could not execute the Next build locally: the runtime reported `'next' is not recognized`; CI remains the verification source for the production frontend build on this commit.
