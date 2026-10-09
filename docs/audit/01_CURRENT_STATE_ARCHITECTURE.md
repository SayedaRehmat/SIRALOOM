# Current-state architecture — initial evidence map

## Observed components

- **Frontend:** Next.js/React/TypeScript, with public marketing/auth routes and protected `/app` workspaces.
- **API:** FastAPI routes under `backend/app/api/v1/`, including cases, artifacts, analyses, resources, storage, reanalysis, review, reports, audit, evidence and population.
- **Identity/tenancy:** Firebase ID-token verification in `backend/app/auth/principal.py`; active organization membership and role checks are applied server-side.
- **Persistence:** SQLAlchemy models and Alembic migrations; latest observed migration is `0046_organization_storage_profiles.py`.
- **Async execution:** Celery/Redis; durable dispatch/outbox records and scheduled reconcilers are configured in `backend/app/infrastructure/queue/celery_app.py`.
- **Scientific workflow:** `backend/app/workflows/variant.py`, with explicit ten-step workflow identifiers: validate input, normalize, annotate, population, build evidence, ACMG assessment, review, reportability, report, export provenance.
- **Resources:** registry, qualification, organization binding, staging/discovery, execution contracts, profile resolver, fallback and resource snapshots.
- **Artifacts:** local filesystem adapter and Firebase/Cloud Storage adapter; organization-specific storage profile resolution.
- **UI deployment:** repository documentation describes Vercel frontend and separate API/worker/Beat services; this audit did not verify live deployment configuration.

## Main execution path to verify in a live environment

1. Authenticated user submits case/artifact request.
2. API verifies identity, membership, role, case ownership and entitlement.
3. Artifact bytes are streamed/staged; hash, size and validation metadata are persisted.
4. Analysis is created against the case and source artifact.
5. Resource preflight resolves the selected profile against deployment type, assembly and organization bindings.
6. Durable workflow steps and dispatch intent are persisted.
7. Relay publishes a task; worker claims the analysis and resumes from persisted workflow state.
8. Each stage records outputs, status, evidence and resource provenance.
9. Human review/reportability gates authorize report finalization.
10. Report and provenance export are persisted and downloadable only through authorized routes.
11. Resource changes can generate reanalysis candidates without mutating historical analyses.

This is the intended/implemented architectural path inferred from current code. Each edge still needs integration proof; the list is not a claim that a production execution has been observed.

## Trust boundaries

- Browser ↔ API over HTTPS.
- Firebase token ↔ backend token verification.
- Tenant-scoped API ↔ shared relational database.
- API ↔ artifact store.
- API/worker ↔ Redis broker.
- Worker ↔ scientific tools, reference files and external provider APIs.
- Organization-approved resources ↔ platform-wide resources.
- Automated assessment ↔ human interpretation and sign-out.
- Deployment control plane ↔ runtime secrets and production infrastructure.

## Current-state risks and questions

- Verify every artifact/report/export access path performs server-side tenant authorization, including indirect IDs and asynchronous task status.
- Verify worker storage resolution uses the same organization-specific profile as the API, including remote artifact materialization and checksum verification.
- Verify every analysis stage records the exact resource contract actually used, not only the preflight selection.
- Verify report sign-out is impossible when required provenance or review gates are incomplete.
- Reconcile documentation with current code: `docs/validation/phase1-status.md` contains older statements about multiallelic and normalization scope that may not reflect the latest mainline changes.
- Confirm the production frontend, API, PostgreSQL, Redis, worker, Beat, artifact store and reference package all run compatible revisions/configuration.

## Evidence files

- `docs/architecture.md`
- `docs/SCIENTIFIC_LAB_WORKFLOW_SPECIFICATION_V1.md`
- `docs/security.md`
- `docs/DEPLOYMENT.md`
- `backend/app/api/v1/analyses.py`
- `backend/app/api/v1/artifacts.py`
- `backend/app/application/analysis.py`
- `backend/app/workflows/variant.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `migrations/versions/0036_analysis_dispatch_outbox.py`
