# SIRALOOM Phase A Engineering Audit Ledger

**Updated:** 2026-10-13  
**Audit baseline:** current `main` after merges of PRs #185 and #186  
**Active batch:** A1–A3 — authentication, membership authorization, and case-create concurrency  
**Status:** PR #185 and PR #186 are merged. Their CI runs #1410 and #1411 passed all backend, PostgreSQL/Celery integration, and frontend/Compose jobs. Follow-up branch `audit/phase-a-postgres-case-race` adds a true PostgreSQL race test and membership authorization tests; that branch is awaiting CI. **Phase A is not complete.**

## Confirmed findings and corrections

| ID | Severity | Area | Evidence / root cause | Correction | Verification |
|---|---|---|---|---|---|
| A1-AUTH-001 | High | Authentication environment isolation | `get_current_principal()` allowed implicit development identity when Firebase auth was optional and `APP_ENV` was anything except `production`. Shared staging/preview could therefore accept unauthenticated requests. | PR #185 restricts implicit identity to explicit `development` or `test`; other environments fail closed with HTTP 401. | Merged as `5735d57652ff5d5c12a798863471db99ade72e7a`; CI run #1410 passed all three jobs. |
| A1-AUTH-003 | High | Single-use invitation acceptance | `backend/app/api/v1/auth.py:accept_organization_invitation` selected a PENDING invitation without a row lock, so two concurrent accepts could both observe PENDING and provision membership state before either commits. | Added `SELECT ... FOR UPDATE` on the invitation lookup so acceptance and the ACCEPTED status transition serialize in the same transaction; added a PostgreSQL race integration test expecting one acceptance and one HTTP 409. | Follow-up CI pending. |
| A1-AUTH-004 | High | Cross-invitation identity provisioning | `_provision_organization()` and `accept_organization_invitation()` checked for an existing Firebase subject without a shared concurrency boundary. Distinct invitation tokens could race and create duplicate user rows for one subject. | Added a PostgreSQL transaction-scoped advisory lock keyed by SHA-256 of the verified subject in both provisioning paths; added an integration test that accepts distinct invitations for the same identity concurrently. | Follow-up CI pending. |
| A1-AUTH-002 | Medium | Membership authority | Resolver reads active membership and derives the effective role from membership, not the user role. Regression tests for stale role divergence, suspended/revoked membership, and unknown roles were absent from this audit batch. | Added `tests/test_principal_membership_authorization.py` on follow-up branch. | Follow-up CI pending. |
| A3-CASE-001 | Medium | Duplicate case creation | The pre-insert existence query and insert were not atomic. The database unique constraint prevented duplicate rows but the losing concurrent request raised an unhandled `IntegrityError`. | PR #186 rolls back and returns the matching tenant-scoped case when another request won the insert; unrelated errors are re-raised when no matching case exists. | Merged as `16d2b931beb56a09f2a6eedfeb44b42d6b15bcef`; CI run #1411 passed all three jobs. |
| A3-CASE-002 | Medium | Real concurrency evidence | The original PR #186 unit test used a mocked session; it did not demonstrate a simultaneous PostgreSQL insert race. | Added a barrier-synchronized test to `tests/integration/test_analysis_dispatch_postgres.py` asserting one durable case, one `CASE_CREATED` audit event, and responses `created=true/false`. | Follow-up CI pending. |

## Change and CI record

- PR #185: https://github.com/SayedaRehmat/SIRALOOM/pull/185 — merged; CI run #1410 passed backend, PostgreSQL/Celery integration, and frontend/container/Compose jobs.
- PR #186: https://github.com/SayedaRehmat/SIRALOOM/pull/186 — merged; CI run #1411 passed backend, PostgreSQL/Celery integration, and frontend/container/Compose jobs.
- Follow-up branch: `audit/phase-a-postgres-case-race` — adds PostgreSQL case-creation race coverage, membership-principal tests, row locking for single-use invitation acceptance, and subject-scoped advisory locking across distinct invitations/onboarding with PostgreSQL concurrency tests. CI result has not yet been observed.
- The regression tests and merges do not establish production deployment, clinical validity, accreditation, or clinical qualification.

## Requirements traceability

| Requirement | Code inspected | Current checkpoint |
|---|---|---|
| A1: Authentication environment boundary | `backend/app/auth/principal.py:get_current_principal` | Corrected and merged; run #1410 passed. |
| A1: Firebase token verification and active membership | `backend/app/auth/principal.py:_verify_firebase_token`, `get_current_principal` | Source checks revoked Firebase tokens and requires active membership; follow-up role/status tests pending. |
| A1: Invitation and membership lifecycle | `backend/app/api/v1/auth.py`, `backend/app/infrastructure/db/organization_invitations.py` | Invitation acceptance locks the invitation row and both onboarding/acceptance paths serialize provisioning by verified subject on PostgreSQL; single-token and cross-invitation concurrency tests are pending CI. Membership mutation races remain open. |
| A2: Role and tenant authorization | `backend/app/auth/authorization.py` and API routes | Shared helpers inspected; complete endpoint-by-endpoint and background-worker authorization matrix remains open. |
| A3: Case lifecycle | `backend/app/api/v1/cases.py`, `backend/app/infrastructure/db/models.py` | Duplicate fix merged; true PostgreSQL race test pending. Specimen identity, update races, and audit transaction coverage remain open. |
| A4/A5: VCF intake and workflow execution | `backend/app/domain/vcf_validation.py`, `backend/app/workflows/variant.py`, `backend/app/application/analysis.py` | Durable dispatch and generic PostgreSQL/Celery worker-loss tests exist; stage-body recovery across all scientific and reporting stages is not yet proven. |
| A6: Evidence and classification | Workflow and evidence adapters/models | Source inspected; complete failure/replay and provenance tests remain open. |
| A7: Human review, reportability, sign-out, reporting | Report/review APIs and reporting services | Source inspected; full authorization/state-transition matrix and deployed E2E remain open. |
| A8: Reanalysis and reproducibility | `backend/app/api/v1/reanalysis.py`, analysis/resource snapshots | Source inspected; complete reanalysis replay and cross-version reproducibility tests remain open. |

## Remaining work before Phase A can be declared complete

1. Complete follow-up CI and merge only after tests pass.
2. Complete CI for the single-token and cross-invitation provisioning tests; audit invitation revocation races and membership mutation invariants.
3. Finish endpoint-to-role-and-tenant coverage, including artifact downloads, report finalization, evidence/review mutations, and every worker/task entry point.
4. Add/verify PostgreSQL concurrency tests for case updates, specimen identity, report/review version allocation, and active-admin invariants.
5. Exercise actual stage-body recovery after worker loss for normalization, annotation, population, evidence, ACMG/review transitions, report creation, sign-out, and reanalysis. Generic worker-loss integration is not proof that every stage body is idempotent.
6. Complete deployed environment checks, approved-resource recovery, storage/ingress capacity testing, and scientific benchmark validation from `docs/PHASE1_ACCEPTANCE_MATRIX.md`.

**Decision:** do not label Phase A complete while these verification items remain open. Phase 1 clinical/scientific qualification is a separate release gate.
