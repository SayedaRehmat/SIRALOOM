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

## Reproducible container inputs

Both the default 1.25 image and source-built profile images pin builder and runtime base images by immutable OCI digest. Runtime OS packages are resolved only from the fixed Debian Trixie snapshot `20261105T000000Z`. Snapshot CDN throttling is handled with five bounded retries and increasing, per-build-staggered backoff; failure after the retry budget fails the build closed. APT package signature verification remains enabled. The `uv` bootstrap binary is downloaded from the official Astral release and verified against its SHA-256 before installation, with Python/OpenSSL explicitly pointed at Debian's CA trust store. The application dependency set remains governed by the committed `uv.lock`. Do not replace these inputs with floating tags, current Debian mirrors, or unverified installer scripts.

## Registered profile set

| Profile | BCFtools | HTSlib | Queue | Current eligibility |
|---|---:|---:|---|---|
| Default | 1.25 | 1.25 | `bioinformatics.bcftools.1_25` | SOFTWARE_QUALIFIED |
| Source-qualified | 1.24.1 | 1.24.1 | `bioinformatics.bcftools.1_24_1` | SOFTWARE_QUALIFIED for Linux AMD64 |
| Source-qualified | 1.23.3 | 1.23.3 | `bioinformatics.bcftools.1_23_3` | SOFTWARE_QUALIFIED for Linux AMD64 |
| Source-qualified | 1.22.3 | 1.22.4 | `bioinformatics.bcftools.1_22_4` | SOFTWARE_QUALIFIED for Linux AMD64 |
| Blocked candidate | 1.21.3 | 1.21.3 | `bioinformatics.bcftools.1_21_3` | BLOCKED_COMPATIBILITY; VCF 4.5 FORMAT/LEN regression |
| Legacy | 1.19 | 1.19 | none | QUARANTINED_LEGACY; never production-selectable |

The three ARM64 counterparts are registered separately as non-production candidates:

| ARM64 candidate | BCFtools | HTSlib | Queue | Current eligibility |
|---|---:|---:|---|---|
| `bcftools-1.24.1-htslib-1.24.1-linux-aarch64-source` | 1.24.1 | 1.24.1 | `bioinformatics.bcftools.1_24_1.arm64` | CANDIDATE |
| `bcftools-1.23.3-htslib-1.23.3-linux-aarch64-source` | 1.23.3 | 1.23.3 | `bioinformatics.bcftools.1_23_3.arm64` | CANDIDATE |
| `bcftools-1.22.3-htslib-1.22.4-linux-aarch64-source` | 1.22.3 | 1.22.4 | `bioinformatics.bcftools.1_22_4.arm64` | CANDIDATE |

Each ARM64 profile has a distinct profile ID, platform-specific lock path and worker queue. The native ARM64 workflow resolves and qualifies these candidates independently; it never changes the x86_64 profile IDs, locks or statuses. Candidate status is deliberately not production-selectable. The image qualification job temporarily promotes only a disposable copy of the registry inside the local test image build; the committed registry remains CANDIDATE until the complete evidence is reviewed and explicitly promoted.

A profile is selectable only after its registry status is SOFTWARE_QUALIFIED. The three source-built profiles above have passed source, lock, VCF smoke, full backend, non-root runtime-image and profile-routing/reanalysis software checks on Linux AMD64. This does not establish clinical validation or compatibility with ARM64 and every possible lab host. The 1.21.3 profile remains blocked by its unresolved VCF 4.5 FORMAT/LEN regression. The 1.19 record is retained solely to make the legacy exclusion explicit. The 1.22.3/1.22.4 pair is intentional: the patched HTSlib release is 1.22.4 while the corresponding BCFtools release is 1.22.3.

## Supported build platform

The current locked build contract is Linux AMD64 (`linux-64`, CPU architecture `x86_64`). Both the default and source-built Dockerfiles fail closed on other architectures. ARM64 (`linux-aarch64`) is not currently qualified: it requires its own explicit package lock, source/runtime image build, VCF regression suite and worker-routing qualification before it can be enabled. Container images are not a substitute for checking host kernel, container runtime, storage permissions, memory/CPU limits, network policy and reference-resource availability during lab preflight.


## Optional production worker pools

The default API and 1.25 worker remain active for the default profile. After a candidate has passed source, lock, runtime-image, regression and cross-version routing qualification, the registry may be promoted to SOFTWARE_QUALIFIED and its dedicated worker pool can be enabled. Do not start a candidate pool against a production registry: the worker's settings validator correctly rejects candidate profiles.

Example for a qualified 1.24.1 profile:

```bash
docker compose -f docker-compose.production.yml --profile bcftools-1.24.1 up -d --build worker-bcftools-1-24-1
```

The corresponding optional profile names and services are:

- `bcftools-1.24.1` → `worker-bcftools-1-24-1`
- `bcftools-1.23.3` → `worker-bcftools-1-23-3`
- `bcftools-1.22.3` → `worker-bcftools-1-22-3`
- `bcftools-1.21.3` → `worker-bcftools-1-21-3`

Each service builds from `docker/backend-bcftools-source.Dockerfile`, uses its own explicit build lock, pins the exact BCFtools/HTSlib pair and consumes only its registered queue. Keep the default 1.25 pool running for default assignments.

## Adding another version

A new version is not enabled merely by adding a version string. Add a security-reviewed profile with a reproducible platform-specific lock, verify source archives against independently published SHA-256 values, build and inspect the runtime image, run the VCF normalization/indexing regression suite and the full backend suite, and then exercise analysis persistence, exact queue routing, wrong-worker rejection, retries, redelivery and reanalysis inheritance. Only after all required evidence is green may it be marked SOFTWARE_QUALIFIED. Never change an existing profile's lock or meaning after analyses have recorded its fingerprint.
