# Frontend-to-backend coverage audit and laboratory UX requirements

**Audit basis:** default-branch source at `a12f57728e9c371d7947f9fce346a8ae79cdb32f`, reviewed 2026-10-11. This is a source-level audit, not a live-deployment or browser E2E result.

## Design research and operating principles

The review uses public documentation from established genomics/laboratory products and published laboratory-information-system usability research:

- [Franklin Workbench documentation](https://help.genoox.com/en/articles/4277712-working-in-the-workbench) describes a case-centered view that brings sample/assay information, case details, QC, analysis results, variant evaluation and exports together.
- [SOPHiA DDM Genomics workflow](https://www.sophiagenetics.com/sophia-ddm-for-genomics/) organizes work around upload, analysis, prioritization, exploration/interpretation and reporting.
- [WHO EMRO laboratory information-system usability study](https://www.emro.who.int/emhj-volume-26-2020/volume-26-issue-12/compliance-with-design-principles-a-case-study-of-a-widely-used-laboratory-information-system.html) reports substantial usability problems in an evaluated LIS and supports explicit usability review rather than assuming that feature presence means good workflow usability.
- [Clinical laboratory information system implementation study](https://pmc.ncbi.nlm.nih.gov/articles/PMC6852617/) emphasizes role-specific worklists, status visibility, explicit handoffs and recovery from rejected or incomplete specimens.

SIRALOOM should adopt the useful interaction patterns without copying proprietary screens: a case-first worklist, a clear next action, concise status and error explanations, a case dossier with separate tabs/sections for input, analysis, variants, phenotype/family context, evidence, reports and provenance, and explicit role-gated review/sign-out. Scientific details and audit evidence should remain accessible but not dominate every screen.

## Source-level feature coverage

| Capability | Backend evidence | Frontend evidence on the audited default branch | Audit result |
|---|---|---|---|
| Case registry and case creation | `/cases`, specimen and artifact APIs | `frontend/app/(app)/app/cases/page.tsx` | Implemented in source; verify create/open/edit and authorization in deployed E2E. |
| VCF intake and artifact persistence | `backend/app/api/v1/artifacts.py`, artifact store implementations | Cases page and `frontend/app/(app)/app/workspace/page.tsx` | This branch adds a case-artifact inventory with download actions and recorded hash/build/validation metadata for every artifact returned by the API. The backend creates a normalized VCF plus index and per-batch annotation-provider response JSON artifacts. It does not currently produce one consolidated annotated VCF artifact; annotations are also persisted in database rows. Hash verification, access control and large-file behavior still require deployed tests. |
| Durable analysis and workflow state | `backend/app/api/v1/analyses.py`, workflow/domain modules, checkpoint and dispatch tests | Workspace polls analysis and renders workflow steps | This branch adds explicit WES/WGS GRCh38 and WES GRCh37 profile selection, passes the profile ID at analysis creation, surfaces the start/preflight response and persisted per-stage resource readiness/issues, and avoids saying “queued” when preflight blocks. Source tests do not prove crash recovery at every stage. |
| Preflight/resource plan | `preflight_analysis_resources`, `resource_profile_resolver.py`, persisted resource plan | Workspace can start an analysis; no dedicated preflight/resource-plan workbench was found | Remaining gap: show the immutable plan hash/version and an accurate deployment-backed capacity estimate; add recovery actions tied to specific blockers. The current UI exposes readiness/issue details but does not estimate capacity. |
| Resource registry | `backend/app/api/v1/resources.py`, registry, qualification and approval domain modules | No resource-management page was present in the audited tree | Gap addressed in this branch by adding `/app/resources`; live API integration remains to be verified. |
| Resource staging/acquisition | Domain modules `resource_staging.py` and `resource_remote_staging.py`; staging tests | No corresponding resource-staging REST router was found in `backend/app/main.py` or `backend/app/api/v1` | Backend/API gap: the new UI states this limitation and does not bypass qualification. A lab-facing staging API/orchestrator is still needed. |
| Resource profiles | `analysis_resource_profiles.py` defines WES/WGS GRCh38 and WES GRCh37 standard profiles | No profile-management or profile-selection screen was found | Gap: expose profile selection/inspection and per-profile organization-bound resource readiness; current branch shows the profiles known to this backend build. |
| Human variant review | Review, ACMG and workflow APIs; human-gate API and tests | `frontend/app/(app)/app/review/page.tsx` and workspace contain variant review actions | Variant-level review controls exist, and this branch adds a direct workspace path to the workflow-level human-gate API for steps in REQUIRES_REVIEW, including reason, expected attempt, changed-input declaration for retry, and refresh/re-poll after resolution. Still verify permissions, gate-specific acceptance constraints, persisted decisions and actual worker resume in deployed E2E. |
| Phenotype and family/segregation | `phenotypes.py`, `pedigree.py`, segregation/inheritance endpoints | Review page has phenotype, family, parent-child, segregation and inheritance sections | UI/API paths exist in source. Verify persistence, reloading, variant-specific use, evidence/provenance and report inclusion end to end. |
| Reports and sign-out | Reports, reportability and finalization APIs | `frontend/app/(app)/app/reports/page.tsx` and workspace | UI paths exist; verify report artifact identity, authorized sign-out, version lineage, PDF bytes and download. |
| Full variant export | Complete-variant report and case export APIs | Workspace shows full variant table/export state | Partial; test CSV/JSON output and file downloads using real persisted artifacts. |
| Provenance/audit | Audit API and resource/annotation/population/evidence/report provenance models | `frontend/app/(app)/app/audit/page.tsx` and workspace timeline | Basic audit viewer exists; completeness and immutability require scenario-based verification. |
| Reanalysis and notifications | `reanalysis.py`, notification and candidate endpoints | Reanalysis notifications are rendered in the variant workspace | Partial discoverability: no dedicated operations/notification center was found. Test resource-change notification, approve/reject, new analysis version and preservation of previous versions. |
| Organization membership | Auth/membership APIs | Settings page | Member administration exists; resource governance is not the same as membership settings. |
| Language selection | Centralized English/Arabic/bilingual catalog and homepage switcher | Before this branch, the language selector was only rendered by the public SiteShell on the homepage; AppShell had none | Gap addressed in this branch by adding a workspace language selector and resource-page translations. Verify RTL layout and persistence in browser tests. |
| Capacity and storage | Upload policy, storage health, upload smoke script | Settings reports health; no operator-facing capacity dashboard was found | Gap: show storage and capacity telemetry only when the deployment supplies trustworthy metrics. Do not infer capacity from an upload-size setting. |
| Laboratory deployment | Production Compose, deployment docs, health/readiness checks | Public website and workspace exist; frontend deploys separately | Not yet deployment-verified. Run installation, migrations, worker/broker/storage, authentication, upload, recovery and report sign-out on a real staging environment. |

## Resource Center added in this branch

- Adds `/app/resources` to the authenticated navigation.
- Adds resource registration as a candidate, status/type filters, qualification result inspection, approval requests, approval decisions with reason/version, activation requests, and visibility of the three built-in analysis profiles.
- Adds a workspace language switcher using the centralized locale catalog.
- Explicitly warns that the existing API does not expose staging/acquisition as a user-facing endpoint. Resource registration must not be represented as qualification or executable readiness.

## Large VCF files and capacity

No code or UI should promise support for arbitrary 5 GB/10 GB files based only on removing a 50 MB limit. A laboratory deployment must configure and measure ingress body limits, proxy and ASGI multipart temporary storage, application staging, persistent artifact storage, worker scratch, available disk/inodes, request/worker timeouts, database/queue capacity, and concurrency. The existing upload smoke test reports client-observed latency and throughput; it does not measure server-side peak temporary disk. Support for a specific file size should be stated only after the complete deployment passes a representative load/recovery test.

## Required next verification gates

1. Run frontend i18n validation, TypeScript and production build; run backend tests after API/UI integration changes.
2. Complete the resource staging API and a user-facing staging/preflight flow, with publisher allow-list, checksum, size limit, disk preflight, organization storage boundary and retryable failure states.
3. Add a case worklist and case detail information architecture that makes the case the permanent root, with explicit tabs for overview, files, analysis, variants, phenotype/family, evidence/review, reports and audit.
4. Trace every workflow-level human gate from visible pending task through authorization, decision persistence, resumed execution and final report.
5. Test English, Arabic/RTL and bilingual modes across public pages, login/onboarding and every protected workspace route.
6. Execute a deployed end-to-end test with a non-sensitive VCF and registered, qualified, approved, organization-bound resources. Record artifact hashes and generated report IDs.
7. Run a measured upload/recovery test on disposable staging cases and execute a properly configured GIAB benchmark before making any scientific-concordance claim.

**Release rule:** a route, component, unit test or implementation report is not proof of a completed laboratory workflow. Mark each requirement PASS only after its intended integration test has passed and retain the run evidence.
