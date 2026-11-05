# Analysis-pinned BCFtools worker pools

## Contract

Each Analysis row stores an immutable native-toolchain assignment:

- toolchain_profile_id: registry identity for the exact BCFtools/HTSlib pair.
- toolchain_bcftools_version and toolchain_htslib_version: expected executable/library versions.
- toolchain_queue: dedicated Celery queue selected from the registered profile.
- toolchain_snapshot: platform, lock path, SHA-256 of the explicit lock, versions, queue and qualification scope.

The assignment is created with the analysis and cannot be edited afterward. Reanalysis children inherit the parent's assignment. The terminal provenance artifact and case export manifest carry the same snapshot.

## Dispatch and worker enforcement

1. The API accepts optional toolchain_profile_id on POST /api/v1/cases/{case_id}/analyses. If omitted, it pins the deployment's configured default profile.
2. The API refuses unknown, candidate, security-unreviewed or lock-incomplete profiles.
3. The durable analysis outbox publishes to the analysis row's toolchain_queue.
4. A worker verifies the analysis profile ID and exact BCFtools/HTSlib pair against its own process settings before acquiring the execution fence.
5. The worker also verifies that the persisted queue and lock fingerprint still match the registered profile. A mismatch fails closed; no VCF stage is started.

The standard 1.25 pool consumes the shared celery queue and bioinformatics.bcftools.1_25. A secondary native-toolchain pool consumes only its own profile queue; it does not steal general background tasks.

## 1.24.1 candidate deployment

The 1.24.1 profile remains CANDIDATE until its isolated runtime image passes CI. Do not enable it in a production deployment before that status is changed by the completed qualification process.

After qualification, build and start the optional worker pool:

```bash
docker compose -f docker-compose.production.yml --profile bcftools-1.24.1 up -d --build worker-bcftools-1-24-1
```

The service pins the 1.24.1 profile ID and version pair in its environment and consumes only bioinformatics.bcftools.1_24_1. Keep the default 1.25 worker running for the shared queue and analyses assigned to 1.25.

## Adding another version

A new version is not enabled merely by adding a version string. Add a security-reviewed profile with a reproducible platform-specific lock, verify the actual runtime image and plugins, run the VCF normalization/indexing regression suite and the full backend suite, and only then mark it SOFTWARE_QUALIFIED. Add a separate worker image and queue. Never change an existing profile's lock or meaning after analyses have recorded its fingerprint.
