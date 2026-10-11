# Milestone 7 — Deployment + End-to-End Validation Foundation

Status: implemented and locally software-tested where the environment permits; live infrastructure validation remains deployment-specific.

## What M7 adds

- Separate liveness (`/api/v1/health`) and readiness (`/api/v1/ready`) probes.
- Readiness checks for PostgreSQL, Redis, artifact storage, and production Firebase configuration.
- API startup script that applies `alembic upgrade head` before serving traffic.
- Worker startup script that leaves schema migration ownership to the release/API step.
- Production environment template with explicit secret/configuration boundaries.
- Production Docker Compose profile for PostgreSQL, Redis, API, worker, durable artifacts, and read-only reference data.
- API container healthcheck.
- Deployment validation documentation and explicit non-claims around clinical validation.

## Required production release sequence

1. Provision PostgreSQL and Redis.
2. Provide `.env` from the production secret/configuration system; never commit it.
3. Mount a validated, indexed reference FASTA read-only at `/data/references`.
4. Configure Firebase Admin credentials outside the repository.
5. Build the backend image.
6. Start API/release migration step; verify `/api/v1/health` and `/api/v1/ready`.
7. Start workers only after the API is healthy and migrations have completed.

### Governed resource staging (lab deployments)

- Mount the persistent `resource_cache_data` volume into both API and worker containers at `/data/siraloom/resource-cache`, or configure `RESOURCE_CACHE_ROOT` to the lab's persistent resource store and mount that exact path in both containers.
- Set `RESOURCE_STAGING_ALLOWED_HOSTS` to a comma-separated allow-list of approved publisher hostnames. Leave it empty when remote acquisition is not approved; the API fails closed in that case.
- Set `RESOURCE_STAGING_LOCAL_SOURCE_ROOTS` to the lab-mounted read-only directories from which local resource files may be staged.
- Set `RESOURCE_STAGING_MAX_BYTES` and `RESOURCE_STAGING_TIMEOUT_SECONDS` to the lab-approved transfer limits.
- Generic remote staging supports public HTTPS files only, with a registered exact release URL, published SHA-256 and expected size. Authenticated or license-controlled resources require provider-specific adapters.
- Verify that a staging attempt records free bytes, required bytes, observed size and SHA-256; simulate worker interruption and retry before enabling resource acquisition in a production environment.
8. Deploy the Next.js frontend separately (for example Vercel) with the public API base URL and Firebase web configuration.
9. Run the M7 smoke/E2E validation against the deployed URL.
10. Perform concurrency, failure/recovery, provider, security and laboratory-specific validation before any clinical deployment claim.

## Safety boundaries

- `GENEBE_ENABLED` is false by default. GeneBe is a development/research provider and must not be represented as a validated clinical backend.
- Firebase credentials/API keys are not stored in source control.
- Readiness never returns secrets.
- Public benchmark testing demonstrates software behavior/reproducibility, not clinical assay validation or accreditation.

## Verification in the current environment

- Existing M0–M6 regression suite: 84/84 PASS before M7 changes.
- M7 Python test suite: see `tests/test_m7_deployment.py` and the final milestone report.
- Docker/real PostgreSQL/Redis/Firebase execution cannot be claimed unless those services are actually available in the execution environment.
- Frontend dependency installation/build remains environment-dependent when npm registry access or a lockfile is unavailable.
