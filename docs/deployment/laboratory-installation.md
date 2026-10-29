# SIRALOOM laboratory installation and deployment

This guide deploys the **full SIRALOOM application** on laboratory-controlled infrastructure: Next.js workspace/public routes, FastAPI, PostgreSQL, Redis, Celery worker and single Celery Beat scheduler, local artifact storage, read-only reference data and a persistent resource cache. It is a deployment procedure, not a statement of clinical validation.

## 1. Choose the presentation mode

Set `NEXT_PUBLIC_SIRALOOM_DEPLOYMENT_MODE` before building the frontend:

- `lab`: workspace-first. Marketing pages redirect to login; login, signup, onboarding, privacy and terms remain accessible. The authenticated workspace has its own English/Arabic/bilingual switcher.
- `platform`: full public website and workspace.

The frontend is built into a container with `frontend/Dockerfile`; it can also be deployed separately (for example, on Vercel). For a laboratory installation, use the same versioned release for the frontend, API and worker.

## 2. Infrastructure and prerequisites

- Linux host with Docker Engine and Docker Compose v2.
- A TLS reverse proxy (for example Nginx) and a lab-owned DNS name.
- A lab-owned Firebase project for the current authentication implementation, including a Firebase Admin service-account JSON file. Firebase Authentication remains an external identity dependency in this release; patient VCFs and generated artifacts are stored through the authenticated SIRALOOM API in the configured lab storage.
- PostgreSQL and Redis capacity appropriate to the lab's case volume.
- A validated, indexed reference package mounted read-only.
- Dedicated storage for database, Redis, artifacts, resource cache and worker scratch; backups for durable data, access control, disk/inode monitoring and a retention policy. Scratch may be managed as a separate high-capacity work volume, but its real mount must be shared consistently with the capacity preflight configuration.
- Provider executables, caches and datasets qualified for the intended workflow. A registry row alone does not make a provider executable or clinically validated.

## 3. Prepare lab-owned storage

Copy the template and create the directories configured in it:

```bash
cp .env.production.example .env
chmod 600 .env
sudo mkdir -p /srv/siraloom/postgres /srv/siraloom/redis \
  /srv/siraloom/artifacts /srv/siraloom/references /srv/siraloom/resource-cache \
  /srv/siraloom/scratch /srv/siraloom/beat
```

Edit `.env` before starting the stack. Set the actual absolute host paths in the `SIRALOOM_*_HOST_PATH` variables. These paths are bind-mounted into the API and worker containers; the reference path is read-only. Configure `SIRALOOM_SCRATCH_HOST_PATH`, `SIRALOOM_BEAT_HOST_PATH`, and the artifact/resource-cache paths. Keep exactly one Celery Beat instance active for this deployment; it uses the persistent beat schedule file to coordinate daily discovery and recovery jobs. The API and worker must see the same scratch filesystem at `/data/siraloom/scratch`; the API preflight estimates capacity there, while worker jobs consume it. The backend API, Celery worker, Beat scheduler, and migration command run as UID/GID **10001:10001**. The backend image seeds writable mountpoint ownership for its default named artifact, resource-cache, scratch and Beat volumes; fresh named volumes are checked in CI. For host bind mounts and additional per-organization artifact roots, grant UID/GID 10001:10001 write access only where required. PostgreSQL and Redis use their own image identities; keep the reference mount read-only. Prepare host bind mounts according to your filesystem policy using ownership or ACLs; do not grant world-writable access as a shortcut. CI verifies backend runtime and fresh-volume permissions.

For organization-specific local artifact roots, configure one host path variable per lab and add the corresponding local-target Compose override. The example in [storage-targets-local.compose.example.yml](../../deployment/storage-targets-local.compose.example.yml) mounts each dedicated host path into both API and worker containers; each `ARTIFACT_STORAGE_TARGETS_JSON` local `root` must exactly match its container-side mount target. Add one mount pair to both services for every additional organization. Render and inspect the merged configuration before startup:

```bash
docker compose -f docker-compose.production.yml \
  -f deployment/storage-targets-local.compose.example.yml config
```

The base Compose file's `/data/siraloom/artifacts` volume is the legacy single-root location. It does not mount any additional local target roots. Do not configure per-laboratory roots outside the container without adding explicit mounts to both API and worker.

Copy the approved reference package into `/srv/siraloom/references`; set `REFERENCE_FASTA` and `REFERENCE_FAI` to the matching in-container paths. Do not silently replace a reference build or index after a case has been analyzed.

## 4. Configure identity, secrets and URLs

Set at minimum:

- `POSTGRES_PASSWORD` to a unique secret; URL-encode special characters if used in `DATABASE_URL`.
- `FIREBASE_ADMIN_CREDENTIALS_HOST_PATH` to the protected host path of the Firebase Admin service-account JSON. Compose mounts it as a read-only secret at `/run/secrets/firebase_admin_credentials`. For file-backed Compose secrets, ensure the source file and each parent directory are readable/traversable by the API container identity (UID/GID 10001:10001), while keeping the file restricted to that service identity and laboratory administrators. The Celery worker and Beat scheduler do not receive this credential.
- `FIREBASE_PROJECT_ID` and `FIREBASE_AUTH_REQUIRED=true`.
- `FRONTEND_ORIGIN=https://lab.example.org` and `PUBLIC_BASE_URL=https://lab.example.org`.
- `NEXT_PUBLIC_SIRALOOM_API_BASE=https://lab.example.org/api/v1`.
- The public Firebase web configuration values. These are browser-visible configuration values, not server credentials.
- `NEXT_PUBLIC_SIRALOOM_DEPLOYMENT_MODE=lab` for a workspace-first installation.
- `GENEBE_ENABLED=false` unless a lab has explicitly approved and configured that research/development provider. Do not treat it as a clinically validated provider.

Never commit `.env`, Firebase Admin credentials, API tokens or real patient data.

## 5. Operate scheduled resource discovery

The production Compose stack runs exactly one persistent Celery Beat service. It schedules resource discovery daily and the existing recovery/outbox tasks. After the stack is healthy, an administrator can trigger the first discovery scan manually:

```bash
docker compose -f docker-compose.production.yml exec worker \
  celery -A backend.app.infrastructure.queue.celery_app.celery_app call siraloom.discover_scientific_resources
docker compose -f docker-compose.production.yml logs --tail=200 beat worker
```

Confirm the task result reports the discovered-candidate and failed-provider counts, then check the lab dashboard notifications and Resources catalog. Discovery is not activation: candidates require lab review, qualification, approval and activation. The installed adapter set currently covers ClinVar monthly archived releases only; gnomAD and other providers require separate release-specific adapters. ClinVar releases without publisher-verified checksums or resolved terms remain blocked from generic staging.

## 6. Configure upload and resource limits

The application upload limit defaults to **512 MiB**. It is configurable with `MAX_ARTIFACT_UPLOAD_BYTES`; the example template keeps that conservative default. Do not raise it to 5 or 10 GiB until the ingress, API temporary storage, application staging storage, persistent artifact store, worker scratch, timeouts and concurrent-upload behavior have been measured on the actual deployment.

The Nginx request-body limit must be at least the validated application limit plus multipart overhead. Example directives for a tested 10 GiB deployment might include:

```nginx
client_max_body_size 10g;
proxy_request_buffering off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
```

These settings only configure the proxy; **they do not prove that 10 GiB files are supported**. Monitor proxy temporary storage, API multipart spooling, application staging, persistent storage and free inodes. Run the repository upload-capacity smoke test against disposable cases and record OS-level peak disk usage. The script measures client latency/throughput; it does not measure peak server-side temporary disk by itself.

For remote resource staging, configure `RESOURCE_STAGING_ALLOWED_HOSTS` with exact approved publisher hostnames, `RESOURCE_STAGING_LOCAL_SOURCE_ROOTS` with approved lab-mounted source directories, `RESOURCE_STAGING_MAX_BYTES`, and `RESOURCE_STAGING_TIMEOUT_SECONDS`. An empty publisher allow-list disables remote staging. The generic stager supports public HTTPS files with a verified release checksum, a resolved license/terms status and an exact expected size; authenticated or licensed resources need provider-specific adapters.

## 6. Start the stack

From the repository root:

```bash
docker compose -f docker-compose.production.yml config
docker compose -f docker-compose.production.yml up -d --build
docker compose -f docker-compose.production.yml ps
docker compose -f docker-compose.production.yml logs --tail=200 api worker frontend
```

The API startup script applies database migrations before serving. Workers wait for API health and Redis. The frontend image is built with the public API and Firebase web configuration; changing those public values requires rebuilding the frontend image.

The frontend and API ports bind to loopback by default (3000 and 8000). Put the lab's TLS reverse proxy on the host and route `/api/` to `http://127.0.0.1:8000` and all other application paths to `http://127.0.0.1:3000`. Do not expose PostgreSQL or Redis publicly.

After TLS/reverse-proxy configuration, verify:

```bash
curl -fsS https://lab.example.org/api/v1/health
curl -fsS https://lab.example.org/api/v1/ready
```

A healthy liveness response is not enough: readiness, migrations, authenticated frontend access and worker processing must all be checked.

## 7. Provision the organization and resources

1. Sign in with an approved account and provision the initial organization using the documented bootstrap process. If `ORGANIZATION_FIRST_BOOTSTRAP_ENABLED` is temporarily enabled, disable it immediately after the first organization is created.
2. Create organization memberships and assign only the roles required by the lab.
3. In **Resources**, register each resource version with exact provider/version/build, source contract, license/terms status, checksum and execution contract.
4. For public HTTPS file releases, configure the publisher allow-list and provide the exact published SHA-256 and release size. Run storage preflight, queue staging, verify the observed hash/size, then qualify, approve and activate the resource.
5. For local executables, caches, authenticated APIs or licensed resources, follow the provider-specific registration and qualification path. Do not label a resource active merely because it has been registered.

## 8. Verify with a non-sensitive test VCF

Use [the lab E2E runbook](../validation/lab-e2e-signout.md) and record the exact deployed commit, organization, resource profile/version, input SHA-256, analysis ID, report ID, artifact hashes and timestamps. Verify intake/download, normalization, annotation, population/evidence, review gates, reportability, sign-out, audit, recovery after worker/broker interruption and a fresh-session report download.

Do not use identifiable patient data for the initial test. Do not call the system clinically validated until the laboratory completes and approves its intended-use validation.

## 9. Backup and upgrade policy

- Pause new submissions and wait for active analyses to reach a durable state. Create a bundle from the repository root; the script stops the currently running API, worker and Beat services with a 300-second graceful-shutdown timeout, dumps PostgreSQL in custom format, archives the configured artifact, reference and resource-cache bind mounts, verifies checksums and archive paths, then restarts the services that were running before backup:

  ```bash
  BACKUP="/srv/siraloom/backups/$(date -u +%Y%m%dT%H%M%SZ)"
  python3 scripts/laboratory_backup.py create "$BACKUP"
  python3 scripts/laboratory_backup.py verify "$BACKUP"
  ```

  The backup is written to a new directory and contains no `.env` or identity-provider credentials. Configure host-level encryption, off-host replication, access controls and retention for the backup destination. The tool requires artifacts, references and resource cache to be absolute host bind mounts; it refuses to silently omit named volumes or symlinks. PostgreSQL uses `pg_dump` custom format, which is restored with `pg_restore`.
  The current bundle implementation backs up local filesystem artifact storage only. Before stopping writers it checks the database for Firebase/GCS storage profiles and `gs://` artifact records and refuses to create a bundle when either exists. A cloud-backed laboratory must use its approved, coordinated GCS backup/export procedure; do not treat a local-only bundle as complete for a deployment that uses cloud artifacts.
- Test restoration into a fresh database and new storage directories before changing the live deployment. Use an isolated Compose project and a separate environment file/Redis instance for the restore test so queued messages from the live system cannot execute against the restored database. The restore command requires a project name exactly `siraloom_restore` or beginning `siraloom_restore_`/`siraloom_restore-`, requires an explicit existing environment file, and refuses to proceed while API, worker, Beat, or frontend services are running in that project. Start from a secured copy of the laboratory environment file with unique paths and a dedicated PostgreSQL/Redis deployment:

  ```bash
  mkdir -p /srv/siraloom-restore
  docker compose -p siraloom_restore \
    --env-file /srv/siraloom-restore/.env \
    -f docker-compose.production.yml up -d postgres redis
  python3 scripts/laboratory_backup.py restore \
    /srv/siraloom/backups/20261026T120000Z \
    --database siraloom_restore_20261026 \
    --artifacts-target /srv/siraloom-restore/artifacts \
    --references-target /srv/siraloom-restore/references \
    --resource-cache-target /srv/siraloom-restore/resource-cache \
    --project-name siraloom_restore \
    --env-file /srv/siraloom-restore/.env
  ```

  Before this command, configure the isolated `.env` with a new PostgreSQL data path, a new Redis data path, a bootstrap `POSTGRES_DB` different from the target restore database, and the target artifact/reference/cache bind paths. Create only the shared parent directory (`/srv/siraloom-restore`); the three final target directories must not exist. Restore targets must be new absolute paths; the database name must be distinct from both the backup source and the currently configured database. Review the output, change `POSTGRES_DB` and `DATABASE_URL` to the restored database, then start the API and worker in this isolated project. Run authenticated workflow checks and compare stored artifact hashes before calling the restore successful. The restore command does not modify `.env`, start application services, or prove that a laboratory recovery objective has been met. Record the tested backup ID, source commit, restore time, resulting database, artifact verification, operator and observed recovery time.
- Do not count Redis queues, Beat schedule files, scratch files or provider credentials as the scientific system of record. Use a fresh broker for the isolated restore and run the application's durable dispatch recovery process after inspection. Preserve the exact reference, provider versions, resource checksums, workflow versions and report artifacts needed to reproduce historical results.
- Upgrade frontend, API and worker as one versioned release; run migrations through the API/release step, then verify readiness before allowing new cases.
- Keep the previous deployment image and database/artifact backups until rollback is tested.
