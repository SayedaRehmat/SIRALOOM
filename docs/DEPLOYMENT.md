# SIRALOOM Variant Deployment

## Recommended public demonstration architecture

```text
Vercel / Next.js
        │ HTTPS
        ▼
FastAPI API (container)
        │
   ┌────┴───────────────┐
   ▼                    ▼
PostgreSQL            Redis
                          │
                          ▼
                    Celery worker
                          │
                          ▼
                 Artifact/reference storage
                          │
                          ▼
                    GeneBe (research)
```

The frontend is never the execution engine. Long analyses stay on the backend worker and are polled from the UI.

## Frontend: Vercel

Set these Vercel Production environment variables:

```text
NEXT_PUBLIC_SIRALOOM_API_BASE=https://YOUR-API-DOMAIN/api/v1
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
```

Never place `GENEBE_API_KEY`, database passwords, Firebase Admin credentials, or private signing secrets in `NEXT_PUBLIC_*` variables.

After deployment, add the Vercel hostname to Firebase Authentication authorized domains.

## Backend: container

Build and run the backend image with:

```bash
docker build -f docker/backend.Dockerfile -t siraloom-variant-api:phase1 .
```

The backend requires PostgreSQL, Redis, a writable artifact root, and a mounted/reference-managed FASTA + FAI for reference-aware normalization.

## Worker

Run the worker separately from the API:

```bash
./scripts/start_worker.sh
```

The worker must share the same database, Redis, artifact store, reference resources, application code/version, and secrets as the API.

## Environment

Copy `.env.production.example` to a secret-managed environment. Do not commit `.env`.

Required production concepts:

```text
DATABASE_URL
REDIS_URL
ARTIFACT_ROOT
PUBLIC_BASE_URL
FRONTEND_ORIGIN
FIREBASE_AUTH_REQUIRED=true
FIREBASE_PROJECT_ID
FIREBASE_CREDENTIALS_PATH
REFERENCE_FASTA
REFERENCE_FAI
```

GeneBe is optional at the software level but required for the current development annotation path. Its credentials remain server-side.

## Health checks

```bash
curl https://YOUR-API-DOMAIN/api/v1/health
curl https://YOUR-API-DOMAIN/api/v1/ready
```

`/health` is liveness. `/ready` checks required runtime dependencies/configuration.

## Production release order

1. Build backend image.
2. Start PostgreSQL and Redis.
3. Start API; migration-safe startup applies Alembic migrations.
4. Start worker.
5. Verify `/health` and `/ready`.
6. Deploy frontend with production API/Firebase variables.
7. Add frontend domain to Firebase Authorized Domains.
8. Run the live VCF validation runbook.
9. Record deployment revision and validation evidence.

## Important

A public software demo is a software/reproducibility validation environment. It is not a clinical diagnostic service and must not receive identifiable patient data.
