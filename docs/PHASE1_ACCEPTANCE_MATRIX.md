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

| Identity and membership role authorization | PASS (focused automated scope) | Inspected principal resolution, invitations, membership roster, serialized membership changes, role hierarchy and case-grant revocation. Focused suite: 31 passed. This does not establish live Firebase/browser identity or deployed access behavior. |
| Analysis worker dispatch identity and redelivery fencing | PASS (focused local test scope) | Inspected persisted queue-task identity and execution claim gates. Outbox, generation-fence and annotation/population redelivery tests: 22 passed. PostgreSQL worker-loss integration and deployed recovery remain NOT RUN. |

| Report review, authorization, sign-out and reportability recovery guards | PASS (local unit/source scope) | Inspected API authorization, version checks, serialized finalization, immutable signed artifact lineage, supersession, idempotent sign-out retry and durable reanalysis resume. Focused report/signout suite: 29 passed. PostgreSQL concurrent sign-out, live cloud storage failures/retry and deployed retrieval are NOT RUN. |

| Case archive export authorization, lineage, integrity and retry handling | PASS (local automated scope) | Inspected API role/case access, worker task claim, case/analysis scoped archive queries, artifact-lineage checks, checksum/size verification, download authorization and artifact compensation. Six focused export test files: 20 passed. PostgreSQL worker-loss integration, real cloud-storage recovery and deployed tenant export isolation are NOT RUN. |

| Resource-registry tenant access, approval roles and staging ownership | PASS (local automated scope) | Inspected organization/global resource boundaries, staging record resource/version binding and organization cache path validation. Eight focused registry/staging test files: 61 passed. Live provider qualification, PostgreSQL dispatch integration and deployed laboratory storage isolation are NOT RUN. |

| Live Firebase identity and controlled Docker deployment journey | BLOCKED (environment) | Verified no local `.env`/`frontend/.env.local`, no Firebase public web config variables in process, no Firebase Auth emulator in `firebase.json`, and no Docker CLI. No live identity/deployment check was run. Requires a configured Firebase test project and deployment-capable host. |

## 2026-10-20 VCF intake regression evidence

| Requirement | Status | Evidence / limitation |
|---|---|---|
| VCF parsing, intake validation, case idempotency, upload capacity policy, and unsupported-class routing | PASS (local automated scope) | Command: `.venv\Scripts\python.exe -m pytest tests/test_ingestion.py tests/test_vcf_validation.py tests/test_vcf_tools.py tests/test_vcf.py tests/test_case_create_idempotency.py tests/test_upload_capacity_policy.py tests/test_unsupported_vcf_worker_routing.py -q -rs`; **83 passed, 5 skipped**. The five skips are BCFtools-gated production normalization tests because BCFtools is unavailable locally. This does not establish independent scientific benchmark concordance, deployed storage behavior, or laboratory QC qualification. |

Phase A remains PARTIAL. Live Firebase/browser identity, deployed two-tenant API and artifact isolation, real-storage reviewer/signout recovery, and scientific/laboratory qualification remain unverified or blocked as recorded above.

## 2026-10-20 technical QC non-finite input safeguard

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Reject non-finite QC observations, assessed metrics, and assay rule bounds | PASS (focused local regression scope) | QC evaluator/API now reject NaN, infinities, booleans, oversized integers, incomplete/non-finite thresholds, invalid ranges, and blank metric names. Command: `.venv\Scripts\python.exe -m pytest tests/test_m11_technical_qc.py tests/test_quality_route_authorization.py tests/test_qc_artifact_lineage.py tests/test_clinical_followup_persistence.py -q -rs`; **29 passed**. This validates input integrity only; it does not qualify laboratory thresholds or the assay. Exact-SHA CI pending. |

| Broad non-integration backend regression at `e5832d5d6222084d2db91a59d9dd12fdb2f79dc9` | PARTIAL | `.venv\Scripts\python.exe -m pytest -q -m "not integration"`: **1,106 passed, 15 skipped, 1 failed, 27 deselected**. The sole failure is `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes` because Windows cannot load WeasyPrint's native `libgobject-2.0-0`; this is an environment dependency failure, not established as unrelated to production PDF behavior. GitHub Actions exact-SHA result remains pending connection/verification. |

| Reviewer/read-only case members can inspect segregation evidence | PASS (focused automated permission scope) | Corrected segregation GET to use case read permission and `READ_ROLES`; assessment and mutation endpoints retain their stricter review/write checks. Tenant/object suites: **79 passed**; focused segregation tests: **3 passed**. No live reviewer browser journey or deployed case-grant check was run. |

| Notification and reanalysis candidate direct-object access | PASS (local automated scope) | Inspected organization/recipient scoping, linked-record lineage, case-grant rechecks, candidate ownership, parent/child consistency, trigger/resource binding and queue-failure recovery. Four focused API/lifecycle suites: **73 passed**. Deployed two-tenant validation and PostgreSQL concurrency remain NOT RUN. |

Phase A remains PARTIAL. Scientific threshold qualification, live identity, deployed tenant/storage isolation, and real-storage report recovery are still unverified.

## Current release-gate snapshot — 2026-10-24

**Repository checkpoint:** `main` at [`2ef07b68f539f8f81d9f14c7eb42204ab33b09fe`](https://github.com/SayedaRehmat/SIRALOOM/commit/2ef07b68f539f8f81d9f14c7eb42204ab33b09fe). Linux `HEAD` and `origin/main` were verified equal. Exact-SHA GitHub Actions run [#40078518465](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40078518465) passed backend, PostgreSQL/Celery worker-loss integration, and frontend/container/Compose jobs. The exact-SHA Vercel status completed successfully; the production URL returned HTTP 200. This is application deployment evidence, not laboratory backend qualification.

| Gate | Status | Current evidence and limitation |
|---|---|---|
| gnomAD missing-AN semantics (`AC=0`, `AN=null`/zero) | **PASS — automated scope** | Exact missing-value regression and downstream population/evidence consumers passed in Linux. gnomAD-focused tests: **29 passed**; adjacent population/evidence/consumer tests: **93 passed, 1 skipped**. No live gnomAD provider or independent scientific benchmark was run. |
| HPO OBO checksum-to-parser integrity | **PASS — automated/resource-format scope** | Provider reads once, hashes and parses the same bytes. TOCTOU regression is included. Combined HPO/gnomAD suite: **81 passed**; official HPO base release `2026-09-01` parsed at the publisher's SHA-256, with 20,482 terms. This does not establish clinical phenotype-ranking validity or laboratory qualification. |
| Worker redelivery regression relevant to the population stage | **PASS — deterministic integration scope** | `tests/test_actual_population_stage_redelivery.py`: **8 passed** locally. Separate exact-SHA PostgreSQL/Celery worker-loss CI job also passed. This is not end-to-end recovery through all stages on laboratory object storage. |
| Authenticated Firebase signup, verification, recovery, login/logout and protected-page revisit | **NOT RUN** | No live authenticated browser journey against a configured Firebase test project is evidenced here. |
| Deployed two-laboratory API, membership, object and artifact isolation | **NOT RUN** | No two-laboratory deployed test identities or lab storage configuration were exercised. |
| Complete deployed VCF-to-review-to-authorized-signout workflow | **NOT RUN** | Current local fixtures and CI do not demonstrate a real laboratory case, qualified external resources, authenticated reviewers and authorized report delivery end to end. |
| Failure/recovery with laboratory PostgreSQL, Redis, workers and object storage | **PARTIAL** | CI PostgreSQL/Celery worker-loss integration and local deterministic stage-redelivery tests passed; no lab object store, provider outage/recovery or deployed signout recovery was tested. |
| Independent germline truth-set concordance | **NOT RUN** | No approved/pinned GIAB truth set, confidence regions and comparison run with TP/FP/FN metrics are recorded. |
| Laboratory installation, backup/restore, capacity and rollback qualification | **NOT RUN** | CI container/Compose checks and a reachable Vercel frontend do not demonstrate lab-managed infrastructure, durable storage, measured capacity or a restore exercise. |
| Clinical validity, clinical utility, accreditation or regulatory authorization | **NOT ESTABLISHED** | Requires separate scientific validation and laboratory governance; software tests and deployment checks cannot establish these claims. |

**Release decision: BLOCKED for laboratory trial or clinical workflow. Phase A remains PARTIAL.** The gnomAD and HPO integrity fixes are verified within the stated automated scopes; live identity, deployed tenant isolation, full laboratory workflow/recovery, independent benchmark and laboratory deployment qualification remain outstanding. No clinical validation or production qualification is claimed.

## 2026-10-24 production broker authentication follow-up

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Production Redis broker requires authentication and clients use the same credential | PASS (configuration and application-start guard) | Production Compose requires a Redis password, enables `requirepass`, keeps the port unpublished, authenticates its health probe, and injects the credential into API/worker/Beat URLs. Production settings reject missing/weak AUTH URLs. Focused deployment/security suite: **33 passed**. Local live Redis execution was unavailable. Exact-SHA GitHub Actions run [40079418085](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40079418085) passed its production Compose validation. Redis ACL command restrictions, in-network TLS and laboratory qualification are not established. |

This closes the unauthenticated broker configuration gap for the included Compose deployment. It does not establish deployed laboratory security or make the overall release ready; live tenant isolation, real workflow/recovery, truth-set validation and backup/restore remain unverified.


## 2026-10-24 reanalysis reproducibility fingerprint follow-up

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Reanalysis comparison accounts for source VCF and persisted scientific, QC, inheritance, review, reportability and stage execution state | PASS (controlled persisted SQLite scope) | Comparator fingerprints source checksum and relevant persisted outputs/decisions, excludes random row IDs, and rejects invalid/missing source or workflow artifact provenance as ineligible. Regression suite exercises these cases and scientific-output mismatches; exact command and **26 passed** are recorded in `MASTER_AUDIT_AND_REMEDIATION.md`. No real laboratory parent/child pair or PostgreSQL execution was available. |
| Segregation/reanalysis provenance includes the pedigree graph used for family interpretation | PASS for new segregation writes; legacy observations are ineligible without a snapshot | Segregation writes now persist a server-generated versioned snapshot of stable family member attributes, specimen identifiers/types, and pedigree edges. The parent/child manifest fingerprints that snapshot; it reports missing legacy snapshots as incomplete provenance. The focused API, access-control, review, and reanalysis suite passed **127 tests**. This does not validate clinical inheritance logic or recover pedigree state that was never snapshotted for old analyses. |

The CLI/service regression is database-backed but uses controlled fixtures. It does not demonstrate reproducibility against real laboratory data, scientific validation, or lab qualification. Overall Phase A remains PARTIAL.

## 2026-10-24 pedigree-to-specimen workflow connection

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Review UI can associate a pedigree member marked as sampled with a specimen in the same case | PASS (API/UI implementation and controlled regression) | Review now loads specimens from the permission-checked case dossier, offers an optional specimen link, submits the selected `specimen_id`, and displays the linked specimen identifier. Backend regression verifies the case-scoped specimen link is persisted; cross-case specimen denial remains covered. Backend command covering pedigree authorization, observation, review and lineage: **98 passed**. Frontend session tests: **39 passed**; i18n guard and `tsc --noEmit` passed. Production frontend build was NOT RUN successfully: invoking the Windows Node executable from the WSL UNC working directory attempted Windows SWC and failed to spawn/build; a Linux Node runtime was unavailable. No UI browser journey or deployed VCF sample-to-specimen match was verified. |

This connects the pedigree member to the case specimen record but does not establish that the specimen's VCF sample name matches the pedigree identifier, nor does it implement automated segregation or inheritance interpretation. Phase A remains PARTIAL; scientific validation and laboratory deployment qualification remain NOT COMPLETE.

## 2026-10-24 single-sample analysis intake boundary

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Analysis cannot treat sites-only or multisample VCF records as one patient's variants | PASS (automated analysis-creation gate) | `validate_analysis_input_artifact` requires exactly one nonblank sample name from persisted ingestion validation metadata before analysis creation. Helper regressions cover missing, empty, multisample and accepted single-sample metadata; database-backed regressions verify rejected inputs create no analysis and consume no quota. Focused backend command: **41 passed** (analysis input, quota, ingestion and artifact-integrity suites). |

The gate does not yet match the VCF sample name to a case specimen/pedigree member or persist genotype/zygosity in normalized variant records. Single-sample input is therefore only a safe scope restriction, not complete sample identity or genotype-aware analysis. Multisample family VCF analysis remains unsupported and is rejected; Phase A remains PARTIAL.

## 2026-10-24 explicit VCF sample-to-specimen identity

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Analysis input VCF sample is explicitly mapped to its case specimen | PASS (automated intake/preflight scope) | Specimen registration accepts a laboratory-declared `vcf_sample_name`; both case-intake and workspace UI collect and display it. Analysis creation verifies one exact VCF header sample equals the mapping and records the sample and specimen IDs in the analysis configuration snapshot. Analysis start rechecks that artifact, specimen, case and mapping still agree, preventing a changed mapping from silently running. Regressions cover exact match, mismatch, missing mapping, ambiguous sample scope, no analysis/quota mutation on failure, and specimen metadata persistence. Backend focused tests: **52 passed** across the mapping, quota, specimen authorization/conflict and intake suites; frontend session tests: **39 passed**; i18n guard and Next production build passed. |

This identity link does not yet parse or persist per-variant genotype/zygosity, exclude homozygous-reference calls, or establish sample identity independently of laboratory-supplied metadata. Those remain critical scientific workflow gaps. Existing specimens without this explicit mapping cannot start new analyses until corrected. Phase A remains PARTIAL.

## 2026-10-24 reference-only genotype candidate exclusion

| Requirement | Status | Evidence / limitation |
|---|---|---|
| A single-sample reference-only genotype is not created as an analysis candidate | PASS (automated normalized-iterator scope) | The shared normalized VCF iterator filters all-reference calls (diploid `0/0` and haploid `0`); the original and normalized VCF artifacts remain intact. Normalization stage metadata records input allele-record and excluded reference-only genotype counts. Regression verifies reference calls are excluded while `0/1` remains. |
| Reference-only records cannot block sign-out as if they were alternate findings | PASS (downstream iterator scope) | Annotation and population processing use the same filtered iterator as normalization, so excluded alleles do not acquire candidate rows or classifications. Combined report/reanalysis regression command: **56 passed**; normalization, VCF and unsupported-input regressions: **68 passed, 1 skipped**. |
| Exclusion lineage identifies every source record individually | PARTIAL | Aggregate counts and immutable source/normalized artifacts are preserved; an individual excluded-record manifest is not yet persisted. The BCFtools-dependent multiallelic execution was skipped in this environment. This change does not establish clinical interpretation or validation. Phase A remains PARTIAL. |

## 2026-10-24 persisted genotype evidence and sign-out gate

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Single-sample GT, phase and selected FORMAT values survive normalization and are linked to each analysis variant | PASS (controlled parser/SQLite partition scope) | VCF parsing retains GT, zygosity, phase/PS and DP/GQ/AD/PL/GL/GP; normalization partitions persist aligned call snapshots without changing canonical allele identity. Focused streaming, report, sign-out and reanalysis suite: **55 passed**. |
| Report findings expose persisted genotype and sign-out rejects absent/incomplete or homozygous-reference calls | PASS (controlled reportability scope) | Report content reads the analysis-scoped normalized partition; regressions verify reported genotype and fail-closed behavior for missing/no-call and 0/0. |
| Genotype evidence participates in reanalysis reproducibility | PASS (controlled persisted SQLite scope) | Manifest includes the call data and flags missing or malformed call lineage. Parent/child comparison fixtures include persisted call snapshots. |
| Actual BCFtools multiallelic split followed by genotype capture | NOT RUN | The two focused BCFtools 1.19 integration cases were skipped because `bcftools` is unavailable in this WSL environment. Existing test fixtures define the expected allele-index and FORMAT transformation; this environment did not execute them. |
| Clinical sample identity, assay QC policy, segregation validity or clinical interpretation | NOT ESTABLISHED | Calls preserve supplied VCF values; they do not establish specimen identity independently, validate assay-specific QC thresholds, or prove inheritance/clinical significance. The full workflow and Phase A remain PARTIAL. |

Focused command: `pytest ... tests/test_m13_streaming_partitions.py tests/test_reporting_signout.py tests/test_reporting_contract.py tests/test_reportability_m6.py tests/test_reanalysis_reproducibility_manifest.py tests/test_reanalysis_comparison_cli.py tests/test_report_artifact_replay_idempotency.py` — **55 passed**. Static checks on the broad changed modules report pre-existing unused imports/locals and import-order findings; `git diff --check` passed.

## 2026-10-25 assay QC policy and clinical sign-out binding

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Analysis selects an active same-organization assay with usable QC rules | PASS (API validation scope) | Analysis creation rejects missing, foreign, inactive, malformed, or rule-free profiles when an assay is supplied. Assay creation validates rule shape and permits only ACTIVE/INACTIVE status; ACTIVE profiles require at least one valid rule. |
| Clinical report eligibility requires reviewed passing assay QC | PASS (SQLite/API and report-service tests) | Clinical eligibility requires organization-bound active profile, matching profile name/version, reviewer identity/time, and PASS gate. QC assessments can only use values matching persisted latest observations. Analytical reports keep their existing distinct eligibility policy. |
| Sign-out is bound to QC evidence used by draft | PASS (report finalization regression) | Report content records assessment identity, profile, measurements, evaluated rules and reviewer. Finalization rejects a changed assessment snapshot, including changed metrics that still pass. |
| Frontend selects the assay and presents the QC gate | PARTIAL (automated frontend scope) | Workspace loads active case-organization profiles and sends selected assay ID; English/Arabic copy explains the gate. Frontend session tests **39 passed** and i18n guard passed. Production build compilation and type check passed, but the WSL build stalled during final trace collection and was interrupted; complete build is NOT RUN. No live browser/Firebase workflow was exercised. |
| Laboratory assay QC qualification | NOT ESTABLISHED | Rules remain laboratory-configured and have not been qualified against a real assay/SOP or deployed lab data. This control does not establish clinical validity, sample identity, or regulatory compliance. |

Verification: Linux command `PYTHONPATH=. DATABASE_URL=sqlite:////tmp/siraloom-qc-final4.sqlite REDIS_URL=redis://localhost:6379/0 GENEBE_ENABLED=false GNOMAD_ENABLED=false .venv/bin/python -m pytest -p no:cacheprovider --basetemp=/tmp/siraloom-qc-final4 -q --tb=short tests/test_analysis_assay_qc_gate.py tests/test_m11_technical_qc.py tests/test_quality_route_authorization.py tests/test_reporting_signout.py tests/test_reporting_contract.py tests/test_report_finalization.py tests/test_report_signout_resume.py tests/test_report_finalization_order.py tests/test_reportability_m6.py tests/test_reviewer_to_signed_report_integration.py tests/test_route_mutation_tenant_guards.py tests/test_report_artifact_commit_compensation.py` — **101 passed**, one existing Starlette/httpx deprecation warning. Frontend session suite — **39 passed**. `npm run build` passed i18n, compilation and type-check stages but did not finish trace collection. Overall Phase A remains **PARTIAL**.

### 2026-10-25 reject malformed legacy assay rules at analysis creation

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Analysis creation validates actual assay QC-rule schema, including pre-existing profiles | PASS (route guard tests) | Intake now normalizes and validates rules rather than checking only that the `rules` field is non-empty. Cross-organization, inactive, empty, null, and malformed-direction profiles all fail before analysis/quota mutation. |

Verification: `PYTHONPATH=. DATABASE_URL=sqlite:////tmp/siraloom-assay-schema.sqlite REDIS_URL=redis://localhost:6379/0 GENEBE_ENABLED=false GNOMAD_ENABLED=false .venv/bin/python -m pytest -p no:cacheprovider --basetemp=/tmp/siraloom-assay-schema -q --tb=short tests/test_analysis_assay_qc_gate.py tests/test_quality_route_authorization.py tests/test_reporting_signout.py` — **40 passed**, one existing Starlette/httpx deprecation warning. This is schema/authorization-path coverage, not laboratory QC qualification.

### 2026-10-25 persist QC observation lineage through sign-out

| Requirement | Status | Evidence / limitation |
|---|---|---|
| QC assessment identifies every observation and linked artifact checksum it consumed | PASS (SQLite/API scope) | Migration `0053_qc_observation_snapshot` adds a nullable snapshot for backward compatibility; new assessments persist observation IDs, values, units, status, source, version, metadata, timestamp, artifact identity/type/checksum. Legacy assessments without snapshots are blocked from new clinical sign-out until reassessed. |
| New or changed QC observations invalidate an existing assessment | PASS (report eligibility scope) | Final eligibility recomputes the current observation lineage and metric values and compares them with the reviewed assessment. Artifact references are checked against case/analysis ownership. Regression tests include added observations, foreign artifact references, and sibling-analysis artifact exclusion. |
| Review UI can link QC observations to an available validated VCF artifact | PASS (API/TypeScript scope) | Quality API offers only same-case source artifacts or the current analysis’s normalized VCFs. The review UI submits an optional artifact ID; server verifies case/analysis lineage. Frontend session tests **39 passed**, i18n guard and TypeScript `--noEmit` passed. |
| Signed report reflects its technical-QC basis | PASS (rendered HTML scope) | Report snapshot stores the QC assessment and observation snapshot. HTML output displays the gate/profile, evaluated rules, and observation source/version/artifact SHA-256. Test asserts these persisted fields appear in rendered HTML. PDF renderer execution remains environment-limited and was not run here. |
| Migration upgrade/downgrade and analysis reproducibility include QC lineage | PASS (SQLite migration/reanalysis scope) | Full migration upgrade verifies the nullable column; downgrade to revision `0052` removes only the new column and retains the QC table. Reanalysis manifest includes the observation snapshot. |

Verification command: Linux backend scope including migration, QC authorization/artifact lineage, report generation/sign-out/recovery, and reanalysis reproducibility — **119 passed**, one existing Starlette/httpx deprecation warning. Ruff `--select F`, Python compilation, and diff checks passed. This establishes software lineage controls only; it does not qualify the laboratory’s QC source or thresholds. Overall Phase A remains **PARTIAL**.

### 2026-10-25 serialize QC mutations against clinical sign-out

| Requirement | Status | Evidence / limitation |
|---|---|---|
| QC observations and assessments serialize with sign-out's analysis lock | PASS (code-path/unit scope) | Both QC mutation routes refresh and lock the authorized analysis row before reading or writing QC state. Sign-out already takes `FOR UPDATE` on the same row before eligibility and snapshot checks. This prevents a QC write from committing concurrently inside the sign-out eligibility window on PostgreSQL. |
| QC concurrency guard regression coverage | PASS (unit/API scope) | Route tests assert both observation recording and assessment use the shared analysis lock; report/sign-out integration regression suite passes. SQLite ignores row-level `FOR UPDATE`, so production-dialect concurrency still requires PostgreSQL integration execution. |

Verification: focused QC authorization, artifact lineage, report sign-out and reviewer/sign-out suite — **47 passed**, one existing Starlette/httpx deprecation warning. PostgreSQL race execution remains NOT RUN.

### 2026-10-25 enforce QC source-artifact contract

| Requirement | Status | Evidence / limitation |
|---|---|---|
| QC provenance only cites valid VCF artifacts | PASS (route/unit scope) | API rejects non-VCF, invalid/pending, malformed-checksum, cross-case, and sibling-analysis artifact links. Existing invalid artifact lineage returns HTTP 409 instead of a server error, and report eligibility uses the same contract. |
| QC source-artifact boundary regression tests | PASS (SQLite/API scope) | Tests cover REPORT_PDF, INVALID VCF, PENDING VCF, foreign lineage, and valid source/normalized VCFs. |

Verification: QC route, lineage, report generation/sign-out and reviewer integration tests — **71 passed**, one existing Starlette/httpx deprecation warning. Ruff, Python compilation and diff checks passed.

### 2026-10-25 prioritize reference-build mismatch in analysis intake diagnostics

| Requirement | Status | Evidence / limitation |
|---|---|---|
| A declared VCF/reference build mismatch is reported before sample mapping problems | PASS (worker unit scope) | `validate_analysis_input_artifact` now validates supported build identity and exact assembly agreement before sample cardinality/mapping. This reports the high-risk reference incompatibility directly while still rejecting sites-only/multisample inputs. |
| Broad backend regression suite | PASS (SQLite/local scope) | **1,373 passed, 46 skipped**; report PDF renderer module excluded because its native rendering environment was not exercised. Existing Starlette/httpx deprecation warning remains. |

Focused prior failure set: **42 passed**. This diagnostic-ordering correction does not change accepted assemblies or sample scope. Live laboratory input qualification remains outstanding.

## 2026-10-26 release-gate implementation follow-up

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Retired ClinGen PP5/BP6 source assertions remain review-only through durable persistence and retry | PASS (controlled SQLite/service scope) | Commit [`e345650`](https://github.com/SayedaRehmat/SIRALOOM/commit/e345650f9e637f69fde7cca5617c2ee8e4f63d7c) persists source assertion identity, specification/version, rationale and `REQUIRES_REVIEW` state without creating a classification. Regression verifies both PP5 and BP6 plus idempotent repeated persistence. Focused ACMG/ClinGen suite: **32 passed**; full Linux suite: **1,467 passed, 46 skipped**. Exact-SHA CI run [40310257138](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40310257138) passed. This does not establish classification validity beyond the tested safeguard. |
| Laboratory backup bundle, integrity verifier and restore-to-new-target command | PARTIAL (implementation and automated scope) | Commits [`21cb88a`](https://github.com/SayedaRehmat/SIRALOOM/commit/21cb88a7a5c981195a5ec8869328241397d39020) and [`8f34808`](https://github.com/SayedaRehmat/SIRALOOM/commit/8f34808ee9453c975c4ae6c3258aac15ad33287b) add custom-format PostgreSQL dump orchestration, artifact/reference/resource-cache archives, hashes, safe archive validation and restore refusal for existing targets. Focused backup/deployment suite: **18 passed**; Ruff, formatting, Python compilation and CLI checks passed. Exact-SHA CI run [40311758158](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40311758158) passed backend, PostgreSQL/Celery and frontend/container/Compose jobs. |
| Actual laboratory Compose backup and PostgreSQL/artifact restore exercise | NOT TESTED | Docker is unavailable in this WSL environment (`docker: command not found`). No real `pg_dump`/`pg_restore`, isolated deployment, restored artifact-hash comparison or measured recovery time was executed. Do not treat CI container builds or archive helper tests as restore evidence. |
| Live Firebase/browser workflow, deployed two-lab API/artifact isolation, real-storage reviewer-to-signout recovery, and independent GIAB benchmark | BLOCKED / NOT TESTED | No configured laboratory deployment, Firebase test credentials, lab-owned storage, or approved benchmark execution environment was available in this work session. Existing API/unit/CI evidence remains narrower than these release gates. |

**Repository checkpoint before this follow-up:** Linux `main` at [`105fd746b49d3a9e639842b6d92b2a74e91e7150`](https://github.com/SayedaRehmat/SIRALOOM/commit/105fd746b49d3a9e639842b6d92b2a74e91e7150); fetched `origin/main` matched. Exact-SHA CI run [40312252892](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40312252892) passed backend, PostgreSQL integration, and frontend jobs. **Release decision remains BLOCKED for laboratory trial or clinical workflow. Phase A remains PARTIAL.** No clinical validation, laboratory qualification, or disaster-recovery demonstration is claimed.

### 2026-10-26 require isolated restore context

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Backup restore refuses the live/default Compose context and active application writers | PASS (deterministic CLI/service-guard scope) | `scripts/laboratory_backup.py` now requires a dedicated `siraloom_restore` Compose project, an explicit existing environment file, and no running API, worker, Beat or frontend service before creating a restore database or storage target. Regression tests verify missing/invalid isolation inputs and active application services fail before storage targets are created. Backup/deployment tests: **23 passed**. |
| Actual isolated PostgreSQL and artifact restore | NOT TESTED | Docker is unavailable in this WSL environment; no real `pg_restore`, isolated Compose lifecycle, or post-restore artifact comparison was performed. |

The guard reduces the risk of an operator accidentally restoring into the normal Compose context. It does not prove the supplied project/environment points to a dedicated laboratory restore host, and does not qualify a real recovery objective. Phase A and deployment readiness remain **PARTIAL**.

**Follow-up code checkpoint:** commit [`4d35ffb4403cab5d3813c1087ce6c9dba9f1b520`](https://github.com/SayedaRehmat/SIRALOOM/commit/4d35ffb4403cab5d3813c1087ce6c9dba9f1b520) is on `origin/main`; exact-SHA CI run [40313345990](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/40313345990) passed all three jobs. This does not change the NOT TESTED status of an actual laboratory backup/restore.

### 2026-10-26 HPOA and patient phenotype review context

| Requirement | Status | Evidence / limitation |
|---|---|---|
| Preserve distinct HPOA `NOT`, HPO Excluded frequency, literal `0%`, and cohort `0/N` semantics in comparison output | PASS (deterministic implementation/test scope) | Evidence engine comparison uses pinned HPO release and aspect P; tests assert distinct source semantics/types, `0/3` denominator preservation, unresolved/missing ontology, patient present/absent/unknown, and hierarchy direction. |
| Persist the real workflow's patient/HPOA comparison and render review context in the bilingual reviewer interface | PASS (local workflow/frontend test scope) | `tests/test_actual_population_stage_redelivery.py` verifies worker persistence and pinned ontology lineage; localization guard, 40 frontend session tests, TypeScript check, and Next production build passed. The context is explicitly non-scored and does not affect classification or ranking. |
| Clinical validity of phenotype matching, diagnostic ranking, or disease-specific interpretation | NOT ESTABLISHED | This is a constrained reviewer aid, not a validated similarity algorithm or clinical utility assessment. No expert-adjudicated clinical benchmark was performed. |

The official HPO references and implementation rationale are recorded in `docs/research/GERMLINE_LAB_WORKFLOW_AND_RESOURCE_RESEARCH.md` and the engineering ledger. This increment does not change the overall release decision: Phase A remains PARTIAL; live identity, deployed tenant/storage isolation, complete lab signout/recovery, independent truth-set benchmarking, and actual deployment/restore qualification are still unverified.
