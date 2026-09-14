# SIRALOOM Variant — Phase 1 Implemented Files

This package contains the cumulative Phase 1 implementation baseline through the end-to-end UI/report milestone.

## Backend

- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/api/v1/*`
- `backend/app/domain/*`
- `backend/app/application/*`
- `backend/app/acmg/*`
- `backend/app/review/*`
- `backend/app/reporting/*`
- `backend/app/infrastructure/*`
- `backend/app/workflows/variant.py`

## Frontend

- `frontend/app/page.tsx` — complete Phase 1 workflow UI
- `frontend/app/globals.css` — responsive UI design
- `frontend/app/layout.tsx` — metadata and global shell
- `frontend/package.json`
- `frontend/next.config.ts`

## Persistence and contracts

- `migrations/versions/0001_initial.py` through `0009_reporting_exports.py`
- `schemas/variant/*`
- `schemas/evidence/*`
- `schemas/events/*`
- `schemas/reports/*`
- `workflows/variant/v1.yaml`

## Validation documentation

- `docs/validation/phase1-status.md`
- `docs/validation/evidence-status.md`
- `docs/validation/acmg-status.md`
- `docs/validation/criterion-evaluators-status.md`
- `docs/validation/review-status.md`
- `docs/validation/ui-status.md`

## Important status

This is a development/architecture baseline. Clinical validation, production identity/RBAC, electronic-signature validation, and regulatory certification are not claimed by this package.

- `backend/app/reporting/reportability.py` — M6 first-class versioned reportability policy/decision engine
- `backend/app/api/v1/reports.py` — M6 reportability evaluation/review and report version endpoints
- `backend/app/reporting/service.py` — M6 clinical vs analytical report content contract
- `backend/app/reporting/finalization.py` — M6 report artifact/sign-out gate and supersession
- `migrations/versions/0013_reportability_decisions.py` — M6 additive reportability table
- `frontend/app/(app)/app/reports/page.tsx` — M6 reporting/sign-out workspace
