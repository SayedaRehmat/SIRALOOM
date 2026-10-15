# SIRALOOM Phase 1 Results

**As of:** 2026-10-15
**Application-code baseline:** `324283be87d28d209d7319e1e599ab898266853d`; audit-record follow-up: `dd4c1e6`.
**Phase status:** IN PROGRESS / PARTIAL. The acceptance criteria are not all met; this report makes no clinical validation or production-readiness claim.

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
