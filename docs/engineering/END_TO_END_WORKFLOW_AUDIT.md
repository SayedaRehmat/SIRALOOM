# SIRALOOM — End-to-End Workflow Audit

Baseline: `2efbe032e0320c717b00a6724b1022bf76621c77`.

This matrix records the actual implementation boundaries inspected in the repository. `PASS` means source/test evidence is sufficient for the stated property; `PARTIAL`, `NOT TESTED`, and `BLOCKED` are intentionally retained where live or broader evidence is missing.

| Stage | User action | Frontend boundary | API / backend boundary | Persistence / worker effect | Authorization | Result |
|---|---|---|---|---|---|---|
| 1. Account / identity | Sign up, activate, login, logout | `frontend/app/(public)` and authenticated application group | `backend/app/api/v1/auth.py`; principal resolution in `backend/app/auth/principal.py` | Identity/session state; organization membership | Server-resolved principal | PARTIAL — source inspected; no captured deployed signup/verification/session-expiry run |
| 2. Organization / tenant | Enter or switch laboratory workspace | `frontend/app/(app)` | membership/organization routes under `backend/app/api/v1`; `get_accessible_case()` / `get_accessible_analysis()` in `backend/app/auth/authorization.py` | Organization membership and case-owned resources | `require_case_tenant()` from trusted principal | PARTIAL — route authorization coverage exists; cross-tenant live denial is not captured |
| 3. Dashboard / navigation | Open workspace, worklists and operational views | `frontend/app/(app)` | case/analysis/review/report/resource APIs | Reads current persisted records | Protected application routes | PARTIAL — source and CI reviewed; deployed workflow not verified |
| 4. Case lifecycle | Create/open/update/reopen case and specimen | `backend/app/api/v1/cases.py` | case and specimen route handlers | Case remains organization-rooted; audit events persist consequential changes | Case tenant + role checks | PARTIAL — automated coverage exists; concurrent live-user behavior not tested |
| 5. VCF intake | Upload VCF/index and inspect validation | `frontend/app/(app)` | `backend/app/api/v1/artifacts.py` | Durable `Artifact` rows and file-backed/cloud artifact identity; SHA-256; validation status | `require_case_tenant()` + write roles | PARTIAL — source/automated validation inspected; live upload/network interruption test blocked |
| 6. Analysis orchestration | Start/monitor/cancel/resume analysis | `frontend/app/(app)` analysis workspace | `backend/app/api/v1/analyses.py`; `backend/app/workflows/variant.py`; `backend/app/infrastructure/queue/celery_app.py` | `Analysis`, `WorkflowStep`, `AnalysisPartition`, dispatch/outbox state | Accessible analysis; durable dispatch identity; worker fences | PARTIAL — durable state/fencing is implemented; full stage-body crash/replay remains open |
| 7. Annotation / population / evidence | Observe scientific-stage outputs | analysis workspace | `backend/app/workflows/variant.py`; `backend/app/api/v1/evidence.py`; `backend/app/api/v1/evidence_context.py` | Annotation, population observations, evidence, resource execution/provenance | Analysis tenant inherited by API; worker scope remains under audit | PARTIAL — missing-resource semantics and provenance are tested; live provider execution not qualified |
| 8. Human review | Review evidence, ACMG state, approve/request more evidence | review workspace under `frontend/app/(app)` | `backend/app/api/v1/review.py`; `backend/app/api/v1/acmg.py`; review service | Versioned classifications/criteria/review decisions + audit | Review roles + accessible analysis | PARTIAL — review state machine is implemented; deployed end-to-end human review not captured |
| 9. Reportability / report | Finalize reportability and generate report | report workspace under `frontend/app/(app)` | report/reportability API modules under `backend/app/api/v1`; reporting services | Immutable report versions/artifacts and supersession lineage | Finalization roles + analysis/case access | PARTIAL — artifact replay safeguards exist; live report generation/download not qualified |
| 10. Approval / sign-out | Approve and sign out a final report | review/report workspace | reportability/sign-out handlers and reporting services | Sign-out decision, report version, audit linkage | Backend finalization guards | BLOCKED — no captured deployed sign-out evidence; electronic-signature/regulatory compliance is not claimed |
| 11. Audit / provenance | Inspect history/export | audit/provenance workspace | `backend/app/api/v1/audit.py` and export/provenance services | Durable audit events, artifact/resource/software lineage | Tenant-scoped access | PARTIAL — provenance domains exist; full live export verification is pending |
| 12. Reanalysis | Review change candidate and create child analysis | reanalysis/resource workspace under `frontend/app/(app)` | reanalysis domain/services + resource discovery/staging tasks in `backend/app/infrastructure/queue/celery_app.py`; `scripts/compare_reanalysis_outputs.py` | Parent/child lineage, resource snapshots, change candidates and notifications | Organization-scoped reanalysis records | PARTIAL — resource pinning and comparison CLI exist; real lab parent/child comparison is not run |
| 13. Logout / revocation | Logout and return to public surface | `frontend/app/(public)` | `backend/app/api/v1/auth.py` and principal/session handling | Session/token revocation where configured | Server authentication boundary | BLOCKED LIVE — no captured deployed logout/session-revocation/back-button test |

## Cross-cutting observations

### API contracts
Backend route authentication coverage is explicitly tested by `tests/test_api_route_authentication_coverage.py`. Evidence and artifact endpoints also perform analysis/case tenant checks in the handler layer.

### Database integrity
The current workflow uses versioned rows for classifications/reports/reanalysis and durable workflow checkpoints. PostgreSQL locking is used for execution ownership in `backend/app/infrastructure/queue/celery_app.py`. Production concurrency evidence still requires the PostgreSQL integration suite plus deployed failure injection.

### Reliability
Late acknowledgements, worker-loss rejection, durable dispatch generations, partition lease fencing, bounded retry behavior and replay-safe report artifact persistence are present. The open stage-body recovery work is the remaining material verification gap.

### Frontend
The frontend is organized as Next.js route groups `frontend/app/(public)` and `frontend/app/(app)`. The repository explicitly states that a real production build must be executed in CI/deployment; local dependency installation was previously environment-blocked.

## Audit conclusion

The software contains substantially more than a screen-level prototype: the case, artifact, workflow, evidence, review, reporting, audit and reanalysis domains are connected in the backend. However, Phase 1 cannot be marked complete until the remaining authorization, stage-body replay, deployed end-to-end, storage/restore and scientific benchmark evidence is captured.
