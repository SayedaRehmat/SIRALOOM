# Milestone 15 — Phase-1 Release & Validation Gate

## Objective

Freeze the Phase-1 feature boundary and move from feature construction to deployment, scientific benchmark validation, and live end-to-end verification.

## Delivered in M15

- Phase-1 release status document
- Requirement/acceptance matrix
- Live VCF deployment runbook
- Production deployment runbook
- Frontend container definition
- GitHub CI for backend tests/compile and frontend production build
- Live health/readiness validation script
- Partition lease heartbeat/recovery hardening
- Fixed recovered-partition scheduler success path
- Removed duplicate annotation reconciliation query

## Explicitly not claimed

- clinical validation
- regulatory certification
- accreditation
- production WGS performance
- clinical use of GeneBe
- successful live infrastructure execution until the deployment environment is actually exercised

## Release gate

The next proof is a real deployed run using a public benchmark or authorized de-identified VCF, with a recorded case/analysis ID, workflow timestamps, provider/resource versions, report hash, and provenance export.
