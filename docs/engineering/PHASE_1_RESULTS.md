# SIRALOOM Phase 1 Results

**As of:** 2026-10-15
**Application-code baseline:** `324283be87d28d209d7319e1e599ab898266853d`; audit-record follow-up: `dd4c1e6`.
**Phase status:** IN PROGRESS / PARTIAL. The acceptance criteria are not all met; this report makes no clinical validation or production-readiness claim.

## Implemented in the current work session

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
