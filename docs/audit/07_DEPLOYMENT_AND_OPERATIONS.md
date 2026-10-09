# Deployment and operations readiness plan

## Deployment profiles

### Hosted research trial

Use isolated demo/test data; Firebase Authentication; PostgreSQL; Redis; separate API, worker and single Beat scheduler; governed resource configuration; private secrets; tenant quotas; explicit trial data retention and deletion; ingress and application upload limits. Do not process patient-identifiable data until data protection, contracts, access controls and intended-use boundaries have been approved.

### Laboratory-controlled deployment

Support a laboratory-managed container/runtime, database, queue, object/file storage, reference packages and resource releases. Document outbound network needs, offline behavior, licensed resources, CPU/RAM/disk/concurrency sizing, TLS, certificate rotation, secrets ownership, backup/restore and upgrade/rollback. Air-gapped operation must be described as unsupported unless all required dependencies are tested offline.

## Required production controls

- Immutable image or commit identity for API, frontend, worker and Beat.
- Pinned dependencies and scientific executable/resource packages.
- Migration preflight and rollback/recovery plan.
- TLS and secure cookie/token handling.
- Runtime secret management and rotation.
- Ingress body limits consistent with API limit and temp-disk capacity.
- Separate persistent artifact/reference storage from ephemeral container filesystems.
- Storage checksum verification and retention/deletion rules.
- Health/readiness checks for database, broker, worker and resource availability.
- Structured logs with correlation IDs and no genomic payloads or unnecessary identifiers.
- Alerts for task age, queue depth, retry exhaustion, stale RUNNING state, storage pressure, provider errors, failed backups and failed restore drills.
- Backup encryption, retention, restore testing, and declared recovery point/time objectives.
- Incident response, access revocation, customer notification and support-bundle redaction.
- Deployment smoke tests and a controlled rollback procedure.

## Capacity and upload policy

A configurable application file-size ceiling is present in current deployment documentation; trial entitlements specify a lower 50 MiB VCF limit. The application-level limit does not alone prevent temporary-disk exhaustion because multipart parsing may spool bytes before endpoint-level checks. Coordinate ingress/proxy limits, ASGI temporary storage, persistent disk, concurrent uploads, tenant quota and worker disk use. Do not configure an unlimited upload ceiling without measured capacity controls.

## Live deployment acceptance checklist

- Verify actual production/preview URL, revision and health endpoints.
- Confirm API/database/broker/worker/Beat are healthy and compatible.
- Confirm authentication is required in production and test organization isolation.
- Upload a public benchmark VCF; verify checksum, record count, build and validation outcome.
- Run through all persisted workflow stages and verify provider/resource provenance.
- Exercise missing-resource, provider outage, worker-loss and storage-corruption paths.
- Generate and download report/provenance export under authorized roles.
- Confirm deletion/retention, backup and restore procedures.
- Capture evidence and have the release owner approve the exact revision.

The repository documentation describes a Vercel + container API + PostgreSQL + Redis/Celery topology. This audit has not verified live deployment settings or executed this checklist.
