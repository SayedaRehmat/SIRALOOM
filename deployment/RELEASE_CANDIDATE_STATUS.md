# SIRALOOM Phase 1 Deployment Release Candidate

## Baseline

M15 is the frozen Phase-1 software baseline. Backend verification remains 113/113 tests passed.

## Completed hardening in this release candidate

- Frontend Node runtime pinned to Node 22.x.
- npm package manager pinned to npm 10.9.2.
- Frontend uses `npm ci` in CI/Vercel configuration.
- `frontend/.nvmrc` added.
- `frontend/.npmrc` enforces the Node engine and disables audit/fund noise in deployment installs.
- Vercel configuration added; Vercel project Root Directory must be `frontend`.
- Cloud Run API deployment template added.
- Cloud Run Worker Pool deployment template added.
- Worker Pool explicitly starts `/app/scripts/start_worker.sh`, preventing the backend image's default Uvicorn command from being used by the worker.
- Firebase Admin is configured to use Application Default Credentials on Google Cloud when `FIREBASE_CREDENTIALS_PATH` is unset.
- Production artifact storage is configured for Firebase/Google Cloud Storage rather than browser-direct access.
- Reference FASTA/FAI are externalized from GitHub and can be mounted read-only from Cloud Storage.
- GeneBe credentials are represented as Secret Manager references in deployment templates.

## One external build step remains

A real `frontend/package-lock.json` must be generated in an internet-connected Node/npm environment using:

```bash
cd frontend
npm install --package-lock-only --ignore-scripts --no-audit --no-fund
npm ci
npm run build
```

The sandbox used for this release review timed out while resolving npm dependencies, so a fake or hand-written lockfile is deliberately not included.

After the command succeeds, commit `frontend/package-lock.json`. From that point the repository's Vercel and CI installs are deterministic.

## Deployment architecture

- Frontend: Vercel, Root Directory `frontend`.
- API: Google Cloud Run service using `docker/backend.Dockerfile`.
- Worker: Google Cloud Run Worker Pool using the same backend image and `/app/scripts/start_worker.sh`.
- Database: Cloud SQL PostgreSQL.
- Queue: managed Redis reachable by both API and worker.
- Artifact storage: Firebase/Google Cloud Storage through the existing server-side adapter.
- References: validated GRCh37/GRCh38 FASTA/FAI in controlled Cloud Storage, mounted read-only where required.
- Identity: Firebase Authentication + Firebase Admin verification.
- Research annotation provider: GeneBe, only where its current terms permit the intended use.
- Population provider: gnomAD adapter.

Do not commit production secrets, service-account JSON files, database passwords, Redis credentials, or GeneBe keys.
