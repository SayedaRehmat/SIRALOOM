# Prioritized implementation roadmap and defect register

Priority definitions: **P0** blocks safe external pilot; **P1** material release risk; **P2** needed for broader production scale; **P3** improvement. Priorities reflect current evidence and must be revised when live validation yields new findings.

| ID | Priority | Finding / evidence | Required next action | Exit evidence |
|---|---|---|---|---|
| AUD-001 | P0 | No verified live E2E run in inspected release docs; acceptance matrix marks E2E and deployment NOT VALIDATED | Run the documented public benchmark smoke test on a controlled deployment and capture complete provenance | Reproducible case-to-export dossier on a pinned revision |
| AUD-002 | P0 | Independent scientific concordance and ACMG/ClinGen correctness remain unvalidated in repo docs | Freeze supported variant/provider scope; create golden fixtures and independent expected outputs | Reviewed discrepancy report and approved acceptance criteria |
| AUD-003 | P0 | Variant-support statements require continued reconciliation across strict validator, normalization, annotation provider and report behavior | Trace exact intake→normalization→annotation→report behavior for SNVs, MNVs, indels, multiallelic records, symbolic alleles, breakends, SVs, GVCF blocks, phasing and sample genotypes | Per-class automated fixtures; unsupported variants fail visibly |
| AUD-004 | P0 | Governed resource runtime binding was merged as `cab2c93b46566ab9b31ca83ebfdfb24eba9f160c`; current `main` is now `c91ed0e2fca9133dbd33f9365ce934221f1557c8` and its CI run `38036686972` is green | Qualify the real API preflight and worker start/recovery matrix against governed reference, annotation, population and ACMG resource identities | CI plus controlled integration evidence for ready, optional-limited, required-blocked, recovery and no-duplicate dispatch |
| AUD-005 | P0 | Worker/queue recovery logic is now covered by real PostgreSQL/Redis/Celery worker-loss CI, including production-task recovery and partition/stage recovery; durable provider-response replay remains incomplete | Complete PR #144 response-checkpoint recovery path, then extend fault injection to dispatch relay failure, lease expiry, broker restart, storage partial write and reanalysis retries | No lost logical execution, no duplicate output, durable terminal/retry state across each failure window |
| AUD-006 | P0 | Code-level tenant controls documented; no production adversarial test evidence inspected | Execute two-tenant API/storage/report/export negative matrix | All cross-tenant attempts denied and logged without leakage |
| AUD-007 | P1 | Current artifact upload controls are bounded but deployment ingress, temporary-disk and persistent-capacity behavior remain unqualified | Reconcile deployment body limits, temporary storage, persistent object storage, concurrency and quotas | Measured load test and documented limits/alerts |
| AUD-008 | P1 | Resource qualification/approval has multiple moving parts and historical branch work | Validate source identity, integrity, qualification, approval, active binding, fallback and audit on one real resource per stage | End-to-end resource lifecycle evidence |
| AUD-009 | P1 | Historical validation documentation may lag current normalization/support code | Reconcile docs only after code-path and fixtures confirm actual behavior | Docs and tests agree on every supported variant class |
| AUD-010 | P1 | Production deployment configuration and restore process not independently verified | Capture revision/configuration inventory; run backup restore and rollback drill | Signed operations checklist with observed outcomes |
| AUD-011 | P1 | Current CI uses SQLite for main backend tests and a dedicated PostgreSQL integration target; live external provider execution is disabled in CI | Add hermetic provider contract tests and separately governed integration smoke tests | Deterministic CI plus protected secrets-based smoke-test workflow |
| AUD-012 | P2 | Broader interoperability and deployment profiles need customer-driven requirements | Define pilot customer requirements before implementing FHIR/VRS/on-prem expansion | Approved requirements and scope decisions |
| AUD-013 | P0 | PR #144 (`205427880326caacedc78ff641f3ccb6bc801c02`) addresses the failure window after a provider response is received and before annotation rows are persisted by checkpointing the exact response artifact with SHA-256 and resource/provider identity | Finish review; verify backend + PostgreSQL + frontend CI; if green, merge under the normal protected workflow; then qualify the same invariant with deployment-backed durable artifact storage | Green required CI, deterministic replay test, resource-release drift rejection, and durable artifact-store evidence |

## Dependency order

1. Finish and qualify the remaining annotation response-checkpoint failure window (#144).
2. Establish the complete variant-class truth table and deployment evidence.
3. Qualify resource preflight/runtime binding and the complete durable execution/recovery matrix.
4. Prove tenant/security boundaries and report authorization.
5. Run scientific benchmark and expert-reviewed discrepancies.
6. Close operational capacity, backup/restore, monitoring and incident gaps.
7. Run controlled live E2E on a pinned deployment and approve a restricted research pilot only after P0 exits.
8. Build broader deployment/interoperability capabilities from documented pilot needs.

Do not start a lower-priority feature while a P0 scientific, tenant, or recovery invariant remains unproven.

## Current checkpoint — 2026-10-10

- Verified `main` HEAD: `c91ed0e2fca9133dbd33f9365ce934221f1557c8`.
- Main CI run `38036686972`: success across backend, PostgreSQL integration and frontend.
- Open PR #144 is the dependency-ready implementation immediately ahead of live deployment qualification; its CI run `38036974027` was still in progress at the time of this checkpoint.
- No live production-like E2E, external-provider execution, adversarial tenant test, backup/restore drill, or clinical validation is claimed by this checkpoint.
