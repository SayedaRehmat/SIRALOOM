# SIRALOOM Render Deployment

## Architecture

Vercel
→ SIRALOOM FastAPI API on Render
→ PostgreSQL
→ Redis / Key Value
→ Celery worker
→ GeneBe
→ Ensembl REST reference sequence provider

## Render services

- siraloom-api
- siraloom-redis
- siraloom-db

## Development reference provider

GRCh38:
https://rest.ensembl.org

GRCh37:
https://grch37.rest.ensembl.org

The remote reference provider is intended for development and integration testing.

Production clinical deployments should use controlled, validated reference resources.

## Important

Render Free resources are for integration/testing.

Do not upload real patient/clinical data to this free deployment.

Firebase Cloud Storage is disabled in this integration configuration.

Artifacts use:

/tmp/siraloom/artifacts

These files are ephemeral.
