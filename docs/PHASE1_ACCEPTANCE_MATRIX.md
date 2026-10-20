# SIRALOOM Variant — Phase 1 Acceptance Matrix

> The evidence snapshot dated 2026-10-13 below is historical. The current evidence-backed release decision is in the 2026-10-20 snapshot near the end of this document.

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

## Earlier release-gate evidence snapshot — 2026-10-19 (superseded)

This snapshot records the source state at `0eb61a4` and is retained as history. The later snapshot titled “Current release-gate snapshot” near the end of this document supersedes it. Issue [#171](https://github.com/SayedaRehmat/SIRALOOM/issues/171) remains **OPEN / BLOCKED** because deployed workflow, scientific benchmark, and laboratory deployment evidence have not been produced.

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
| Independent scientific truth-set benchmark | **NOT RUN** | The manifest remains unconfigured; truth assets, confidence BED, approved laboratory acceptance policy and hap.py execution are unavailable. Exact-SHA run [#39421274780](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39421274780) passed at `185f3c2`: backend (**1,107 passed, 28 skipped**), PostgreSQL integration and frontend; CI asserted BCFtools 1.19 and exercised benchmark sample selection and production normalization lineage. Query biological identity as HG001 still requires lab attestation. No GIAB comparison or concordance metrics are claimed. |
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

## Historical exact-CI baseline — 2026-10-20

> **Historical source and exact CI evidence:** at this checkpoint, `main` was at [`e732841`](https://github.com/SayedaRehmat/SIRALOOM/commit/e73284193cda4d1e5a7a847d5ec0ccb007d76612), a ledger/matrix documentation commit. Application and regression-test code at [`300eae3`](https://github.com/SayedaRehmat/SIRALOOM/commit/300eae382d780fb8fda8062a7eb5b31aa3935af6) passed exact-SHA [GitHub Actions run 39395036911](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39395036911): backend **1,046 passed, 27 skipped**, PostgreSQL integration **26 passed**, frontend passed, startup-script validation and Python compilation passed, the laboratory backend Docker image built, and its runtime BCFtools version assertion passed for **1.19**. The run exercised the actual pinned BCFtools 1.19 golden test for gVCF wildcard trimming and allele-indexed fields. This does not verify subsequent main commits.

### Evidence status by release dimension

| Capability | Status | Evidence and remaining limitation |
|---|---|---|
| Backend, frontend, PostgreSQL integration CI | **PASS (automated scope)** | Exact-SHA run [39395036911](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39395036911) on `300eae3`: backend 1,046 passed/27 skipped; PostgreSQL integration 26 passed; frontend, startup scripts, Python compile, backend image build and container BCFtools 1.19 assertion succeeded. |
| Sequence-resolved SNV/small-indel normalization | **PASS (automated scope)** | Pinned BCFtools 1.19 synthetic goldens verify reference check, left alignment, multiallelic split and preserved MNV behavior. This is not an independent truth-set benchmark or broad clinical validation. |
| Concrete GVCF variant with uncalled wildcard | **PASS (automated scope)** | The production wrapper routes the variant to normalization only when every sample genotype is complete and does not use the wildcard. Actual BCFtools 1.19 golden verifies resulting ALT, INFO/AF, GT, AD and PL fields. |
| GVCF reference blocks and wildcard-called/unresolved variants | **PARTIAL** | Input records are preserved in provenance-linked review artifacts and never treated as variants. No GVCF reference-confidence interpretation or block-aware downstream analysis is implemented. |
| Symbolic SVs, breakends and spanning-deletion `*` | **PARTIAL** | Valid records are validated, preserved byte-for-text in separate artifacts with source/output hashes, counts and `NOT_ANALYZED` status. They enter `REQUIRES_REVIEW`; report sign-out remains blocked until interpretation. No SV/CNV/breakend downstream interpretation is implemented. |
| Malformed structural records and reference mismatch | **PASS (automated scope)** | Regression tests assert precise malformed-SV rejection and fail-closed reference-mismatch state while preserving source/routed artifacts. The positive reference-aware output is exercised with BCFtools in CI. |
| VCF routing provenance and artifact persistence | **PASS (automated scope)** | Production-wrapper SQLite tests verify unchanged source records, exact routed record lines, record counts, source lineage, `NOT_ANALYZED`, and SHA-256 consistency for persisted artifacts. This does not establish durability of a deployed laboratory object store. |
| Authentication, signup/recovery/logout in a real browser | **NOT RUN** | Unit/API coverage exists; no configured Firebase project and authenticated live identity journey evidence are recorded. |
| Tenant isolation in deployed APIs, jobs, and artifact storage | **NOT RUN** | Automated authorization checks do not substitute for deployed two-laboratory API and object-store boundary verification. |
| Reviewer-to-authorized-signout complete workflow | **PARTIAL** | Local/CI review, report-version fencing and sign-out tests exist. Full deployed review through signed report, with laboratory object storage and injected recovery failures, is not demonstrated. |
| Worker recovery and PostgreSQL behavior | **PARTIAL** | PostgreSQL integration passed 26 tests in CI; this does not prove every provider/storage/report stage's loss and retry behavior in a deployed lab environment. |
| Scientific truth-set concordance | **NOT RUN** | No pinned GIAB truth set and benchmark configuration with measured TP/FP/FN and precision/recall is recorded. Synthetic normalization goldens are not truth-set validation. |
| Laboratory deployment, backup/restore and rollback | **PARTIAL** | Backend image builds reproducibly in CI with pinned BCFtools 1.19. No controlled laboratory deployment, external durable-storage restart, backup restore, capacity measurements, or rollback exercise is evidenced. |
| Clinical validity, clinical utility, accreditation or regulatory authorization | **NOT ESTABLISHED** | These require separate laboratory evidence and authorization; CI and software workflow tests cannot establish them. |

**Release decision: BLOCKED for laboratory trial or clinical workflow.** The scoped sequence-variant preprocessing and safe GVCF/SV routing boundary have automated and exact-CI evidence, but Phase A is **PARTIAL**, Phases B/C remain incomplete, and the product must not be represented as clinically validated or production-qualified. Issue [#171](https://github.com/SayedaRehmat/SIRALOOM/issues/171) remains open. Open PR #179 is not evidence for current main; current-main recovery tests are separate from its stale PR head.

## 2026-10-19 report sign-out integrity addendum

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Authorized sign-out distinguished from clinical validation | PASS (automated source/test scope) | Finalization now records `AUTHORIZED_SIGNOUT` and `clinical_use_status=LABORATORY_VALIDATION_REQUIRED`; rendered signed reports retain the lab-validation limitation. Focused report/sign-out suite: 35 passed; full backend suite excluding the Windows-native PDF renderer: 964 passed, 39 skipped. This does not establish laboratory validation or live report delivery. |

The change is committed and pushed on local/remote `main` at [`c68e0f2`](https://github.com/SayedaRehmat/SIRALOOM/commit/c68e0f24325f950a9f13e5f1a778fee8eb0d055a). Exact-SHA CI is unverified. It does not change the overall release decision: Phase A remains PARTIAL and controlled laboratory use remains blocked pending deployed and scientific evidence.

## 2026-10-19 unsupported VCF scope routing addendum

| Requirement | Status | Evidence / limitation |
|---|---|---|
| GVCF and symbolic SV inputs explicitly blocked with durable provenance | PASS (automated workflow scope) | Commit [`07fffb9`](https://github.com/SayedaRehmat/SIRALOOM/commit/07fffb972a7c07a068f097dc818c6394f42b288c) plus a test-only follow-up invokes `run_variant_analysis` against SQLite for GVCF `<NON_REF>`, symbolic `<DEL>`, breakend, and `*` records, asserting `BLOCKED`, typed codes, next-step/profile metadata, audit record, and no reference lookup. Focused worker/VCF/intake tests: 29 passed; full backend suite: 968 passed, 39 skipped, excluding the Windows-native PDF renderer. This verifies safe rejection only, not SV/GVCF analysis support. |

This code is on local and remote `main`; exact-SHA CI and all live/deployed, independent scientific benchmark, and laboratory storage/restore gates remain unverified. Overall release status remains BLOCKED for laboratory use; Phase A remains PARTIAL.

## 2026-10-20 case-assigned notification and resource-change authorization addendum

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Case-scoped reanalysis notifications honor assignment grants and admin bypass | PASS (local automated scope) | Reanalysis and case-change producers use active case-read grants plus current admin roles; inbox omits stale notifications after access revocation. Focused regression: 15 + 8 tests passed. This is not deployed two-tenant evidence. |
| Resource-change event registration is role- and resource-governed and audited | PASS (local automated scope) | Case-writer role denial, tenant/kind/name validation, aggregate-only response, authenticated human audit, and audit-failure rollback are covered; combined workflow/API/resource-adoption regressions: 24 passed. PostgreSQL/deployed workflow remains unverified. |
| Broad backend regression after this change | PASS (local automated scope) | `pytest -q --ignore=tests/test_report_pdf.py`: 1,047 passed, 40 skipped, one deprecation warning. PDF renderer excluded for unavailable Windows-native WeasyPrint libraries; PostgreSQL and BCFtools dependent tests skipped where services/executable are unavailable. |

At this checkpoint these changes are committed locally on `main` as `baff5ff`, based on `86008358caae94898ceaedf3be9449e55e9936b6`; remote-push status must be verified separately. Phase A remains PARTIAL and the laboratory release decision remains BLOCKED.

## 2026-10-20 case assignment role/grant alignment addendum

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Case write/review grants agree with the current member role | PASS (local automated scope) | Assignment API rejects incompatible capabilities; case creator's review grant is role-aware. Follow-up migration clears role-incompatible legacy flags while preserving effective access. Focused migration/case-access/membership suite: 20 passed; broad backend suite: 1,050 passed, 40 skipped. PostgreSQL migration execution and deployed identity/tenant tests remain NOT RUN. |

Phase A remains PARTIAL; live Firebase journeys, deployed two-lab isolation, real-storage reviewer/sign-out recovery, scientific benchmark, and deployment/restore remain unverified. The migration is pushed as `3e95248de7370173eb2290c75dd3c63067761979`; local and remote `main` were verified equal at ledger commit `3c1b1acf3e82bf064660247fd9d74927cee2e33b`.

## 2026-10-19 ACMG engine status gate (local checkpoint)

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Non-proposed ACMG criteria cannot contribute to a classification | PASS (automated scope) | `ACMGEngine.validate_assessments` now accepts only `PROPOSED`; regression cases cover `NOT_MET`, `REJECTED`, `REQUIRES_REVIEW`, and `NOT_APPLICABLE`. Python compilation, `git diff --check`, and five isolated runtime assertions passed. Exact-SHA CI run #392456 passed backend, PostgreSQL integration, and frontend jobs for `e416a4e`. |
| Manual ACMG decision audit identifies the authenticated reviewer | PASS (automated scope) | The manual assessment route records the authenticated principal as `HUMAN`; `tests/test_acmg_audit_actor.py` passed in exact-SHA CI run #392460, along with backend, PostgreSQL/Celery integration, and frontend jobs for `b30d6c0`. Local pytest was unavailable, so this is CI evidence. |
| Draft report generation audit identifies the requesting user | PASS (automated scope) | The production route records the authenticated principal as the human actor; the report artifact compensation regression passed the backend job in exact-SHA CI run #392465 for `3f85ce0`. PostgreSQL integration also passed; frontend was in progress at ledger update. |
| Report supersession audit identifies the authorized signer | PASS (local automated scope; CI pending) | Production finalization now records the same human approver for `REPORT_SUPERSEDED` and `REPORT_APPROVED`. The two-version production finalization regression and report/sign-out suite passed: 23 tests. This does not verify live storage recovery. |
| ACMG automatic assessment and its audit event persist atomically | PASS (automated scope) | Production-route SQLite failure injection verifies assessment and classification rows are rolled back if audit persistence fails. Focused ACMG and authorization suite: 60 passed. Exact-SHA CI run [#39247884133](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39247884133) passed backend, PostgreSQL integration, and frontend for `eaab71d`. Local full backend suite: 1,020 passed, 39 skipped, and one unrelated Windows WeasyPrint native-library failure (`libgobject-2.0-0`). |

These changes protect interpretation status handling and reviewer audit attribution; they do not prove evidence assignment or clinical validity. Phase A remains PARTIAL and the laboratory deployment release gate remains BLOCKED.

## 2026-10-20 role-demotion capability revocation

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Role changes cannot leave latent case write/review grants that reactivate after promotion | PASS (local automated scope) | Membership mutation clears role-incompatible capabilities only for cases in the member's tenant, preserves read access, and audits the aggregate revocation. Regression verifies foreign-tenant grants are untouched and later promotion does not restore permissions. Focused suite: 17 passed; full backend suite excluding Windows-native PDF renderer: 1,006 passed, 40 skipped. PostgreSQL and deployed tenant verification remain NOT RUN. |

Phase A remains PARTIAL; live Firebase/browser journeys, deployed two-lab API/artifact isolation, real-storage reviewer/sign-out recovery, independent scientific benchmark, and deployment/restore remain unverified.

## 2026-10-20 VCF reference-declaration consistency

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Contradictory recognized VCF assembly declarations fail intake | PASS (local automated scope) | Ingestion checks `##reference` and `##contig` assembly tags, rejects conflicts, and preserves explicit user build selection. Focused tests: 47 passed; full backend excluding Windows-native PDF renderer: 1,011 passed, 40 skipped. Header metadata is self-reported and optional; actual reference identity still depends on the selected, integrity-checked package and REF validation. |

Source: [HTS VCF v4.5 specification](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex), read 2026-10-20; reference/contig metadata is recommended but optional, and metadata lines may occur in any order. Implementation commit `92057a89511bb770e74a09de54af8fe689f412ed` is pushed to `main`; exact-SHA CI is unverified. Phase A remains PARTIAL.

## 2026-10-20 VCF header framing conformance

| Requirement | Status | Evidence / limitation |
|---|---|---|
| VCFv4.2/v4.3 fileformat header is first; UTF-8 BOM is rejected | PASS (local automated scope) | Strict validator and shared record parser reject misplaced fileformat and BOM for plain/gzip files. Focused VCF suite: 58 passed, 5 skipped; full backend suite excluding Windows-native PDF renderer: 1,017 passed, 40 skipped. Exact-SHA CI and BCFtools executable cases remain unverified locally. |

Sources: official [HTS VCF v4.2](https://github.com/samtools/hts-specs/blob/master/VCFv4.2.tex) and [v4.3](https://github.com/samtools/hts-specs/blob/master/VCFv4.3.tex) specifications, read 2026-10-20. The fileformat line must be first; v4.3 forbids a BOM. Implementation commit `76eb5fabb9a32098a190b206364dfac368d8ba00` is pushed to `main`; exact-SHA CI is unverified. Phase A remains PARTIAL.

## 2026-10-20 declared INFO/FORMAT cardinality

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Declared INFO/FORMAT types and A/R/G/fixed cardinalities preserve allele/sample correspondence | PASS (local automated scope) | Validator checks Integer/Float/Character payload syntax and Number=A/R against ALT count, Number=R against REF+ALT count, FORMAT Number=G against per-sample GT ploidy, and fixed counts; duplicate INFO keys are rejected. Regression suite: 73 passed, 5 skipped; broad backend suite: 1,032 passed, 40 skipped with native PDF renderer excluded. INFO/Number=G remains unverifiable without a sample-specific ploidy and produces an explicit intake warning. Exact-SHA CI is not verified; BCFtools/PostgreSQL and deployed laboratory validation remain outstanding. |

Source: official [HTS VCF v4.3 specification](https://github.com/samtools/hts-specs/blob/master/VCFv4.3.tex), read 2026-10-20. Implementation and tests are pushed to `main` as [`e0858aa`](https://github.com/SayedaRehmat/SIRALOOM/commit/e0858aa9ad719b6b34214c5c932a5b1e3886c32b); exact-SHA CI is unverified because `gh` is unavailable. Phase A remains PARTIAL.

## 2026-10-20 pinned BCFtools 1.19 GVCF/SV routing boundary

| Representation / behavior | Status | Evidence and limitation |
|---|---|---|
| GVCF reference blocks (`<NON_REF>` only with `END`) | PARTIAL | Validated and preserved in a hash-verified `GVCF_REFERENCE_BLOCKS` artifact; they are not sent through ordinary variant normalization and require a future GVCF-aware review/analysis stage. |
| Concrete GVCF variant with uncalled wildcard allele | PARTIAL | Router admits only complete sample genotypes that do not call `<NON_REF>`/`<*>`; production-worker regression runs actual BCFtools when available and checks normalized GT/AD/PL and persisted artifact lineage. Local test used a mock because the binary is absent; pinned BCFtools golden cases are skipped and exact-SHA CI is unverified. |
| Symbolic SV `<DEL>` with valid `END` | PARTIAL | Source REF/span validation is performed and the exact record is persisted for review. BCFtools 1.19 has limited symbolic normalization behavior; SIRALOOM has no downstream SV interpretation, so report sign-out remains gated. |
| Reciprocal breakends | PARTIAL | Mate IDs and remote coordinates are validated; original records are preserved for review. No downstream breakend analysis is implemented. |
| Spanning-deletion `*` | PARTIAL | Accepted only when an overlapping deletion and compatible carrier context exist; record is preserved for review and not analyzed downstream. |
| Malformed symbolic span / reference mismatch | PASS (automated rejection scope) | Worker tests assert typed validation/reference errors and audit lineage. Malformed symbolic input is rejected before routing (source retained); selected-reference mismatch occurs after routing and retains source plus routed artifacts. |

Research: official pinned [BCFtools 1.19 manual](https://raw.githubusercontent.com/samtools/bcftools/1.19/doc/bcftools.txt) documents `view -A` for unseen wildcards at variant sites and `-AA` for all sites; `norm` is documented for reference-aware indel normalization, REF checks and multiallelic splitting. Official [1.19 release notes](https://raw.githubusercontent.com/samtools/bcftools/1.19/NEWS) describe some symbolic `<DEL.*>` support and a `<DEL>` REF-expansion issue. Neither tool behavior establishes complete SV/GVCF interpretation.

Commits [`0afbb1b`](https://github.com/SayedaRehmat/SIRALOOM/commit/0afbb1bc6786934dc2246605ef2c22c6a073d544) and [`490fda8`](https://github.com/SayedaRehmat/SIRALOOM/commit/490fda80f04615c59df31a18f7cde819b63634bf) added the production-worker test and PostgreSQL + real-BCFtools integration. Initial run #1743 exposed test-fixture membership/FK ordering failures; commits `a99af28` and `c7e1eb7` repaired them. Exact-SHA run [`39413084941`](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39413084941) then passed on `c7e1eb7`: backend **1,092 passed, 28 skipped** and PostgreSQL integration **27 passed**; CI installed and asserted BCFtools 1.19. This confirms the previous pushed worker/integration code path, not the current uncommitted metadata changes. Local PostgreSQL and BCFtools remain unavailable. Phase A remains PARTIAL.

## 2026-10-20 GVCF/SV routing and per-artifact review provenance

| Capability | Status | Evidence / limitation |
|---|---|---|
| Called concrete variant in mixed GVCF proceeds to sequence normalization | PARTIAL | Router sends it only when all sample GTs are complete and do not call the wildcard; production normalizer uses pinned BCFtools `view -A` then reference-aware `norm`. Exact-SHA run [`39414744914`](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39414744914) passed on `e908bae`; PostgreSQL integration passed 27 tests with BCFtools 1.19 installed/asserted, including persisted GT/AD/PL, artifacts and reference lineage. |
| Reference-only GVCF blocks | PARTIAL | Preserved as `GVCF_REFERENCE_BLOCKS`, explicitly marked `NOT_ANALYZED`/`GVCF_REFERENCE_CONFIDENCE_ANALYSIS_UNSUPPORTED`, and routed to `REQUIRES_REVIEW`; reference validation is explicitly `NOT_RUN` when no sequence variant causes package resolution. No reference-confidence analysis is implemented. |
| Unresolved `<NON_REF>`/`<*>` variant genotype | PARTIAL | Preserved as `UNRESOLVED_GVCF_VARIANTS` with `GVCF_VARIANT_ALLELE_UNRESOLVED`; not interpreted. Updated worker regression passed in exact-SHA run #39414744914. |
| Symbolic SV and BND; spanning deletion `*` | PARTIAL | Preserved in typed artifacts with explicit specialized-review reason. Mixed inputs record selected reference package/version/checksum and REF validation result; these rows are not claimed as interpreted. Malformed structure or selected-reference mismatch remains blocked with reason/audit. Updated production-worker regressions passed in run #39414744914. |
| Per-artifact reference-validation provenance | PASS (automated scope) | Exact-SHA run #39414744914 passed the worker and PostgreSQL assertions for `NOT_RUN` on review-only inputs, `PASS` with selected package identity on matching mixed inputs, and `FAILED` with mismatch reason on incompatible input. |
| Local source and routing smoke | PASS (narrow helper scope) | Bundled Python 3.12 compileall passed; a direct smoke call to `route_vcf_records` preserved and counted 9 representative rows across sequence, GVCF block, unresolved wildcard, symbolic DEL, reciprocal BND and `*` routes. This does not exercise database persistence, the production worker, BCFtools or PostgreSQL. |

Research: pinned [BCFtools 1.19 manual](https://raw.githubusercontent.com/samtools/bcftools/1.19/doc/bcftools.txt) and [1.19 release notes](https://raw.githubusercontent.com/samtools/bcftools/1.19/NEWS); current [HTS VCFv4.5 specification](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex). Repository validator currently accepts only VCFv4.2/v4.3; VCFv4.5 is not claimed as supported. The reference-block/SV processing boundary is intentional because those downstream analytical stages are not implemented. Exact-SHA run [`39414744914`](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39414744914) passed at `e908bae`: backend 1,093 passed/28 skipped; PostgreSQL integration 27 passed with pinned BCFtools 1.19; frontend 29 tests and production build passed. This is software workflow evidence only, not GVCF-reference-confidence/SV clinical interpretation, truth-set validation, live identity, deployed tenant isolation or laboratory deployment. Phase A remains PARTIAL.

## 2026-10-20 review-page technical QC wiring

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Review page displays and records assay-specific technical QC using persisted API data | PASS (frontend automated scope) | Corrected display to consume newest-first `assessments[]`; added controls for recording QC observations and submitting metrics to the existing assay-rule assessment endpoint. Regression tests cover latest assessment, latest metric value and null/unavailable preservation. i18n guard PASS; frontend suite 31 passed; Next production build/typecheck PASS; diff check PASS. Exact-SHA Actions [run #39422733480](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39422733480) succeeded for backend, PostgreSQL/worker-loss integration, frontend tests/build, production image and Compose validation. No live Firebase/deployed endpoint interaction or laboratory QC policy qualification was performed. |
| Review QC per-rule transparency | PASS (automated frontend scope) | Latest persisted `evaluated_rules` render with value and configured direction/threshold or range; local frontend tests (31), localization guard, and production build/typecheck pass. No live assay profile or lab deployment was exercised. |

Phase A remains PARTIAL. Live browser identity, deployed tenant isolation, real-storage reviewer/signout recovery, and actual scientific/laboratory qualification remain unverified.

## 2026-10-20 case-access manager role parity

| Requirement | Status | Evidence / limitation |
|---|---|---|
| UI exposes case assignment management to all and only the backend's case-access admin roles | PASS (local frontend regression scope) | Frontend role helper matches server `CASE_ACCESS_ADMIN_ROLES`: platform admin, organization admin, and lab director. Regression test covers those and representative denied roles. Frontend 32 tests and i18n guard pass; production build/typecheck and 24 static pages pass; exact-SHA CI for this role-parity change is pending. Server authorization remains authoritative. |

## 2026-10-20 report action role parity

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Reportability evaluation/draft generation and reportability/report sign-out controls match backend roles | PASS (local frontend regression scope) | UI now resolves authenticated server session role; generation/evaluation follow backend case-write roles and finalization follows signatory roles. Tests cover both role sets; i18n guard and production build/typecheck pass; frontend suite 34 passed. API authorization remains authoritative. No live or deployed role/sign-out test was run. Commit `5eba4b1` passed both exact-SHA Actions runs #39425262052 and #39425254556 (backend, PostgreSQL integration, frontend). |

| Review-page write and signatory controls follow backend role policy | PASS (local frontend automated scope) | Phenotype, pedigree/segregation, QC observation, confirmation and follow-up controls require backend-aligned case-write roles; secondary-finding decisions require signatory roles. Session lookup failure hides editing controls. i18n guard PASS, frontend suite 34 passed, production build/typecheck and 24 pages PASS, diff check PASS. Backend role constants and route guards inspected. Live/deployed authorization journey NOT RUN; exact-SHA CI pending. |

| Direct variant-detail object authorization and selected-analysis binding | PARTIAL | The endpoint now checks case-level read access and analysis membership; the workspace passes its selected `analysis_id`. Regression tests were added for unassigned-case denial and authorized fallback. Python 3.12 compileall, frontend i18n guard, 34 frontend session tests, and production build/typecheck PASS. Six focused backend tenant/authorization test files: 99 passed. Broader non-integration backend suite: 1,093 passed, 15 skipped, 1 unrelated PDF-renderer failure due missing native `libgobject-2.0-0`, 27 integration tests deselected. Exact-SHA CI and deployed cross-tenant verification pending. |
