# SIRALOOM laboratory installation and deployment

This guide deploys the **full SIRALOOM application** on laboratory-controlled infrastructure: Next.js workspace/public routes, FastAPI, PostgreSQL, Redis, Celery worker, local artifact storage, read-only reference data and a persistent resource cache. It is a deployment procedure, not a statement of clinical validation.

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
- Dedicated persistent storage for database, Redis, artifacts and resource cache; backups, access control, disk/inode monitoring and a retention policy.
- Provider executables, caches and datasets qualified for the intended workflow. A registry row alone does not make a provider executable or clinically validated.

## 3. Prepare lab-owned storage

Copy the template and create the directories configured in it:

```bash
cp .env.production.example .env
chmod 600 .env
sudo mkdir -p /srv/siraloom/postgres /srv/siraloom/redis \
  /srv/siraloom/artifacts /srv/siraloom/references /srv/siraloom/resource-cache
```

Edit `.env` before starting the stack. Set the actual absolute host paths in the `SIRALOOM_*_HOST_PATH` variables. These paths are bind-mounted into the API and worker containers; the reference path is read-only. Ensure the relevant container users can write to the database, Redis, artifact and resource-cache paths. Do not guess ownership IDs: inspect the exact container images and apply your lab's filesystem policy.

Copy the approved reference package into `/srv/siraloom/references`; set `REFERENCE_FASTA` and `REFERENCE_FAI` to the matching in-container paths. Do not silently replace a reference build or index after a case has been analyzed.

## 4. Configure identity, secrets and URLs

Set at minimum:

- `POSTGRES_PASSWORD` to a unique secret; URL-encode special characters if used in `DATABASE_URL`.
- `FIREBASE_ADMIN_CREDENTIALS_HOST_PATH` to the protected host path of the Firebase Admin service-account JSON. Compose mounts it as a read-only secret at `/run/secrets/firebase_admin_credentials`.
- `FIREBASE_PROJECT_ID` and `FIREBASE_AUTH_REQUIRED=true`.
- `FRONTEND_ORIGIN=https://lab.example.org` and `PUBLIC_BASE_URL=https://lab.example.org`.
- `NEXT_PUBLIC_SIRALOOM_API_BASE=https://lab.example.org/api/v1`.
- The public Firebase web configuration values. These are browser-visible configuration values, not server credentials.
- `NEXT_PUBLIC_SIRALOOM_DEPLOYMENT_MODE=lab` for a workspace-first installation.
- `GENEBE_ENABLED=false` unless a lab has explicitly approved and configured that research/development provider. Do not treat it as a clinically validated provider.

Never commit `.env`, Firebase Admin credentials, API tokens or real patient data.

## 5. Configure upload and resource limits

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

- Back up PostgreSQL consistently and test restore.
- Back up artifact and resource-cache directories with hashes/retention policy.
- Preserve the exact reference, provider versions, resource checksums, workflow versions and report artifacts needed to reproduce historical results.
- Upgrade frontend, API and worker as one versioned release; run migrations through the API/release step, then verify readiness before allowing new cases.
- Keep the previous deployment image and database/artifact backups until rollback is tested.
