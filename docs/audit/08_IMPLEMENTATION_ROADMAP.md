# Prioritized implementation roadmap and defect register

Priority definitions: **P0** blocks safe external pilot; **P1** material release risk; **P2** needed for broader production scale; **P3** improvement. Priorities reflect current evidence and must be revised when live validation yields new findings.

| ID | Priority | Finding / evidence | Required next action | Exit evidence |
|---|---|---|---|---|
| AUD-001 | P0 | No verified live E2E run in inspected release docs; acceptance matrix marks E2E and deployment NOT VALIDATED | Run the documented public benchmark smoke test on a controlled deployment and capture complete provenance | Reproducible case-to-export dossier on a pinned revision |
| AUD-002 | P0 | Independent scientific concordance and ACMG/ClinGen correctness remain unvalidated in repo docs | Freeze supported variant/provider scope; create golden fixtures and independent expected outputs | Reviewed discrepancy report and approved acceptance criteria |
| AUD-003 | P0 | Variant-support statements conflict: strict validator/tool code and older validation documentation differ on multiallelic/SV scope | Trace exact intake→normalization→annotation→report behavior and publish support matrix | Per-class automated fixtures; unsupported variants fail visibly |
| AUD-004 | P0 | PR #134 attempts to make runtime use the exact preflight-selected resources, but its first CI run failed: 11 backend tests and 2 PostgreSQL integration tests. Failures include missing resource_deployment_profiles in an SQLite fixture, mock principal/child fields, and dispatch integration fixtures lacking an explicit trial profile. PR #84 also remains open with no workflow run found for its latest head | Fix fixtures without weakening laboratory resource-profile enforcement; rerun full backend and PostgreSQL integration CI; then qualify real API preflight and worker start/recovery matrix | CI evidence for ready, optional-limited, required-blocked, recovery and no-duplicate dispatch |
| AUD-005 | P0 | Worker/queue recovery logic exists but live infrastructure failure matrix not evidenced | Inject worker loss after claim, relay failure, lease expiry, broker restart and orphaned dispatch in PostgreSQL/Redis tests | No lost logical execution, no duplicate output, durable terminal/retry state |
| AUD-006 | P0 | Code-level tenant controls documented; no production adversarial test evidence inspected | Execute two-tenant API/storage/report/export negative matrix | All cross-tenant attempts denied and logged without leakage |
| AUD-007 | P1 | Open PR #78 upload ceiling change; current docs warn multipart temporary storage can exhaust disk | Reconcile merged main policy with PR; enforce coordinated ingress, temp disk, persistent capacity and quotas | Measured load test and documented limits/alerts |
| AUD-008 | P1 | Resource qualification/approval has multiple moving parts and historical branch work | Validate source identity, integrity, qualification, approval, active binding, fallback and audit on one real resource per stage | End-to-end resource lifecycle evidence |
| AUD-009 | P1 | `docs/validation/phase1-status.md` appears stale relative to recent normalization changes | Update docs only after code-path and fixtures confirm actual behavior | Docs and tests agree on every supported variant class |
| AUD-010 | P1 | Production deployment configuration and restore process not independently verified | Capture revision/configuration inventory; run backup restore and rollback drill | Signed operations checklist with observed outcomes |
| AUD-011 | P1 | Current CI uses SQLite for main backend tests and a dedicated PostgreSQL integration target; live external provider execution is disabled in CI | Add hermetic provider contract tests and separately governed integration smoke tests | Deterministic CI plus protected secrets-based smoke-test workflow |
| AUD-012 | P2 | Broader interoperability and deployment profiles need customer-driven requirements | Define pilot customer requirements before implementing FHIR/VRS/on-prem expansion | Approved requirements and scope decisions |

## Dependency order

1. Establish variant-class truth table and deployment evidence.
2. Qualify resource preflight/runtime binding and durable execution/recovery.
3. Prove tenant/security boundaries and report authorization.
4. Run scientific benchmark and expert-reviewed discrepancies.
5. Close operational capacity, backup/restore, monitoring and incident gaps.
6. Approve restricted research pilot only after P0 exits.
7. Build broader deployment/interoperability capabilities from documented pilot needs.

Do not start a lower-priority feature while a P0 scientific, tenant, or recovery invariant remains unproven.
