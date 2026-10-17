# SIRALOOM Phase 1 Results

## Current checkpoint — 2026-10-17

**Latest pushed application baseline:** `main` commit `e4573a9`. CI #1593 passed report draft-artifact lineage checks and #1594 passed report signout UI recovery. Commit `e4573a9` extends lineage enforcement to report listings: draft artifact lineage is checked and FINAL reports must have a valid signed artifact before artifact IDs are listed. CI #1596 is running.

This continuation repaired two real clinical-governance defects: the secondary-finding request schema lacked the `status` field the route dereferenced, and four create routes serialized ORM-generated timestamps before flushing new rows. Regression coverage now exercises confirmation, follow-up, secondary finding, and QC observation creation with a SQLite session and checks their audit snapshots. The status-field regression first caused run #1582 to fail and identified the route defect; the correction passed run #1583.

Additional tenant-lineage fixes in commits `14b819d`, `81a604c`, `a8ccc3f`, and `fcd0efe` cover notification references, secondary-finding variants, quality assay ownership, case-phenotype analysis linkage, and report-to-case linkage; the associated CI runs passed as recorded in the master ledger.

Commit `147062a` constrains governance states; CI #1584 passed. Commits `5a5e788` and `32f8e84` add tests and enforce the implemented resource-staging backend contract. Test-first run #1585 failed with 1 failed, 883 passed, 24 skipped; the fix passed all jobs in run #1586. This session found and fixed a draft report PDF lineage gap (`d6d7ec7`): report access now checks the linked artifact's case, analysis, type, validation state, and any present report identity/version/state metadata; newly generated drafts record report ID/version. New parameterized direct-object regressions cover malformed links. Run #1593 passed all jobs. Python tests could not run locally because the Windows Python launcher is unavailable. Commit `4458859` fixes reportability/report signout UI feedback when the API mutation succeeds but its subsequent refresh fails; it reports a localized recovery message instead of unconditional success. CI #1594 is running. Frontend behavior tests passed 20/20, i18n guard passed, and `git diff --check` passed locally. The unrelated untracked backup artifact remains untouched.

**Phase 1 remains PARTIAL.** The stage matrix still records all 13 journeys as partial; live Firebase/browser signup, verification, recovery, token/session invalidation, deployed direct cross-tenant checks, a complete reviewer-to-signed-report journey, and integrated failure recovery have not been demonstrated. No clinical validation, regulatory authorization, or production-readiness claim is made.

### 2026-10-17 direct-object and signout recovery continuation

- **Direct-object finding:** `get_accessible_report` validated the report's tenant, case-analysis lineage, and final signed artifact but did not validate a non-null draft `artifact_id`. The report could expose a stale or cross-case PDF reference.
- **Correction:** `has_valid_draft_artifact` now verifies case, analysis, PDF type, validation state, and explicit metadata identity when present. New draft reports persist report ID/version metadata; legacy draft artifacts without those optional fields remain supported if their case/analysis/type are valid.
- **Regression coverage:** six parameter cases reject a draft artifact with wrong case, analysis, type, report ID, version, or state. CI #1593 passed all jobs. Local backend pytest was unavailable (`python.exe` is only a Windows Store stub).
- **Signout UI recovery finding:** reports UI mutation handlers always displayed success after `load()` even though `load()` swallowed refresh errors. Commit `4458859` checks the refresh outcome and shows a new English/Arabic “mutation succeeded, latest status unavailable” message. Frontend behavior tests passed 20/20; i18n validation and `git diff --check` passed. CI #1594 passed.
- **Report list follow-up:** `GET /analyses/{analysis_id}/reports` previously returned draft/signed artifact references after only checking case linkage. Commit `e4573a9` validates draft artifact lineage on every row and rejects finalized rows whose signed artifact fails integrity checks; route regressions cover both cases. CI #1596 is running.
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

### Additional sign-in state routing fix

- Changed `backend/app/auth/principal.py`, `backend/app/main.py`, `frontend/lib/session.ts`, `frontend/lib/session-destination.mjs`, `frontend/components/auth-form.tsx`, and English/Arabic auth messages. Added a backend regression for the unprovisioned marker and frontend behavior tests.
- Focused results: auth/principal/route/tenant backend tests **68 passed**; frontend session/redirect tests **7 passed**; localization guard and `node --check` passed.
- `npm run build` could not execute the Next build locally: the runtime reported `'next' is not recognized`; CI remains the verification source for the production frontend build on this commit.
