# SIRALOOM Variant — Phase 1 Acceptance Matrix

| Requirement | Implementation | Automated evidence | Live validation | Status |
|---|---|---|---|---|
| Valid VCF accepted | VCF parser + artifact ingestion | Backend tests | Required | PARTIAL |
| Invalid VCF rejected with actionable error | VCF validation + workflow failure state | Backend tests | Required | PARTIAL |
| Genome build explicit/verified | GRCh37/GRCh38 artifact metadata + normalization | Backend tests | Required | PARTIAL |
| Reference-aware normalization | Streaming normalizer | Backend tests | Required | PARTIAL |
| Canonical IDs created | Stable canonical key/UUID | Backend tests | Required | PARTIAL |
| Annotation through adapter | GeneBe adapter | Adapter/workflow tests | Required | PARTIAL |
| Provider source/version preserved | Annotation + audit provenance | Backend tests | Required | PARTIAL |
| Global population represented | Population observation model | Backend tests | Required | PARTIAL |
| Middle Eastern context represented when available | gnomAD MID adapter | Backend tests | Required | PARTIAL |
| Country resource can be added without core rewrite | Population provider architecture | Architecture/tests | Required for connector | PARTIAL |
| Missing population resource does not break analysis | Availability states | Backend tests | Required | PARTIAL |
| Missing ≠ zero | Population availability semantics | Backend tests | Required | PARTIAL |
| Evidence source/version preserved | Evidence model | Backend tests | Required | PARTIAL |
| ACMG criteria versioned | ACMG assessment/review history | Backend tests | Required | PARTIAL |
| Proposed vs reviewed classification separated | Review state machine | Backend tests | Required | PARTIAL |
| Reviewer edits create history | Versioned review/classification | Backend tests | Required | PARTIAL |
| Report versions immutable | Report version/supersession model | Backend tests | Required | PARTIAL |
| English report | Report renderer | Backend tests | Required | PARTIAL |
| Arabic report | RTL/localization foundation | Backend tests | Required | PARTIAL |
| Audit events generated | Audit service/hash chain | Backend tests | Required | PARTIAL |
| Provenance lineage generated | Artifact/workflow/resource lineage | Backend tests | Required | PARTIAL |
| SHA-256 artifact hashes | Artifact store | Backend tests | Required | PARTIAL |
| Full case package export | Export service | Backend tests | Required | PARTIAL |
| API contract tests | FastAPI/backend suite | CI | Required | PARTIAL |
| Security tests | Tenant/RBAC/auth tests | CI | Required | PARTIAL |
| Laboratory capacity preflight fails closed when not READY | PR #174 merged as `01ef71735f812d51acaabd059f9431e264544ccc`; lab analysis dispatch requires READY preflight; no disk reservation | PR CI run #1329: backend, PostgreSQL integration and frontend/Compose jobs passed | Verify against configured lab deployment and actual host mounts | PARTIAL |
| Durable stage retry + scientific-gap human review routing | [PR #176](https://github.com/SayedaRehmat/SIRALOOM/pull/176) merged as [`8d6da5b46df65adf69be77576812bd51611ab152`](https://github.com/SayedaRehmat/SIRALOOM/commit/8d6da5b46df65adf69be77576812bd51611ab152); report retry checkpoint, bounded gnomAD transient retries, missing population/evidence and ClinGen resource gaps routed to review, manual ACMG resume test | [PR CI #1361](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362003153): backend, PostgreSQL/Celery integration, frontend production build/container and Compose validation all passed | Still requires controlled deployed failure injection and full stage-body recovery evidence | PARTIAL |
| Laboratory Operations UI and source trace | PR #173 merged as `94d4625fc85e8803ce096fe802228dcfd682b0e2`; notifications, reanalysis candidates, storage/capacity telemetry, storage-profile registration, case deep-links and workflow section navigation | PR CI run #1332: backend, PostgreSQL integration and frontend/production Compose jobs passed on PR head `5368c502498f848f5efbcadb888c830bd3ef086a` | Test authenticated actions, persistence, permissions, language/RTL and production deployment | PARTIAL |
| End-to-end VCF → report | Workflow + UI | Integration tests | Required | NOT VALIDATED |
| Scientific benchmark validation | Validation corpus + expected outputs | Harness | Required | NOT VALIDATED |
| Live frontend/backend deployment | Vercel/public backend | CI/deployment | Required | NOT VALIDATED |

## Release-gate evidence snapshot (2026-10-13)

- **Current main revision after recovery work:** [`8d6da5b46df65adf69be77576812bd51611ab152`](https://github.com/SayedaRehmat/SIRALOOM/commit/8d6da5b46df65adf69be77576812bd51611ab152), merged from [PR #176](https://github.com/SayedaRehmat/SIRALOOM/pull/176).
- **Recovery PR CI:** [run #1361](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362003153) passed backend tests, PostgreSQL/Celery worker-loss integration, frontend production build/container, and production Compose validation on the PR head. It is automated CI evidence, not a deployed clinical workflow run.
- **Post-merge main CI:** [run #1362](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362716115) was still in progress when this matrix edit began; its final result must be recorded after verification. Backend and PostgreSQL integration had passed; frontend production container build was still running at the last check.
- **Capacity safety change:** [PR #174](https://github.com/SayedaRehmat/SIRALOOM/pull/174), merge commit [`01ef71735f812d51acaabd059f9431e264544ccc`](https://github.com/SayedaRehmat/SIRALOOM/commit/01ef71735f812d51acaabd059f9431e264544ccc). Preflight remains a snapshot with `reservation_supported=false`; large-file support remains unqualified.
- **Operations UI/source trace:** [PR #173](https://github.com/SayedaRehmat/SIRALOOM/pull/173), merge commit [`94d4625fc85e8803ce096fe802228dcfd682b0e2`](https://github.com/SayedaRehmat/SIRALOOM/commit/94d4625fc85e8803ce096fe802228dcfd682b0e2); preview readiness does not prove the production domain runs the merged revision.
- **Resource-discovery PR explicitly held out:** [PR #169](https://github.com/SayedaRehmat/SIRALOOM/pull/169) is not release evidence. It covers ClinVar monthly archives only; gnomAD/other publishers are absent, and source-integrity/licensing review must be completed before staging or approval.
- **Still not evidenced:** controlled live authenticated VCF → worker → persisted evidence → human review → report/provenance; tenant-isolation verification; injected failure/re-execution for every scientific stage body; GIAB truth-set concordance metrics; production deployment health/storage/backup/restore evidence.

## Release rule

The GitHub repository may describe the software as a **Phase-1 release candidate** only while the rows marked PARTIAL/NOT VALIDATED remain explicitly disclosed. It may be described as a clinically validated diagnostic system only after separate laboratory validation, which is outside this software release gate. Keep the release gate open until the deployed end-to-end workflow, scientific benchmark, authorization/isolation, recovery, and deployment gates have evidence.