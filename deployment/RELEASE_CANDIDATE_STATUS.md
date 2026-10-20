# SIRALOOM Phase 1 Deployment Release Candidate

## Current germline VCF processing boundary (2026-10-20)

Follow-up implementation on `main` is commit `bd7b93c`; the release-gate evidence update is `b5a07ba`, and both were pushed successfully. Before BCFtools normalization, every input record in a mixed analysis is now checked against the selected reference FASTA, including preserved GVCF blocks, symbolic SVs, BND REF alleles and remote loci, and `*` records. A mismatch durably blocks normalization with a specific code while retaining source and routed artifacts with audit lineage. Focused production-wrapper and validation tests passed **33**; broad backend suite excluding the Windows-native PDF renderer passed **1,043, 40 skipped**. Local BCFtools 1.19 executable and PostgreSQL integration remain **NOT RUN** because this Windows environment has neither BCFtools/container runtime nor a configured database. The exact-SHA Actions result is **not verified**; the run could not be retrieved in this session. SV/GVCF records remain preserved for review and uninterpreted. Detailed evidence is in the [master engineering ledger](../docs/engineering/MASTER_AUDIT_AND_REMEDIATION.md#2026-10-20-preserved-vcf-records-validated-against-the-selected-reference).

The working tree now partitions records before reference lookup. Reference-aware BCFtools normalization is intended for sequence-resolved SNVs and small indels, including a GVCF concrete ALT only when complete sample genotypes establish that wildcard alleles are unseen. GVCF reference blocks, wildcard-called/unresolved variants, symbolic SVs, breakends, and spanning-deletion `*` records are retained as provenance-linked artifacts and require an appropriate review/processing stage. They are not interpreted by the current workflow, and final report sign-out is blocked while these records remain unreviewed. This is an explicit partial-processing boundary, not complete GVCF or SV support.

Production-wrapper regression evidence: focused local suite including the BCFtools golden module **44 passed, 14 skipped** because this Windows environment lacks BCFtools; the broad backend suite locally **986 passed, 40 skipped**, excluding the PDF-renderer test. Exact-SHA CI run [39395036911](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39395036911) for `300eae3` passed backend (**1,046 passed, 27 skipped**) with actual BCFtools 1.19, PostgreSQL integration (**26 passed**), frontend, Python compilation, startup scripts, backend Docker image build, and container version verification. Production-wrapper tests verify routed GVCF/SV record preservation, source linkage and file hashes. The BCFtools golden confirms GVCF wildcard trimming and allele-indexed field handling. GVCF reference blocks and unresolved GVCF/SV/spanning-deletion records remain preserved for review and are not clinically interpreted. Deployed tenant/storage checks, complete external-storage recovery, and independent scientific benchmarks remain unverified. No clinical validation or production-readiness claim is made.

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
