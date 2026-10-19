# SIRALOOM Variant — Phase 1 Acceptance Matrix

> The evidence snapshot dated 2026-10-13 below is historical. The current evidence-backed release decision is in the 2026-10-19 snapshot at the end of this document.

| Requirement | Implementation | Automated evidence | Live validation | Qualification status |
|---|---|---|---|---|
| Valid VCF accepted | Strict VCFv4.2/v4.3 validation at artifact intake plus artifact ingestion | `tests/test_vcf_validation.py tests/test_ingestion.py`: 25 passed locally | Required | BLOCKED |
| VCF version scope | Strict validator accepts VCFv4.2 and VCFv4.3; VCFv4.4/v4.5 are not accepted | Unsupported-version behavior in strict validator; latest code CI not yet verified | Reconcile version support with lab inputs before qualification | PARTIAL |
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

## Current release-gate evidence snapshot — 2026-10-19

This snapshot supersedes the historical 2026-10-13 snapshot below for current source and CI state. The release gate in Issue [#171](https://github.com/SayedaRehmat/SIRALOOM/issues/171) remains **OPEN / BLOCKED** because the required deployed workflow, scientific benchmark, and laboratory deployment evidence have not been produced.

### Current main source and CI

- **Current code-bearing main checkpoint:** [`0eb61a49f2f2f0e115f56436cb5640e05350599e`](https://github.com/SayedaRehmat/SIRALOOM/commit/0eb61a49f2f2f0e115f56436cb5640e05350599e). The local strict-validation/intake suites passed 25 tests; CI status for this exact SHA is unverified because the unauthenticated Actions API is rate limited.
- **Previous configured-CI checkpoint:** [`9a81ac1111c28aa06ad220ef89a1bc267489216d`](https://github.com/SayedaRehmat/SIRALOOM/commit/9a81ac1111c28aa06ad220ef89a1bc267489216d), verified by [run #392269](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39226927997) across `backend`, `postgres-integration`, and `frontend`. It points Docker Compose and Render probes at `/api/v1/ready`; that endpoint returns HTTP 503 on failed required checks.
- **Readiness API code checkpoint:** [`0533276957a8e329a1df328bc2d14df128c1e48a`](https://github.com/SayedaRehmat/SIRALOOM/commit/0533276957a8e329a1df328bc2d14df128c1e48a), verified by run #392261.
- **Previous inheritance assessment code checkpoint:** [`75ccd44565ee6bc5e1f952644f8fed746dddc891`](https://github.com/SayedaRehmat/SIRALOOM/commit/75ccd44565ee6bc5e1f952644f8fed746dddc891), verified by run #392245. Its following ledger checkpoint `30421af87caefac93920ad6301c50bc823c1c419` passed run #392246.
- **Following ledger checkpoint:** [`30421af87caefac93920ad6301c50bc823c1c419`](https://github.com/SayedaRehmat/SIRALOOM/commit/30421af87caefac93920ad6301c50bc823c1c419). GitHub Actions [run #392246](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39224623844) passed all three jobs for that exact SHA. The code fix itself is covered by run #392245.
- The CI workflow applies migrations in its PostgreSQL integration job and validates production Compose/container configuration in the frontend job. These are CI checks only; they do not prove an actual laboratory deployment, durable host storage, backup restoration, Firebase identity flows, or a live two-tenant boundary.
- Local Python evidence at the code checkpoint: **984 passed, 36 skipped** across the backend suite excluding `tests/test_report_pdf.py`. The unfiltered run had one failure because the Windows host could not load WeasyPrint native `libgobject-2.0-0`. This is not a claim that PDF rendering passed locally; Linux CI passed its configured checks.

### Open pull requests and disposition

- **PR #184 — production readiness hardening:** [open, head `31fd423`](https://github.com/SayedaRehmat/SIRALOOM/pull/184), based on `e6e80ad`. Its CI [run #38385341613](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38385341613) passed on that PR head. The branch is stale relative to current main (184 main-only commits and 27 PR-only commits in the local comparison); its current tree would remove many later source and regression-test files. **Do not merge this branch as-is.** Its readiness HTTP status, strict VCF column cardinality, startup configuration, package pinning and persistent-mount changes require review and selective reconciliation after the earlier workflow/scientific gates; they are not verified in the current deployment.
- **PR #179 — annotation recovery:** [open, head `76d8b34`](https://github.com/SayedaRehmat/SIRALOOM/pull/179), based on `6cfc89b`. Its old backend check failed in [run #38378949929](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38378949929). The current main tree has a later production-workflow/Celery-wrapper recovery test at `tests/test_actual_annotation_stage_redelivery.py` and corresponding worker recovery changes; those current-main tests passed run #392245. **Disposition: the old PR head is superseded for code integration; no merge is required.** Its deterministic-provider test remains orchestration evidence, not a live provider or scientific benchmark.
- **PR #166 — laboratory UI/operations design:** [open, head `8a86c8a`](https://github.com/SayedaRehmat/SIRALOOM/pull/166), based on `3ae4c6f`. Its CI [run #38134595226](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38134595226) passed on the old head. The branch is stale relative to current main (199 main-only commits and 27 PR-only commits in the local comparison). Its capacity policy is present on current main; the remaining UI changes are not accepted as evidence for deployment or for the live workflow. **Do not merge the stale branch as-is; rebase and review only if that UI work remains a product requirement.**

### Required acceptance status

| Gate | Status | Evidence and remaining requirement |
|---|---|---|
| Exact main source and configured CI | **PARTIAL** for current code checkpoint `0eb61a4`; **PASS** for parent `9a81ac1` | The current VCF changes passed 25 focused local tests; exact-SHA CI is unverified. Parent run #392269 passed all configured jobs. PR #184 and #166 remain stale/open and need selective disposition. |
| Signup, email verification, recovery, login/logout and protected-page revisit against Firebase | **NOT RUN** | No configured Firebase test project/credentials and no authenticated live browser journey are recorded. |
| Two-laboratory API, membership, object and artifact isolation in deployment | **NOT RUN** | Requires two controlled lab identities and deployed API/storage configuration. Unit/API guards are not a deployed tenant test. |
| Complete deployed VCF-to-review-to-authorized-signout workflow | **NOT RUN** | No deployment revision, real provider response, artifact hashes, or authenticated end-to-end evidence recorded. |
| Failure/recovery on real PostgreSQL, Redis, workers and object storage | **PARTIAL** | CI includes PostgreSQL/Celery integration and current-main annotation-stage worker-redelivery coverage; real provider/storage, queue outage and complete reviewer/signout recovery remain unverified. |
| Independent scientific truth-set benchmark | **NOT RUN** | No pinned GIAB truth set, reference checksum, comparison command, or measured TP/FP/FN and precision/recall result recorded. |
| Production deployment, durable storage, health/readiness, backup/restore and rollback | **PARTIAL** | Readiness HTTP status semantics and Docker Compose/Render probe configuration passed CI #392269 on parent `9a81ac1`. There is no deployed host, measured capacity, backup/restore exercise, or live readiness evidence. PR #184 remains unreconciled. |
| Clinical validity, utility, accreditation or regulatory authorization | **NOT ESTABLISHED** | Outside what software CI or these engineering tests can demonstrate. |

**Release decision:** BLOCKED for a laboratory trial or clinical workflow pending the NOT RUN gates above. Automated CI supports a software development/research demonstration only; it does not establish clinical readiness or a production-qualified laboratory installation.

## Release-gate evidence snapshot (2026-10-13)

### Exact source and CI evidence
- **Current main revision:** [`41ffa557ed5b127ef060cb519c70cdf1ed811499`](https://github.com/SayedaRehmat/SIRALOOM/commit/41ffa557ed5b127ef060cb519c70cdf1ed811499), which includes the workspace resource-blocker routing fix from [PR #181](https://github.com/SayedaRehmat/SIRALOOM/pull/181).
- **Main CI for current revision:** [run #1377](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38371074637) passed on exact main SHA `41ffa557ed5b127ef060cb519c70cdf1ed811499`, including backend, PostgreSQL/Celery integration, frontend build/container and production Compose validation.
- **Previous main CI:** [run #1373](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370357644) passed on `25abfacb13045d6c0834f6d0acae42b81a039a63`, including the cancellation polling fix.
- **Cancellation polling fix:** [PR #180](https://github.com/SayedaRehmat/SIRALOOM/pull/180), merged as `25abfacb13045d6c0834f6d0acae42b81a039a63`; [PR CI #1371](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370113596) passed backend, PostgreSQL/Celery integration and frontend jobs.
- **Resource-blocker navigation fix:** [PR #181](https://github.com/SayedaRehmat/SIRALOOM/pull/181), merged as `41ffa557ed5b127ef060cb519c70cdf1ed811499`; [PR CI #1375](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38370756686) passed backend, PostgreSQL/Celery integration and frontend jobs. This changes navigation, not resource qualification or authorization.
- **Actual annotation-stage recovery test:** [PR #179](https://github.com/SayedaRehmat/SIRALOOM/pull/179) exercises the real workflow body through the production Celery task wrapper with a deterministic provider double. Latest [run #1387](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38372891651) failed at head `0fc881f2a9984a6406f554cf4b730b36ce73e374`: provider calls and annotation-persistence calls were both zero, while the observed state had `annotate=RUNNING` and later population/evidence/ACMG stages progressing to `REQUIRES_REVIEW`. The test has not reached its injected post-commit worker-loss boundary. Debug the real stage path and fixture before any merge; do not weaken assertions. Even when green, this remains orchestration coverage, not a live provider or scientific truth-set benchmark.
- **Missing population handling:** [PR #178](https://github.com/SayedaRehmat/SIRALOOM/pull/178) is merged; [CI #1366](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38363977226) passed on main SHA `6cfc89b4f2b9abfae5b4908ff1cedac58ecdbc7e`. This controlled test confirms missing population is not represented as AF=0 and routes the analysis to review; it is not live gnomAD integration.
- **Recovery hardening:** [PR #176](https://github.com/SayedaRehmat/SIRALOOM/pull/176), merge `8d6da5b46df65adf69be77576812bd51611ab152`; [CI #1362](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38362716115) passed backend, PostgreSQL/Celery integration and frontend/Compose validation.
- **Capacity safety:** [PR #174](https://github.com/SayedaRehmat/SIRALOOM/pull/174), merge `01ef71735f812d51acaabd059f9431e264544ccc`. Preflight remains a snapshot with `reservation_supported=false`; it does not reserve disk/capacity.
- **Operations UI/source trace:** [PR #173](https://github.com/SayedaRehmat/SIRALOOM/pull/173), merge `94d4625fc85e8803ce096fe802228dcfd682b0e2`. The source/CI evidence does not prove the production domain runs the current main revision.

### Open pull requests requiring explicit disposition
- [PR #179](https://github.com/SayedaRehmat/SIRALOOM/pull/179): OPEN but stale and explicitly excluded from current main. The production annotation recovery logic and expanded `tests/test_actual_annotation_stage_redelivery.py` are present on main in/after `3385b69`; exact-main CI #392288 passed that version. The PR head is based on `6cfc89b` and its backend check fails. Do not merge this stale branch; its current-main equivalent is already covered. The PR itself remains open for maintainer disposition.
- [PR #169](https://github.com/SayedaRehmat/SIRALOOM/pull/169): not release evidence; ClinVar monthly archive discovery only, with publisher checksum and licensing gates still blocking generic staging/activation. Other publishers are not implemented by this PR.
- [PR #166](https://github.com/SayedaRehmat/SIRALOOM/pull/166): draft; preview readiness does not prove production deployment, and earlier Vercel deployment quota exhaustion prevented reliable production-revision confirmation.
- [PR #1](https://github.com/SayedaRehmat/SIRALOOM/pull/1), [PR #2](https://github.com/SayedaRehmat/SIRALOOM/pull/2), and [PR #10](https://github.com/SayedaRehmat/SIRALOOM/pull/10): closed as superseded after comparing their relevant changes with current main. Current main has the governed reference-package contract, `bcftools` normalization in `backend/app/workflows/variant.py`, durable next-step resolution in `backend/app/api/v1/analyses.py`, and current workspace recovery routing. Their closure does not pass the deployed-reference or end-to-end gates.

### Release blockers not satisfied by CI
- No captured authenticated production signup/email-verification/logout/session-expiry run or deployed cross-tenant denial evidence.
- No captured live deployed VCF → worker → population/evidence → human review → report/sign-out → provenance workflow with artifact hashes and deployment revision.
- Current main contains deterministic annotation-stage worker-loss/redelivery recovery coverage (CI #392288 passed), but live-provider recovery and end-to-end real-storage recovery across population/evidence/ACMG/review/report/provenance remain NOT TESTED.
- No pinned GIAB truth-set comparison artifact with TP/FP/FN, precision/recall or concordance, confident-region/scope declaration and excluded variant classes.
- The current Render blueprint is explicitly staging/free, sets `ARTIFACT_ROOT=/tmp/siraloom/artifacts`, disables Firebase Storage, and declares no persistent disk/reference mount. That configuration does not establish artifact/reference durability across restart or redeploy; qualify a durable storage target and restore before any lab trial. Source: [render.yaml](https://github.com/SayedaRehmat/SIRALOOM/blob/main/render.yaml).
- No production backup/restore proof, host-mounted reference/artifact storage evidence, health/readiness evidence or representative concurrency/load report for 10 labs × 5–6 users and the scale path toward 100 labs.
- No proof that current main is deployed to the production frontend/backend domains.

## Release rule

The GitHub repository may describe the software as a **Phase-1 release candidate** only while the rows marked BLOCKED/NOT TESTED remain explicitly disclosed. It may be described as a clinically validated diagnostic system only after separate laboratory validation, which is outside this software release gate. Keep the release gate open until the deployed end-to-end workflow, scientific benchmark, authorization/isolation, recovery, and deployment gates have evidence.

## Current release-gate snapshot — 2026-10-19

> **Superseding checkpoint (2026-10-19):** latest code-bearing commit on `main` is [`4b494b2`](https://github.com/SayedaRehmat/SIRALOOM/commit/4b494b2). Full backend suite on that source passed 964 tests, with 39 PostgreSQL/bcftools-dependent skips; the Windows-native PDF renderer test was excluded. Exact-SHA CI for recent commits is not verified. Frontend tests/build evidence at `14e9afc` is recorded in the ledger. Phase A remains PARTIAL. See [the Phase A ledger](engineering/PHASE_A_AUDIT_LEDGER.md) for exact commands, limitations and remaining gates.

### Source and CI reconciliation

- **Current branch / exact SHA:** `main` at [`c71222b6511e52a2a6383d002dc5bbf03688d827`](https://github.com/SayedaRehmat/SIRALOOM/commit/c71222b6511e52a2a6383d002dc5bbf03688d827); local `main` and `origin/main` match. The only local untracked path is the preserved unrelated backup artifact.
- **Exact-SHA CI:** [run #392334](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39233424737) passed on ancestor `4ac43c3`. CI for current `c71222b` and later commits is not verified; the unauthenticated GitHub Actions API is rate limited. Invitation localization and backend-session behavior passed local frontend checks (**24 tests**); Firebase verifier regression code passed Python syntax compilation but pytest was unavailable locally.
- **Issue #171:** OPEN; its live/deployed workflow, scientific benchmark and deployment/restore requirements remain unsatisfied.
- **PR #179:** OPEN at head `76d8b3460bedcac5d38f01bbd3b81666ea9a29fa`, based on `6cfc89b4f2b9abfae5b4908ff1cedac58ecdbc7e`; current PR backend check fails. Its annotation recovery logic and test are superseded by the current main implementation/test already verified in run #392288. **Disposition: exclude the stale PR branch from this release candidate; do not merge it.** Leave closing the PR to the repository maintainer.

### Evidence status by release dimension

| Dimension | Status | Evidence / remaining requirement |
|---|---|---|
| API/backend/frontend regression CI | PARTIAL | Exact-SHA run #392334 passed on ancestor `4ac43c3`; current `c71222b` CI is unverified. This is software evidence only. |
| VCF intake and concurrent case readiness | PASS (automated scope) | Strict VCF validation tests passed locally; PostgreSQL concurrent valid/invalid VCF regression passed in run #392315. Supported VCF versions remain 4.2 and 4.3; newer versions are rejected. |
| Versioned confirmation and secondary-finding concurrency | PASS (automated scope) | Local focused tests: 6 passed, 2 PostgreSQL cases skipped locally; both PostgreSQL cases passed in run #392315. |
| Authentication/signup/verification/recovery/logout in a live browser | NOT TESTED | No configured Firebase/browser journey evidence. |
| Deployed two-lab API and artifact isolation | NOT TESTED | Requires deployed test tenants and verified storage permissions. |
| Reviewer-to-authorized-signout recovery with lab object storage | PARTIAL | Automated recovery tests cover storage failure rollback, retry, durable local artifact, integrity, approval audit, resume dispatch and idempotency; live laboratory object-storage/deployed recovery remains unverified. |
| Independent scientific truth-set benchmark | NOT TESTED | No versioned TP/FP/FN and concordance report is recorded. |
| Production deployment, backup restore and rollback | NOT TESTED | No controlled lab deployment/restore evidence is recorded. |
| Clinical validity, utility, accreditation or regulatory authorization | NOT ESTABLISHED | These are not established by code tests or CI. |

**Current decision: BLOCKED for laboratory trial or clinical workflow.** Phase A remains PARTIAL; Phases B and C remain incomplete. Use only with an explicit non-clinical development/demo description; do not represent the system as clinically validated or production-qualified.

## 2026-10-19 report sign-out integrity addendum

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Authorized sign-out distinguished from clinical validation | PASS (automated source/test scope) | Finalization now records `AUTHORIZED_SIGNOUT` and `clinical_use_status=LABORATORY_VALIDATION_REQUIRED`; rendered signed reports retain the lab-validation limitation. Focused report/sign-out suite: 35 passed; full backend suite excluding the Windows-native PDF renderer: 964 passed, 39 skipped. This does not establish laboratory validation or live report delivery. |

The change is in the working tree based on local/remote `main` at `9abb0a4`; its commit/push state is pending. It does not change the overall release decision: Phase A remains PARTIAL and controlled laboratory use remains blocked pending deployed and scientific evidence.
