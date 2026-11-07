# Tool-neutral API and scheduler image boundary

**Status:** implementation proposal in PR; not merged or deployment-qualified.  
**Dependency:** durable artifact validation in PR #297.  
**Scope:** Linux AMD64 container image separation only.

## Decision

The API and Celery Beat scheduler use `docker/backend-api.Dockerfile`. The default scientific worker continues to use `docker/backend.Dockerfile`, and alternate BCFtools workers continue to use `docker/backend-bcftools-source.Dockerfile`.

The API image contains the Python application, locked Python dependencies, migrations, configuration contracts and startup scripts. It does not install, copy or expose BCFtools, VEP, Samtools or other scientific executables. CI asserts that BCFtools is not on the API image PATH and tests the image as the unprivileged UID/GID 10001.

The worker image remains responsible for scientific executable execution. This preserves the existing immutable BCFtools/HTSlib profile and queue fence.

## Why this boundary is safe only after durable intake validation

Before PR #297, the upload HTTP handler synchronously invoked BCFtools for VCF structural validation and uploaded-index concordance. Removing BCFtools from the API image before moving both operations would break intake.

PR #297 changes intake to persist the artifact and a durable validation-dispatch intent, then validate the persisted artifact in a worker. The API no longer calls `validate_vcf` or `validate_index` in the upload path. The worker-side validator verifies persisted bytes and their digest/size before scientific validation.

This PR is intentionally based on the PR #297 branch. It must not be merged ahead of PR #297. If PR #297 is changed or does not merge, re-evaluate this dependency before merging this image-boundary change.

## Service mapping

| Service | Image | Scientific executable responsibility |
|---|---|---|
| API | `docker/backend-api.Dockerfile` | None; HTTP, authorization, persistence and dispatch |
| Celery Beat | `docker/backend-api.Dockerfile` | None; schedules durable relays/recovery |
| Default worker | `docker/backend.Dockerfile` | BCFtools 1.25 profile |
| Alternate BCFtools workers | `docker/backend-bcftools-source.Dockerfile` | Exact source-built profile and queue |

Both development and production Compose files encode this mapping. The API and Beat no longer receive BCFtools build arguments. The worker build contract is unchanged.

## Configuration compatibility

The shared Python settings currently retain BCFtools profile fields because application configuration and task registration are not yet fully separated by process role. These fields identify/validate the configured worker profile; they do not install or provide a BCFtools executable in the API image.

This is an intermediate compatibility boundary, not the final universal tool registry. A later change should make process roles explicit and move scientific tool configuration into worker-owned execution profiles without allowing API settings to choose or execute arbitrary binaries.

## Qualification in CI

The backend CI job:

1. Builds the API image independently.
2. Verifies API runs as UID/GID 10001.
3. Verifies required data directories are writable.
4. Verifies BCFtools, VEP, Samtools and GATK are absent from the API image.
5. Builds the BCFtools worker image and verifies its exact BCFtools/HTSlib pair.
6. Runs deployment tests that assert Compose service-to-image mapping.

The frontend CI job validates the production Compose file and asserts that API/Beat use the tool-neutral Dockerfile while the default worker uses the scientific worker Dockerfile.

## Explicit limitations

This change does **not** implement:

- A remote laboratory execution agent or outbound authenticated agent protocol.
- Kubernetes, Slurm/HPC, Windows or ARM64 deployment.
- A universal tool registry or workflow compatibility resolver.
- Automatic environment construction, signing or SBOM attestation.
- A separate API-only Python dependency lock.
- Clinical or workflow qualification.

It establishes one necessary service boundary without claiming the broader independent-laboratory execution architecture is complete.
