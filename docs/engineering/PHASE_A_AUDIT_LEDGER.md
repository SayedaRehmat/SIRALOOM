# SIRALOOM Phase A Engineering Audit Ledger

**Updated:** 2026-10-13  
**Audit baseline:** `main` as fetched from GitHub on 2026-10-13  
**Active batch:** A1 — identity and authentication environment boundary  
**Status:** Implementation committed to `audit/phase-a-auth-fail-closed`; automated verification is pending CI. This is not a phase-completion declaration.

## Confirmed findings

| ID | Severity | Area | Evidence in baseline | Root cause | Correction | Verification |
|---|---|---|---|---|---|---|
| A1-AUTH-001 | High | Authentication / environment isolation | `backend/app/auth/principal.py:get_current_principal` | When no Bearer token was supplied, the fallback rejected only when Firebase auth was required or `APP_ENV == production`. Any other environment (for example staging or preview) could receive the implicit shared development identity when `FIREBASE_AUTH_REQUIRED=false`. | Restrict implicit identity to explicit `development` or `test` environments; all other environments fail closed with HTTP 401. | Added `tests/test_auth_environment_boundary.py` for staging, preview, production, and local-development behavior. Execution is pending CI; do not treat the test as passed until a run is observed. |

| A3-CASE-001 | Medium | Case lifecycle / duplicate submission | `backend/app/api/v1/cases.py:create` and the `Case` uniqueness constraint | The pre-insert existence query and insert were not atomic. Concurrent requests could both observe no row; the unique constraint prevented duplicate data but the losing request surfaced an unhandled `IntegrityError` rather than returning the winning case. | PR #186 catches the flush-time integrity error, rolls back, and returns `created: false` only if the same organization-scoped case identifier now exists; unrelated integrity errors are re-raised. | Regression tests added in PR #186; CI run #1411 was in progress at last check. |

## Change set

- `backend/app/auth/principal.py`: changed the no-token branch to allow the development identity only for normalized `development` and `test` environment names, while retaining the explicit Firebase-auth-required gate.
- `tests/test_auth_environment_boundary.py`: added regression coverage for shared-environment rejection and the local development path.

## Requirements traceability — initial checkpoint

| Requirement | Code entry point inspected | Current checkpoint |
|---|---|---|
| A1: Authentication environment boundary | `backend/app/auth/principal.py:get_current_principal` | One confirmed defect corrected; backend tests and PostgreSQL/Celery integration passed in run #1410; remaining CI jobs were still in progress at last check |
| A1: Firebase token verification and active membership | `backend/app/auth/principal.py:_verify_firebase_token`, `get_current_principal` | Source inspected; broader token/configuration and membership lifecycle audit remains open |
| A1/A2: Role and tenant authorization | `backend/app/auth/authorization.py`, `require_case_tenant` | Shared authorization helpers inspected; endpoint-by-endpoint coverage remains open |
| A3: Case lifecycle | `backend/app/api/v1/cases.py:create`, `update_case`, `create_specimen` | Concurrent duplicate submission correction proposed in PR #186; CI pending. Audit transaction, specimen identity, and state-invariant tests remain open |
| A4/A5: VCF intake and workflow execution | `backend/app/domain/vcf_validation.py`, `backend/app/workflows/variant.py`, `backend/app/application/analysis.py` | Entry points inspected; full transition/caller audit and live worker recovery verification remain open |
| A6/A7/A8: Evidence, review, reporting, reanalysis | `backend/app/api/v1/reports.py`, `backend/app/api/v1/reanalysis.py` and workflow implementation | Entry points inspected; complete trace and integration tests remain open |

## Verification record

- Repository main branch and current README / dependency manifest fetched from GitHub.
- Authentication principal, authorization helpers, case API, analysis dispatch, workflow orchestration, VCF validation, report API, reanalysis API, DB models, readiness endpoint, and release/acceptance documents inspected at source level.
- Authentication regression tests passed in GitHub Actions backend job; PostgreSQL/Celery integration job passed. PR #185's frontend container/Compose verification was still in progress at last check. PR #186's test run was in progress at last check; no result is claimed for it yet.
- No production data or deployment was changed.

## Remaining work

1. Observe CI for this batch; fix any failures before considering the batch verified.
2. Continue A1: inspect signup/invitation/membership revocation and authorization in background workers, then add integration tests for expired/revoked/cross-tenant identities.
3. Continue A2/A3: resource ownership/approval, case uniqueness under concurrent creation, artifact/specimen identity, and transaction/audit integrity.
4. Trace the complete workflow state machine from durable dispatch through every stage, retries, leases, worker death, human review, signout, and reanalysis.
5. Build an endpoint-to-role-and-tenant regression matrix; then continue the remaining Phase A requirements.
6. Phase B and Phase C remain gated behind the Phase A checkpoint as requested.

## Interpretation rules

- “Inspected” means source was retrieved and reviewed; it does not mean every path is audited.
- “Implemented” means a code change exists; it does not mean tests passed.
- “Verified” requires recorded test/runtime evidence.
- Passing CI or merging a PR does not establish clinical validation or deployment qualification.
