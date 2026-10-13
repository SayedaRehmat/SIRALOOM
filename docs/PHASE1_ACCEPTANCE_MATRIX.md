# SIRALOOM Variant — Phase 1 Acceptance Matrix

| Requirement | Implementation | Automated evidence | Live validation | Qualification status |
|---|---|---|---|---|
| Valid VCF accepted | VCF parser + artifact ingestion | Backend tests | Required | BLOCKED |
| Invalid VCF rejected with actionable error | VCF validation + workflow failure state | Backend tests | Required | BLOCKED |
| Genome build explicit/verified | GRCh37/GRCh38 artifact metadata + normalization | Backend tests | Required | BLOCKED |
| Reference-aware normalization | Streaming normalizer | Backend tests | Required | BLOCKED |
| Canonical IDs created | Stable canonical key/UUID | Backend tests | Required | BLOCKED |
| Annotation through adapter | GeneBe adapter | Adapter/workflow tests | Required | BLOCKED |
| Provider source/version preserved | Annotation + audit provenance | Backend tests | Required | BLOCKED |
| Global population represented | Population observation model | Backend tests | Required | BLOCKED |
| Middle Eastern context represented when available | gnomAD MID adapter | Backend tests | Required | BLOCKED |
| Country resource can be added without core rewrite | Population provider architecture | Architecture/tests | Required for connector | BLOCKED |
| Missing population resource does not break analysis | Availability states | Backend tests | Required | BLOCKED |
| Missing ≠ zero | Population availability semantics | Backend tests | Required | BLOCKED |
| Evidence source/version preserved | Evidence model | Backend tests | Required | BLOCKED |
| ACMG criteria versioned | ACMG assessment/review history | Backend tests | Required | BLOCKED |
| Proposed vs reviewed classification separated | Review state machine | Backend tests | Required | BLOCKED |
| Reviewer edits create history | Versioned review/classification | Backend tests | Required | BLOCKED |
| Report versions immutable | Report version/supersession model | Backend tests | Required | BLOCKED |
| English report | Report renderer | Backend tests | Required | BLOCKED |
| Arabic report | RTL/localization foundation | Backend tests | Required | BLOCKED |
| Audit events generated | Audit service/hash chain | Backend tests | Required | BLOCKED |
| Provenance lineage generated | Artifact/workflow/resource lineage | Backend tests | Required | BLOCKED |
| SHA-256 artifact hashes | Artifact store | Backend tests | Required | BLOCKED |
| Full case package export | Export service | Backend tests | Required | BLOCKED |
| API contract tests | FastAPI/backend suite | CI | Required | BLOCKED |
| Security tests | Tenant/RBAC/auth tests | CI | Required | BLOCKED |
| Laboratory capacity preflight fails closed when not READY | PR #174 merged as `01ef71735f812d51acaabd059f9431e264544ccc`; lab analysis dispatch requires READY preflight; no disk reservation | PR CI run #1329: backend, PostgreSQL integration and frontend/Compose jobs passed | Verify against configured lab deployment and actual host mounts | BLOCKED |
| Durable stage retry + scientific-gap human review routing | [PR #176](https://github.com/SayedaRehmat/SIRALOOM/pull/176) merged as [`8d6da5b46df65adf69be77576812bd51611ab152`](https://github.com/SayedaRehmat/SIRALOOM/commit/8d6da5b46df65adf69be77576812bd51611ab152); report retry checkpoint, bounded gnomAD transient retries, missing population/evidence and ClinGen resource gaps routed to review, manual ACMG resume test | [PR CI #1361](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362003153): backend, PostgreSQL/Celery integration, frontend production build/container and Compose validation all passed | Still requires controlled deployed failure injection and full stage-body recovery evidence | BLOCKED |
| Laboratory Operations UI and source trace | PR #173 merged as `94d4625fc85e8803ce096fe802228dcfd682b0e2`; notifications, reanalysis candidates, storage/capacity telemetry, storage-profile registration, case deep-links and workflow section navigation | PR CI run #1332: backend, PostgreSQL integration and frontend/production Compose jobs passed on PR head `5368c502498f848f5efbcadb888c830bd3ef086a` | Test authenticated actions, persistence, permissions, language/RTL and production deployment | BLOCKED |
| End-to-end VCF → report | Workflow + UI | Integration tests | Required | NOT TESTED |
| Scientific benchmark validation | Validation corpus + expected outputs | Harness | Required | NOT TESTED |
| Live frontend/backend deployment | Vercel/public backend | CI/deployment | Required | NOT TESTED |

## Release-gate evidence snapshot (2026-10-13)

### Exact source and CI evidence
- **Current main revision:** [`41ffa557ed5b127ef060cb519c70cdf1ed811499`](https://github.com/SayedaRehmat/SIRALOOM/commit/41ffa557ed5b127ef060cb519c70cdf1ed811499), which includes the workspace resource-blocker routing fix from [PR #181](https://github.com/SayedaRehmat/SIRALOOM/pull/181).
- **Main CI for current revision:** [run #1377](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38371074637) passed on exact main SHA `41ffa557ed5b127ef060cb519c70cdf1ed811499`, including backend, PostgreSQL/Celery integration, frontend build/container and production Compose validation.
- **Previous main CI:** [run #1373](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370357644) passed on `25abfacb13045d6c0834f6d0acae42b81a039a63`, including the cancellation polling fix.
- **Cancellation polling fix:** [PR #180](https://github.com/SayedaRehmat/SIRALOOM/pull/180), merged as `25abfacb13045d6c0834f6d0acae42b81a039a63`; [PR CI #1371](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370113596) passed backend, PostgreSQL/Celery integration and frontend jobs.
- **Resource-blocker navigation fix:** [PR #181](https://github.com/SayedaRehmat/SIRALOOM/pull/181), merged as `41ffa557ed5b127ef060cb519c70cdf1ed811499`; [PR CI #1375](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370756686) passed backend, PostgreSQL/Celery integration and frontend jobs. This changes navigation, not resource qualification or authorization.
- **Actual annotation-stage recovery test:** [PR #179](https://github.com/SayedaRehmat/SIRALOOM/pull/179) exercises the real workflow body through the production Celery task wrapper with a deterministic provider double. [Run #1379](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38371397561) is queued at head `503ad39bef1f97811628dd1127d3c16de256a221`. Previous attempts exposed fixture defects and a flawed single-delivery assumption: a real worker loss requires a second broker-redelivered task invocation with the same task ID and `redelivered=true`. The test now models both deliveries and gates its stop boundary until after annotation persistence replay. Do not count it as release evidence until the durable annotation row, checkpoint and partition assertions pass. Even when green, this remains orchestration coverage, not a live provider or scientific truth-set benchmark.
- **Missing population handling:** [PR #178](https://github.com/SayedaRehmat/SIRALOOM/pull/178) is merged; [CI #1366](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38363977226) passed on main SHA `6cfc89b4f2b9abfae5b4908ff1cedac58ecdbc7e`. This controlled test confirms missing population is not represented as AF=0 and routes the analysis to review; it is not live gnomAD integration.
- **Recovery hardening:** [PR #176](https://github.com/SayedaRehmat/SIRALOOM/pull/176), merge `8d6da5b46df65adf69be77576812bd51611ab152`; [CI #1362](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362716115) passed backend, PostgreSQL/Celery integration and frontend/Compose validation.
- **Capacity safety:** [PR #174](https://github.com/SayedaRehmat/SIRALOOM/pull/174), merge `01ef71735f812d51acaabd059f9431e264544ccc`. Preflight remains a snapshot with `reservation_supported=false`; it does not reserve disk/capacity.
- **Operations UI/source trace:** [PR #173](https://github.com/SayedaRehmat/SIRALOOM/pull/173), merge `94d4625fc85e8803ce096fe802228dcfd682b0e2`. The source/CI evidence does not prove the production domain runs the current main revision.

### Open pull requests requiring explicit disposition
- [PR #179](https://github.com/SayedaRehmat/SIRALOOM/pull/179): keep open until the current recovery test passes without weakening assertions.
- [PR #169](https://github.com/SayedaRehmat/SIRALOOM/pull/169): not release evidence; ClinVar monthly archive discovery only, with publisher checksum and licensing gates still blocking generic staging/activation. Other publishers are not implemented by this PR.
- [PR #166](https://github.com/SayedaRehmat/SIRALOOM/pull/166): draft; preview readiness does not prove production deployment, and earlier Vercel deployment quota exhaustion prevented reliable production-revision confirmation.
- [PR #1](https://github.com/SayedaRehmat/SIRALOOM/pull/1), [PR #2](https://github.com/SayedaRehmat/SIRALOOM/pull/2), and [PR #10](https://github.com/SayedaRehmat/SIRALOOM/pull/10): closed as superseded after comparing their relevant changes with current main. Current main has the governed reference-package contract, `bcftools` normalization in `backend/app/workflows/variant.py`, durable next-step resolution in `backend/app/api/v1/analyses.py`, and current workspace recovery routing. Their closure does not pass the deployed-reference or end-to-end gates.

### Release blockers not satisfied by CI
- No captured authenticated production signup/email-verification/logout/session-expiry run or deployed cross-tenant denial evidence.
- No captured live deployed VCF → worker → population/evidence → human review → report/sign-out → provenance workflow with artifact hashes and deployment revision.
- Annotation stage-body recovery is pending PR #179; population/evidence/ACMG/review/report/provenance recovery has not been demonstrated end-to-end at every durable boundary.
- No pinned GIAB truth-set comparison artifact with TP/FP/FN, precision/recall or concordance, confident-region/scope declaration and excluded variant classes.
- The current Render blueprint is explicitly staging/free, sets `ARTIFACT_ROOT=/tmp/siraloom/artifacts`, disables Firebase Storage, and declares no persistent disk/reference mount. That configuration does not establish artifact/reference durability across restart or redeploy; qualify a durable storage target and restore before any lab trial. Source: [render.yaml](https://github.com/SayedaRehmat/SIRALOOM/blob/main/render.yaml).
- No production backup/restore proof, host-mounted reference/artifact storage evidence, health/readiness evidence or representative concurrency/load report for 10 labs × 5–6 users and the scale path toward 100 labs.
- No proof that current main is deployed to the production frontend/backend domains.

## Release rule

The GitHub repository may describe the software as a **Phase-1 release candidate** only while the rows marked BLOCKED/NOT TESTED remain explicitly disclosed. It may be described as a clinically validated diagnostic system only after separate laboratory validation, which is outside this software release gate. Keep the release gate open until the deployed end-to-end workflow, scientific benchmark, authorization/isolation, recovery, and deployment gates have evidence.