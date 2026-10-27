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
REDIS_PASSWORD
ARTIFACT_ROOT
ARTIFACT_STORAGE_TARGETS_JSON
PUBLIC_BASE_URL
FRONTEND_ORIGIN
FIREBASE_AUTH_REQUIRED=true
FIREBASE_PROJECT_ID
FIREBASE_CREDENTIALS_PATH
REFERENCE_FASTA
REFERENCE_FAI
```

Set `REDIS_PASSWORD` to a cryptographically generated secret with at least 32 characters; for the included Compose deployment, use `openssl rand -hex 32`. Production Compose starts Redis with `requirepass` and injects an authenticated `REDIS_URL` into API, worker, and Beat. Do not publish Redis ports. The application rejects production startup with a missing or weak Redis AUTH secret. For an externally managed Redis service, set `REDIS_URL` directly to an authenticated `redis://` or `rediss://` URL with a 32-character minimum password; use TLS (`rediss://`) when traffic crosses an untrusted network. Protect the secret through the laboratory's secret-management process and rotate it in coordination with all application services.

Redis authentication follows Redis's documented `AUTH`/`requirepass` behavior; Redis ACL users are an alternative for deployments that need command/key-level restrictions ([Redis AUTH](https://redis.io/docs/latest/commands/auth/), [Redis ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)). This Compose setup authenticates the default user but does not impose a custom command allowlist.

GeneBe is optional at the software level but required for the current development annotation path. Its credentials remain server-side.

### Organization-specific artifact stores

For a deployment serving multiple laboratories, configure a deployment-owned target allowlist and assign one target ID to each organization's active storage profile. Profile configuration may contain only `target_id`; filesystem paths, bucket names, credentials, and cloud settings remain controlled by the deployment administrator. For example:

```json
{
  "lab-a-files": {"backend_type": "LOCAL_FILESYSTEM", "root": "/srv/siraloom/labs/lab-a/artifacts", "organization_id": "<Lab A organization UUID>"},
  "lab-b-files": {"backend_type": "LOCAL_FILESYSTEM", "root": "/srv/siraloom/labs/lab-b/artifacts", "organization_id": "<Lab B organization UUID>"},
  "lab-c-cloud": {"backend_type": "FIREBASE_GCS", "bucket": "lab-c-siraloom-artifacts", "organization_id": "<Lab C organization UUID>", "project_id": "lab-c-project", "credentials_path": "/run/secrets/lab-c-storage-service-account.json"}
}
```

Set this JSON as `ARTIFACT_STORAGE_TARGETS_JSON` in the API and every worker environment. Each target must be bound to the exact organization UUID, preventing cross-organization target reuse even during concurrent profile activation. Filesystem roots must be mounted and writable only by the appropriate service identity. A cloud target may include its laboratory-owned `project_id` and an absolute `credentials_path` to a read-only mounted service-account file; the file contents are never placed in environment JSON, the database, or API responses. The Firebase Admin Python SDK supports named apps and permits bucket selection with the app, keeping each target's client bound to the configured credentials ([Admin SDK initialization](https://firebase.google.com/docs/reference/admin/python/firebase_admin), [Storage bucket API](https://firebase.google.com/docs/reference/admin/python/firebase_admin.storage)). If no target credential file is supplied, that target uses Google Application Default Credentials and does not inherit the Firebase Auth service-account file. Each target uses a separately named Firebase Admin app and selects its configured bucket through that app. The administrator creates a profile with `configuration: {"target_id": "lab-a-files"}`; activation rejects unknown targets, organization mismatches and backend mismatches. For Docker Compose, [storage-targets.compose.example.yml](../deployment/storage-targets.compose.example.yml) shows how to mount a target credential file read-only into both API and worker. Restart API and workers after changing a target's credential or project configuration so the named Firebase apps are recreated with the new configuration. Keep retired target entries configured for as long as historical artifacts on them must remain retrievable; removing one makes its historical artifacts unavailable while leaving a valid active target usable. Historical downloads resolve only against active or retired target bindings for that organization and continue through canonical URI and checksum validation. When this setting is empty, deployments retain legacy single-root/single-bucket behavior; that compatibility mode does not provide per-laboratory storage separation.

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

1. Generate and set the production `REDIS_PASSWORD`, then build the backend image.
2. Start PostgreSQL and authenticated Redis.
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
