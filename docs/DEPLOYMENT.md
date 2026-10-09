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

## Celery Beat

Run exactly one Celery Beat scheduler for the deployment:

```bash
./scripts/start_beat.sh
```

Beat publishes the durable resource-change scan task on the configured schedule. It does not perform the scan itself; the Celery worker executes `siraloom.scan_reanalysis_resources`. Do not run multiple Beat instances against the same deployment unless an external scheduler/leader-election mechanism is explicitly in place.

A newly registered scientific resource also triggers a best-effort immediate scan after the registry transaction commits. If the queue is temporarily unavailable, the resource registration remains successful and the daily Beat scan is the recovery mechanism. Resource registration never silently mutates completed analyses.

The current application schedule is daily at 00:00 UTC:

```text
scan-reanalysis-resources-daily
→ siraloom.scan_reanalysis_resources
→ scan active registered resources
→ create durable reanalysis candidates/notifications
```

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

## Artifact upload capacity

The API enforces a configurable per-file ceiling through `MAX_ARTIFACT_UPLOAD_BYTES` (default: `536870912`, or 512 MiB). Trial entitlements may impose a lower ceiling; they cannot raise the deployment limit. Laboratory deployments may increase this setting only after sizing the API's multipart temporary storage, persistent artifact storage, concurrent upload count, and available disk headroom.

Configure the reverse proxy or ingress request-body limit to the same value or lower. The endpoint-level check runs while reading the multipart upload, but the ASGI multipart parser may already have spooled request bytes to temporary storage before the endpoint executes; therefore this setting is not, by itself, protection against ingress-level disk exhaustion. Monitor temporary-disk free space and reject overload at the ingress layer. Do not set an unlimited value.

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
5. Start exactly one Celery Beat scheduler.
6. Verify `/health` and `/ready`.
7. Deploy frontend with production API/Firebase variables.
8. Add frontend domain to Firebase Authorized Domains.
9. Run the live VCF validation runbook.
10. Record deployment revision and validation evidence.

## Important

A public software demo is a software/reproducibility validation environment. It is not a clinical diagnostic service and must not receive identifiable patient data.
