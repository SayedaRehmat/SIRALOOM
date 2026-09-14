# SIRALOOM Cloud Run deployment templates

These files are deployment templates only. Do not commit real credentials, database passwords, GeneBe keys, or Firebase service-account keys.

## API

Build the existing `docker/backend.Dockerfile` into Artifact Registry and deploy it as a Cloud Run service. The existing `scripts/start_api.sh` runs `alembic upgrade head` and then starts FastAPI on `$PORT`.

## Worker

Deploy the same backend image to a **Cloud Run Worker Pool**. The worker pool has no HTTP endpoint; it runs the existing `scripts/start_worker.sh` Celery consumer. Worker pools are designed for continuous background work. See the official documentation: https://docs.cloud.google.com/run/docs/deploy-worker-pools

## Identity

Use the Cloud Run service account with Application Default Credentials for Firebase Admin. Keep `FIREBASE_CREDENTIALS_PATH` unset in Google Cloud unless a deliberate secret-file configuration is required.

## Secrets

Store GeneBe credentials and database credentials in Secret Manager and inject them into the API and worker. Never put them in GitHub or these example files.

## References

Keep GRCh38/GRCh37 FASTA/FAI outside GitHub. Mount the validated reference bucket read-only at `/data/references` for the API/worker runtime where needed.

## Redis

The API and worker must resolve the same Redis endpoint. If using Memorystore, configure Cloud Run networking/egress to reach it.

## Important: worker command

The worker-pool template explicitly overrides the image's default Uvicorn command with `/app/scripts/start_worker.sh`. This is required because the same backend image is used for both the HTTP API and Celery worker.
