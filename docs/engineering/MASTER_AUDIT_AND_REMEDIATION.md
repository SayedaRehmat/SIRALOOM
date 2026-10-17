# SIRALOOM Master Audit and Remediation

**Updated:** 2026-10-17
**Latest pushed baseline:** `main` commit `9d14ef7` (`Fix clinical governance and QC persistence`); GitHub Actions run [#1583](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39021934019) succeeded across backend (**878 passed, 24 skipped**), PostgreSQL/Celery integration, frontend behavior/build/container, and Compose validation. Local backend verification remains unavailable because this Windows runtime has no usable Python interpreter; the prior full local suite was 805 passed, 37 skipped, and one WeasyPrint native dependency failure. A local follow-up validates governance status enums and awaits CI. The pre-existing untracked backup artifact remains untouched.
**Working tree note:** an unrelated pre-existing untracked backup artifact is present; it has been preserved.
**Scope:** Phase 1 account-to-signout product workflow audit and repair.
**Overall status:** IN PROGRESS — do not treat Phase 1 as complete or the product as clinically/production ready.

## 2026-10-17 continuation checkpoint — case-export recovery verified

## 2026-10-17 case phenotype lineage checkpoint

- **Finding:** `GET /cases/{case_id}/phenotypes` authorized the requested case and filtered observations by `case_id`, but returned each row's optional `analysis_id` without verifying that the analysis belonged to that case. An inconsistent persisted link could attach unrelated analysis context to a case phenotype response.
- **Correction:** `backend/app/api/v1/phenotypes.py::list_case_phenotypes` now rejects missing or cross-case linked analyses with 409 before serialization.
- **Regression coverage:** `test_case_phenotype_list_rejects_analysis_from_another_case` seeds an authorized case observation linked to another case's analysis and asserts fail-closed behavior.
- **Verification:** Python `compileall` and `git diff --check` passed before push. Local pytest is unavailable (`No module named pytest`); GitHub Actions #1579 succeeded for the pushed regression.
- **Status:** pushed in `a8ccc3f`; CI #1579 succeeded. Phase A remains PARTIAL. CI #1578 also succeeded for the preceding assay-tenant change.
- **Next action:** continue direct-object API and worker-boundary audit plus integrated reviewer-to-signout/recovery acceptance.

## 2026-10-17 quality-assay tenant lineage checkpoint

- **Finding:** `GET /analyses/{analysis_id}/quality` authorized the analysis, then serialized `analysis.assay_id` without checking that the referenced assay belonged to the caller's organization. The quality-assessment write endpoint already rejects a foreign assay, but the read endpoint could disclose its profile name/configuration from an inconsistent persisted link.
- **Correction:** `backend/app/api/v1/quality.py::get_quality` now fails closed with 409 before returning the assay when its organization differs from the principal's.
- **Regression coverage:** `test_quality_read_rejects_analysis_assay_from_another_tenant` injects the cross-tenant assay relation and asserts no response is produced.
- **Verification:** Python `compileall` and `git diff --check` passed before commit. Local pytest is unavailable (`No module named pytest`); GitHub Actions #1578 completed successfully for this change.
- **Status:** pushed in `81a604c`; CI #1578 succeeded. Phase A remains PARTIAL. CI #1577 for notification/secondary-finding checks also succeeded.
- **Next action:** await CI verification for the two pushed batches while continuing the direct-object and integrated review/signout recovery audit.

## 2026-10-17 notification and direct-object lineage checkpoint

- **Confirmed CI:** run #1576 completed successfully for `fcd0efe` on `main`.
- **Findings:** the notifications endpoint scopes rows to the current organization and user but previously serialized case, analysis, candidate, and discovered-resource references without checking their ownership/lineage. The secondary-finding list authorized its analysis but trusted each stored variant link when serializing decisions.
- **Corrections:** `backend/app/api/v1/reanalysis.py` now validates notification case/analysis/candidate ownership and consistency and permits a discovered resource only when it is shared or owned by the notification tenant; inconsistent rows return 409 without exposing the referenced objects. `backend/app/api/v1/clinical_followup.py` now validates every secondary-finding variant against the authorized analysis before serialization.
- **Regression coverage:** parametrized notification tests cover foreign case, mismatched case/analysis, cross-case candidate, foreign resource tenant, and a discovery linked to another resource. A secondary-finding list test verifies out-of-analysis variants are rejected.
- **Verification:** Python `compileall` passed for changed Python files. Local focused pytest could not start because the bundled interpreter reports `No module named pytest`; `git diff --check` is recorded after the patch. Push-triggered CI is required to execute the regression tests.
- **Status:** implementation is in progress and Phase A remains PARTIAL. CI #1576 confirms only the prior commit; it does not verify this change.
- **Next action:** inspect remaining direct-ID APIs and worker entrypoints; then continue integrated reviewer-to-signout, notification delivery, and failure recovery. Live Firebase/browser and deployed two-tenant verification still require configured infrastructure and test identities.

## 2026-10-17 continuation checkpoint — global variant detail lineage

- **Finding:** `GET /variants/{variant_id}` chose the latest tenant-owned annotation and then returned analysis-scoped populations, evidence, ACMG assessments, and classifications without verifying that the requested variant belonged to the selected analysis. Corrupt or inconsistent lineage could therefore produce a response assembled for a variant outside the selected analysis.
- **Correction:** `backend/app/api/v1/variants.py` now resolves the selected analysis and checks variant membership using the shared `get_analysis_variant` guard before loading any analysis-scoped result rows; non-members receive the same 404 as a missing variant.
- **Regression coverage:** `tests/test_audit_tenant_authorization.py::test_variant_details_require_analysis_membership` injects a non-member and asserts a not-found response.
- **Verification:** authorization, review, tenant-object, and population route suites: 58 passed. Focused regression file after import cleanup: 12 passed. `git diff --check` passed. Ruff reports pre-existing dependency-default and loop-capture findings in these files; the newly introduced unused imports were removed.
- **Status:** locally verified; this batch is not yet pushed and has no CI result. Phase A remains PARTIAL.
- **Next action:** continue direct-ID route audit across every analysis-scoped API and background entrypoint, then proceed through remaining signup-to-signout and recovery acceptance gaps.

## 2026-10-17 evidence-to-variant lineage check

- **Finding:** evidence reads verified tenant access through `analysis_id`, but did not check that the evidence row's `variant_id` was part of that analysis. The list response could also serialize inconsistent evidence rows.
- **Correction:** `backend/app/api/v1/evidence.py` now validates the variant lineage on direct reads (using indistinguishable 404 for absent, foreign, or mismatched records) and refuses to return an analysis evidence list containing mismatched variant links (409).
- **Regression coverage:** `tests/test_audit_tenant_authorization.py::test_evidence_endpoint_hides_variant_outside_analysis` covers direct read rejection.
- **Verification:** evidence binding, tenant-route, review, and object-authorization suites: 50 passed; `git diff --check` passed. Commit `2592a95` was pushed directly to `main`; its GitHub Actions run #1566 is in progress. No CI result exists yet for this local evidence-lineage change.
- **Status:** fix committed and pushed in `818da15`; GitHub Actions run #1567 in progress. Phase A remains PARTIAL.
- **Next action:** continue analysis-scoped direct-ID and list-response lineage checks, then complete remaining A1–A10 journey and recovery acceptance requirements.

## 2026-10-17 reanalysis candidate lineage check

- **Finding:** candidate execution authorized the parent analysis by tenant but trusted the candidate's independent case link and any pre-linked child analysis. Inconsistent rows could cause a reanalysis request to return or dispatch a child associated with a different case or parent.
- **Correction:** `backend/app/api/v1/reanalysis.py` now fails closed with 409 when the candidate case does not match the authorized parent, or when an existing child does not match both the parent case and `parent_analysis_id`. Checks run before child status reuse, resource preflight, or task dispatch.
- **Regression coverage:** `tests/test_reanalysis_api_contract.py` injects each mismatched candidate-case, child-case, and child-parent relationship and asserts rejection before enqueue.
- **Verification:** reanalysis API, reanalysis workflow/completion, case-change reanalysis, resource snapshot, and discovery suites: 34 passed; `git diff --check` passed. Latest main CI runs #1566–#1568 all succeeded.
- **Status:** locally verified; this batch is not yet pushed. Phase A remains PARTIAL.
- **Next action:** inspect notification/candidate list lineage and remaining direct-object APIs, then continue reviewer-to-signout and end-to-end recovery acceptance.

## 2026-10-17 resource approval qualification lineage

- **Finding:** resource adoption decision verified that the referenced qualification was marked `QUALIFIED` but did not verify that the qualification belonged to the resource on the approval row. An inconsistent approval link could therefore authorize a resource based on another resource's technical qualification.
- **Correction:** `backend/app/domain/resources.py::decide_resource_approval` now requires the qualification's `resource_id` to match the approval's resource before changing approval status or creating/updating a tenant resource binding.
- **Regression coverage:** `tests/test_resource_registry.py::test_resource_approval_cannot_use_another_resources_qualification` injects a cross-resource qualification link and verifies rejection leaves the approval pending and creates no binding.
- **Verification:** resource registry and adoption provenance suites: 18 passed; `git diff --check` passed. Candidate lineage batch also passed 34 related tests and is pushed in `0b77752`; its CI run #1569 is in progress.
- **Status:** resource fix verified locally, pending commit/push. Phase A remains PARTIAL.
- **Next action:** finish notification/candidate list lineage and remaining direct-object APIs, then perform cross-tenant and end-to-end workflow verification where configured dependencies are available.

## 2026-10-17 reanalysis candidate list lineage

- **Finding:** the candidate list was scoped only by its denormalized `organization_id`, then returned its case and analysis IDs without confirming the case's tenant, parent analysis case, or linked child lineage. Corrupt rows could send the UI to unrelated or inconsistent case/analysis context.
- **Correction:** `backend/app/api/v1/reanalysis.py::list_candidates` joins the case and parent analysis, filters both to the requesting organization and matching case, and includes a linked child only when its case and parent match. Invalid rows are omitted from the candidate work list.
- **Regression coverage:** `tests/test_reanalysis_api_contract.py::test_candidate_list_excludes_cross_case_and_cross_parent_lineage` seeds valid and mismatched candidate rows in SQLite and verifies only the coherent candidate is returned.
- **Verification:** reanalysis API + resource registry + adoption provenance suites: 36 passed; `git diff --check` passed. Candidate execution lineage CI run #1569 passed. Resource qualification linkage CI run #1570 remains in progress.
- **Status:** candidate-list fix locally verified; pending commit/push. Phase A remains PARTIAL.
- **Next action:** audit notification-to-case/candidate/resource lineage and continue remaining direct-object APIs, then verify the full reviewer-to-signout journey and failure-recovery requirements.

## 2026-10-17 signup/session, signout, report, and recovery regression pass

- **Scope exercised:** auth foundation/onboarding, invitation and membership lifecycle, report signout/resume and serialization ordering, failure-recovery contracts, worker-loss recovery matrix, and frontend session destination/signout/workspace identity behavior.
- **Verification:** backend focused suites: 58 passed. Frontend Node tests (`signout`, `session-destination`, `workspace-context`): 13 passed. One Starlette/httpx deprecation warning was emitted by the Python test runtime. These are code-level contract tests, not live Firebase/browser e2e sessions.
- **CI:** resource qualification ownership commit `7f688b1` passed run #1570; candidate-list commit `d2267fe` run #1571 remains in progress.
- **Status:** source/test verification for these contracts passed; Phase A remains PARTIAL because no configured Firebase identity, interactive browser E2E, deployed two-tenant lab, or full report signout journey has been exercised.
- **Next action:** continue notification lineage and direct object route review; run live auth/tenant journey only when configured test identity and deployment are available, then exercise reviewer-to-authorized-report signout and recovery against the integrated stack.

## 2026-10-17 full-suite verification checkpoint

- **Backend:** full `pytest tests -q`: 805 passed, 37 skipped, 1 failed in 47.99s. The sole failure is `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`: this Windows runtime cannot load native `libgobject-2.0-0`, required by WeasyPrint. PDF render therefore remains unverified locally; CI/container or supported Linux execution evidence is required.
- **Frontend:** `npm run test:session`: 20 passed. `npm run build` passed the i18n architecture guard, then could not run `next build` because the `next` executable is absent from this checkout. No production build claim is made locally.
- **CI:** candidate-list commit `d2267fe` passed run #1571; ledger-only commit `7e37b12` run #1572 is in progress.
- **Status:** suite evidence recorded; these results do not establish browser E2E, PDF correctness, clinical validation, or Phase A completion.
- **Next action:** continue notification and remaining API lineage audit; use the CI production build and PDF-render-capable environment as actual evidence when available, then perform integrated review/signout and failure recovery journeys.

## 2026-10-17 pedigree observation lineage and interpretation guard

- **Finding:** segregation reads used analysis/variant-scoped rows but serialized observations even when `pedigree_member_id` referred to a member outside the analysis case. Inheritance assessment silently filtered those rows from its input, potentially presenting a result computed from an incomplete family observation set without identifying the inconsistency.
- **Correction:** `backend/app/api/v1/pedigree.py` now fails closed with 409 on both segregation reads and inheritance assessment whenever a stored observation's member is not in that analysis case.
- **Regression coverage:** `tests/test_audit_tenant_authorization.py::test_segregation_lineage_rejects_member_from_another_case` exercises both endpoints and asserts no partial inheritance result is returned.
- **Verification:** authorization, analysis-variant access, mutation role, review, and pedigree/inheritance suites: 54 passed; `git diff --check` passed. CI #1570–#1572 passed; #1573 is in progress.
- **Status:** local fix verified, pending commit/push. Phase A remains PARTIAL.
- **Next action:** continue notification lineage and direct-object API inventory; then demonstrate the complete reviewer-to-authorized-signout journey and failure recovery against configured integration services.

## 2026-10-17 pedigree dossier relationship/specimen lineage

- **Finding:** pedigree dossier reads trusted `PedigreeMember.case_id` and `PedigreeRelationship.case_id` filters, but did not verify a member's linked specimen belonged to the same case or that relationship endpoints referred to members in the returned case. The write route already enforces these links; malformed persisted rows could still be presented on read.
- **Correction:** `backend/app/api/v1/pedigree.py` now checks all relationship member IDs against the case's loaded member set and loads/validates each linked specimen before returning the dossier. Mismatches fail closed with 409.
- **Regression coverage:** `tests/test_audit_tenant_authorization.py::test_pedigree_dossier_rejects_cross_case_links` covers foreign relationship endpoints and cross-case specimen linkage.
- **Verification:** focused authorization, analysis variant access, role mutation, and pedigree/inheritance suites: 31 passed; `git diff --check` passed. Previous pedigree observation batch is pushed as `a5c61c6`; CI #1574 is in progress.
- **Status:** locally verified; pending commit/push. Phase A remains PARTIAL.
- **Next action:** continue notification and remaining direct-object lineage audit, then verify reviewer-to-signout and recovery against integrated services.

## 2026-10-17 report-list case lineage (local checkpoint)

- **Finding:** the analysis report-list route authorized the analysis and filtered reports by `analysis_id`, but serialized each report's redundant `case_id` without confirming it matched the authorized analysis. Single-report reads already enforce this link through `get_accessible_report`; list reads did not.
- **Correction:** `backend/app/api/v1/reports.py::list_reports` now returns 409 if any linked report has a different case, rather than returning inconsistent case/report metadata.
- **Regression coverage:** added `test_report_list_rejects_case_link_different_from_analysis` in `tests/test_audit_tenant_authorization.py`.
- **Verification status:** `compileall` and `git diff --check` passed. The current bundled Python executable no longer contains pytest or ruff in `site-packages`, although it remains executable; focused pytest could not be rerun after that runtime change. Prior full suite was 805 passed, 37 skipped, and one environment-dependent WeasyPrint failure. This regression therefore awaits CI verification.
- **Status:** implementation and regression are pending commit/push; do not mark verified until CI runs. Phase A remains PARTIAL.
- **Next action:** push this small fix and inspect its CI result, restore a repository-supported test runtime if available, then continue direct-object inventory and notification lineage.

- **Current repository:** `main` at `4c43ad953a48e7360b1371d5ef79ad513143b01a`, matching `origin/main`; unrelated pre-existing untracked backup artifact preserved.
- **Latest validation:** GitHub Actions run [#1559](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/39014895300) succeeded in backend, PostgreSQL/Celery integration, and frontend jobs. The workflow includes frontend behavior tests, production build/container, Compose validation, DB migrations and real worker-loss integration.
- **Current code batch:** case-export cloud artifact packaging/download integrity and compensation on failed persistence are pushed; locally focused export suite: 17 passed. Earlier authorization changes (analysis/case artifact linkage and administrator-only member roster) are also pushed and covered by focused tests.
- **Phase A status:** NOT COMPLETE. The stage matrix remains PARTIAL. CI success verifies the committed test suite only; configured Firebase/browser sign-up-to-signout, live two-tenant behavior, end-to-end reviewer/report signout, and deployed lab infrastructure remain unexercised.
- **Next implementation action:** resume the API object-authorization inventory from the nested reportability, report, case-export, and worker entrypoints; add regression tests for confirmed linkage/tenant defects. Then continue the outstanding A1–A10 journeys and recovery cases. Do not switch to Phase B/C or declare readiness before Phase A gate evidence is complete.

## 2026-10-17 reportability linkage authorization batch (local, pending push)

- **Finding:** reportability listing and signoff trusted a decision's `analysis_id` without verifying that its `variant_id` belongs to that analysis. Existing finalization validates the linked classification but does not establish analysis membership for the variant. Inconsistent/corrupted cross-links could therefore be presented or approved as analysis-scoped decisions.
- **Correction:** `backend/app/api/v1/reports.py` now validates decision variant membership through the shared `get_analysis_variant` guard on both listing and signoff; inconsistent records fail closed with HTTP 409.
- **Regression coverage:** `tests/test_audit_tenant_authorization.py` covers both listing and signoff with a variant outside the analysis.
- **Verification:** focused reportability/report/auth suite: 39 passed; Python compileall passed for the changed route; `git diff --check` passed. A Starlette/httpx deprecation warning is emitted by the test runtime.
- **Status:** fixed in `2041fcb`; GitHub Actions run #1561 passed all three jobs. Phase A remains PARTIAL.
- **Next action:** continue nested report and clinical-governance link audit, then complete the remaining A1–A10 journey and failure-recovery checks.

## 2026-10-17 nested artifact lineage batch (local, pending push)

- **Finding:** case export selected `Artifact` rows by `case_id` and copied their bytes without verifying that a non-null `analysis_id` belonged to that same case. A malformed row could cause a tenant-authorized export to include another case's artifact bytes.
- **Correction:** `backend/app/reporting/export_service.py` validates every case artifact's analysis linkage before creating the manifest or packaging bytes. An inconsistent link fails the export with `CaseExportError`; no artifact bytes are read or packaged.
- **Regression coverage:** `tests/test_case_export.py::test_case_export_rejects_artifact_linked_to_another_cases_analysis` creates a foreign-tenant analysis linked from a local case artifact and confirms fail-closed export behavior.
- **Verification:** case export build, cloud/local download integrity, compensation, error redaction and dispatch tests: 19 passed; `git diff --check` passed.
- **Status:** code and regression pass locally; push-triggered CI pending. Phase A remains PARTIAL.
- **Next action:** resume direct object-linkage inventory for clinical-governance and worker exports; verify the newly pushed reportability check's frontend job, then continue the remaining A1–A10 workflows and failure injection.

## 2026-10-17 clinical follow-up lineage batch (local, pending push)

- **Finding:** clinical follow-up rows store both `case_id` and `analysis_id`. The update path authorized only through the analysis and then returned/mutated the row without proving its case matched that analysis; the governance dossier also serialized follow-up rows without checking the redundant case link.
- **Correction:** `backend/app/api/v1/clinical_followup.py` rejects inconsistent case/analysis links with HTTP 409 on dossier reads and updates; updates also verify any linked variant is in the analysis before mutation.
- **Regression coverage:** `tests/test_audit_tenant_authorization.py::test_followup_update_rejects_case_mismatch_with_its_analysis`.
- **Verification:** clinical governance/mutation and object-authorization suites: 24 passed; `git diff --check` passed.
- **Status:** locally verified; push-triggered CI pending. Phase A remains PARTIAL.
- **Next action:** continue validating worker-owned query scope and case-export payload lineage; complete the remaining signup-to-signout workflow checks and deterministic failure-injection cases.

## 2026-10-17 review-service variant authorization batch (local, pending push)

- **Finding:** review bundle and manual-classification service fetched a global `Variant` by ID without proving membership in the requested analysis. Other review mutations similarly relied on matching classification/assessment rows but did not consistently verify membership at the reusable service boundary.
- **Correction:** `backend/app/review/service.py` now uses the shared `get_analysis_variant` authorization helper in the review bundle, manual proposal, review start, criterion mutation, approval, and more-evidence request paths. Foreign analysis variants fail as a domain `ReviewError` before any review mutation.
- **Regression coverage:** `tests/test_review_workflow.py` records normalize-manifest membership in its valid fixture and verifies both dossier reads and manual proposals reject globally existing variants absent from the analysis.
- **Verification:** review workflow, queue, signout integration, and route mutation tenant tests: 47 passed; changed service import lint and compileall passed; `git diff --check` passed.
- **Status:** locally verified; push-triggered CI pending. Phase A remains PARTIAL.
- **Next action:** audit review queue/criterion lineage and the rest of clinical governance; then continue user-journey and failure-recovery verification from signup through signout.

## 2026-10-17 clinical governance and context-evidence lineage batch (local, pending push)

- **Finding:** the clinical-governance dossier selected confirmation and secondary-finding histories by analysis/variant but did not check row variant linkage; the context-evidence write route only inferred variant membership from an annotation row rather than the shared normalization/analysis membership policy.
- **Correction:** `backend/app/api/v1/clinical_followup.py` validates record variant linkage in returned histories (and the follow-up case linkage remains checked); `backend/app/api/v1/evidence_context.py` now calls `get_analysis_variant` before writing human context evidence.
- **Verification:** combined object-authorization, review, clinical-governance, report-signout, evidence, and route mutation suites: 65 passed. Import lint and Python compileall passed for changed routes/services; `git diff --check` passed.
- **Status:** locally verified, pending push; Phase A remains PARTIAL.
- **Next action:** add explicit route regressions for confirmation/secondary-finding malformed row links and context-evidence nonmember IDs; then continue audit of review queue and every analysis-scoped API and complete signup-to-signout recovery evidence.

## Verified current batch

| Finding | Root cause | Correction | Evidence | Status |
|---|---|---|---|---|
| Case readiness was overwritten by each VCF upload. | `backend/app/api/v1/artifacts.py` assigned status from only the latest primary VCF and could therefore hide a valid earlier VCF or reset a later lifecycle state. | Added `case_status_after_vcf_upload` and derive intake readiness from all persisted primary VCF validations; preserve statuses outside the intake lifecycle. | Focused intake/artifact/input tests: 32 passed using bundled Python runtime. | FIXED locally; CI and route-level verification pending |
| Supported BGZF VCF files were rejected during record parsing. | Filename classification and header inspection accepted `.vcf.bgz`, but `domain/vcf.py::open_text` passed it to plain text `open()` instead of gzip decoding. | Parse `.bgz` through the gzip reader and add a compressed-content regression. | Intake suite including BGZF regression: 33 backend tests passed; run #1549 backend job passed. | FIXED; frontend build for the same commit failed for a missing TS declaration, corrected locally |
| Invalid uploads appeared ready for analysis in the workspace. | The upload page stored every returned artifact ID and displayed success even when the API returned `validation_status=INVALID`; selecting a replacement file also retained the previous artifact ID. | Gate the startable artifact ID on both persisted and detailed validation status, clear it when file selection changes, show backend validation errors and warnings, and expose `.vcf.bgz` in the file picker. | Frontend behavior tests: 18 passed; localization guard passed; run #1549 production build failed on absent helper declaration. | Behavior fixed; declaration correction pending CI |
| Rejected replacement uploads displaced a still-valid selected VCF in the case wizard; new valid VCFs could retain a previously paired index. | The wizard unconditionally selected each new upload and kept the index state independently. | Keep a valid current primary when a replacement is invalid, select valid replacements, and clear index state and selected index file when the primary changes. Surface backend validation diagnostics in the wizard. | Frontend behavior suite: 18 passed; localization guard passed. | FIXED and pushed in `082dbd7`; CI pending |
| Report draft upload could leave an orphaned PDF after a failed database commit. | The report route wrote artifact bytes before committing the report/artifact rows, but handled only integrity conflicts and did not verify/delete stored bytes on failure. | Added shared commit compensation: on commit errors roll back, read the artifact row in a fresh DB session, and delete bytes only if absence is confirmed; preserve bytes when commit outcome is uncertain or durable. Applied to draft report creation. | Artifact compensation, report route commit-failure, finalization and replay tests: 16 passed; compileall passed. | FIXED locally; CI pending |
| Onboarding and invitation account-switch signout could reject without user feedback. | Those buttons chained `signOut().then(...)` with no rejection handler outside the protected shell; both screens also passed nullable Firebase auth without retaining TypeScript narrowing in the callback. | Added a shared signout attempt boundary, localized failure feedback, disabled duplicate actions while pending, and narrow the auth value before use. | Frontend behavior tests: 20 passed; localization guard passed; signout helper tests: 2 passed. | Behavior fixed; production build retest pending |
| Signed report bytes could be orphaned when signout failed after upload. | The signed PDF is stored before report/audit flush and the route's later commit or durable resume-intent commit; these errors previously had no storage compensation. | Derive the deterministic signed artifact identity and canonical URI before finalization; on any failed finalization/commit path roll back, verify artifact-row absence from a fresh session, then remove bytes. On the direct commit path, use the shared artifact-compensated commit helper. | `tests/test_report_artifact_commit_compensation.py`, `tests/test_report_finalization.py`, and `tests/test_report_signout_resume.py`: 14 passed locally. | FIXED locally; CI pending |
| Scheduled scientific-resource discovery was absent from the production Celery registry. | `discover_scientific_resources` had been declared only in the `Celery is None` branch, while the Beat schedule referenced it in all deployments. | Registered the named task in the normal Celery-enabled branch; retained an unavailable placeholder for environments without Celery. | `tests/test_celery_dispatch_fence_audit.py` + `tests/test_resource_discovery.py`: 13 passed. GitHub Actions run [#1533](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38723206952): backend, PostgreSQL/Celery integration, and frontend jobs succeeded. Commit `6b11afd`. | FIXED, tested, pushed to main |
| Artifact authorization did not validate its linked analysis/case relationship. | Shared artifact access checked only the case's tenant, although `Artifact.analysis_id` is independently stored and can refer to an analysis under a different case. | After tenant check, require any linked analysis to exist and have the same `case_id`; return the same 404 for inconsistent linkage. | Tenant-object, artifact-download identity, and population route tenant tests: 27 passed locally. | FIXED locally; CI pending |
| Any authenticated tenant user could enumerate member emails and roles. | The memberships list endpoint enforced authentication and tenant filtering but no role policy, while its only product use is the administrator-only settings roster. | Restrict the endpoint to organization admins and lab directors; call it in the settings UI only for those roles. | Roster authorization, membership mutation, invitation lifecycle, principal authorization, and API route-auth coverage: 30 passed locally. | FIXED locally; CI pending |
| Case export could fail on cloud storage and leave package bytes after persistence failure. | The export bundler required `local_path` for every artifact, while case exports accept the organization-selected Firebase store; deterministic package IDs also disabled the store's generated-ID cleanup if `flush` failed. | Copy cloud artifacts through the verified cloud download API and verify both cloud and local bytes against stored SHA-256/size. On worker failure, compensate the deterministic object only after a fresh DB check proves the Artifact row is absent; preserve a confirmed successful commit. | `tests/test_case_export.py`, `tests/test_case_export_artifact_compensation.py`, error-redaction, download-integrity, and dispatch tests: 17 passed locally. | FIXED locally; CI pending |

## Verification limits observed

- The local Windows full suite at `6b11afd` reported 807 passed, 37 skipped, and one failure in `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`. The runtime could not load WeasyPrint native `libgobject-2.0-0`/Pango libraries. This is an environment limitation, not evidence that PDF rendering passes locally.
- A fresh full backend run at `dc3be3e` reported **816 passed, 37 skipped, 1 failed**. The only failure was again `tests/test_report_pdf.py::test_pdf_renderer_returns_pdf_bytes`, caused by the unavailable Windows native `libgobject-2.0-0` dependency. CI status for commits after `324283b` has not been verified in this environment; prior run #1534 is not evidence for these later commits.
- GitHub Actions run [#1541](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38726450883) for `12ed477` completed successfully in backend, PostgreSQL/Celery integration, and frontend jobs. It includes the frontend production build/container and Compose validation. The current local changes have not yet been included in that run.
- The matching GitHub Actions run succeeded in all three jobs, including PostgreSQL/Celery integration and frontend production checks.
- No configured Firebase browser identity, live cloud bucket, or laboratory deployment was used for browser-based signup, email verification/recovery, real tenant separation, or report signout. Those checks remain NOT RUN here.
- The repository's existing detailed history is retained in [`PHASE_A_AUDIT_LEDGER.md`](PHASE_A_AUDIT_LEDGER.md); it contains prior fixes and remaining worker, deployment, and scientific qualification boundaries. This file supplements, rather than replaces, that record.

## Current workflow checkpoint

Source inspection has confirmed the Next.js/Firebase browser identity flow, FastAPI `/api/v1` routes, SQLAlchemy persistence, Celery/Redis workers and Beat, artifact stores, review/report APIs, and the existing workflow and integration test suites. The detailed stage-by-stage status is in [`END_TO_END_WORKFLOW_AUDIT.md`](END_TO_END_WORKFLOW_AUDIT.md).

## Remaining work, in dependency order

1. Complete the account lifecycle trace, including inactive/suspended identities, invitation and membership changes, browser session revocation, and error/retry behavior. Add browser/component-level coverage for user-visible paths where the current test stack permits.
2. Complete API-by-API object authorization and tenant isolation review, including every artifact/report/export and background task entrypoint; execute PostgreSQL integration tests rather than relying only on SQLite doubles.
3. Complete the case/specimen/VCF intake and analysis path audit against actual UI requests, persisted state, and failure recovery. Preserve the declared VCF scope and unsupported-input behavior.
4. Complete the evidence, review, reportability, artifact generation, signout, amendment, and audit-lineage trace. Verify each critical guard in route and service tests.
5. Complete frontend contract, stale-state, loading/error, accessibility, navigation, and authenticated-download review; run available frontend tests/build and a real browser journey if configured infrastructure exists.
6. Complete the reanalysis and resource-release lifecycle audit, including failure and duplicate-delivery cases.
7. Run the Phase 1 acceptance gate and update every matrix row with actual evidence; keep any unavailable external checks explicitly BLOCKED/NOT RUN.

## Phase decision

**Phase 1: PARTIAL.** The current code has broad automated coverage and several previously repaired workflow controls, but a complete source-level trace and authenticated end-to-end browser-to-persistence-to-signout verification have not been demonstrated. This is not a clinical validation, regulatory, or production-readiness determination.

## 2026-10-15 workspace case-switch privacy and stale-response correction

- **Finding:** changing the selected case left the previous case's analysis, specimens, variants, review, report, export, artifacts, and audit entries rendered until the new case request completed. In-flight polling and detail requests could also write the previous case's data after a switch.
- **Correction:** clear case-scoped state when selection changes; render only a loading/retry surface until `caseWorkspace.case_id` matches the selected case; cancel case-detail requests on cleanup; ignore stale responses from analysis, variant, audit, export, and artifact reads. Added a pure readiness-policy regression test.
- **Verification:** frontend `npm run test:session` passed 14 tests; `npm run validate:i18n` passed; `git diff --check` passed. CI run #1542 passed backend, PostgreSQL integration, and frontend jobs for prior commit `a270237`; the current UI correction still requires its own push-triggered CI run. Local Next build cannot run because `frontend/node_modules` is absent.
- **Checkpoint:** correction was committed and pushed as `c409f68`; GitHub Actions run #1543 passed all three jobs. Phase A remains PARTIAL: case switching is guarded in code and helper tests, but interactive browser account/tenant switching, remaining frontend surfaces, and all remaining Phase A workflow checks are still outstanding.

## 2026-10-15 audit timeline case-switch privacy correction

- **Finding:** the standalone audit page retained the prior case's events in the timeline while another case was selected; overlapping requests could allow an older response to overwrite the current selection.
- **Correction:** associate loaded events with their case identity, hide the timeline unless that identity matches the current selection, clear prior events on selection changes, and ignore canceled or superseded audit/list responses.
- **Verification:** frontend `npm run test:session` passed 14 tests; `npm run validate:i18n` and `git diff --check` passed. The shared case-identity readiness policy test covers the visible-data guard. This page change is not yet included in a production build or CI run.
- **Checkpoint:** correction was committed and pushed as `5519751`; GitHub Actions run #1544 passed all three jobs. Reports were then separately corrected in `c914c44`; run #1545 is in progress. Phase A remains PARTIAL; review still requires the same stale-response audit, and no browser-based journey has been demonstrated.

## 2026-10-15 report-page analysis-scope correction (working tree)

- **Finding:** the Reports page continued rendering decision and report rows from the previous analysis while another analysis ID was selected; racing requests could overwrite the newly selected analysis's data.
- **Correction:** results and selected decision are rendered only when their loaded analysis ID matches the selected ID; overlapping reads are generation-checked; reportability and report-generation actions remain disabled until the selected analysis data is loaded. Changing analyses also clears the prior decision selection, rationale, and disposition.
- **Verification:** frontend `npm run test:session` passed 15 tests, including the analysis-identity readiness policy; `npm run validate:i18n` passed. CI run #1545 caught a TypeScript error in the bootstrap effect cleanup. The scope error was fixed and pushed as `bc22d41`; run #1546 is in progress.
- **Checkpoint:** report-scope correction is committed as `c914c44`, and the build hotfix is committed as `bc22d41`. The review-page correction remains in the working tree and requires its own build verification. Phase A remains PARTIAL.

## 2026-10-15 clinical review analysis and variant context correction (working tree)

- **Finding:** changing analyses or selected variants could leave a previous clinical dossier, governance record, pedigree/segregation data, or reviewer rationale visible or writable while new review detail was loading. Late queue/detail responses could also replace newer selections.
- **Correction:** queue visibility is bound to its loaded analysis ID; dossier visibility additionally requires the selected variant and returned review bundle to match. Queue, review, governance, and family reads ignore superseded requests. Analysis changes reset case-specific reviewer edits, and variant changes clear variant-specific review data and rationale.
- **Verification:** frontend `npm run test:session` passed 16 tests (including analysis readiness and identity-key policy); `npm run validate:i18n` and `git diff --check` passed. The Next production build is unavailable locally because `frontend/node_modules` is absent; push-triggered CI will verify the review-page TypeScript/build integration.
- **Checkpoint:** review-page and Firebase identity remount corrections are in the working tree pending commit/push. CI #1546 passed the preceding report hotfix; current changes still need their own build run. Phase A remains PARTIAL and no browser-based reviewer/account-switch journey has been run.

## 2026-10-15 account-switch in-memory workspace isolation correction (working tree)

- **Finding:** auth-state changes cleared localStorage context but did not remount protected route components. On a direct Firebase UID change, case/report/review data already held in React component state could remain rendered for the next account.
- **Correction:** key the authenticated route subtree by a namespaced Firebase UID (and a distinct signed-out key), forcing route-local state to be discarded when the identity changes. Added a policy regression for distinct identities and signout.
- **Verification:** frontend behavior tests now pass 16 tests and localization validation passes. This app-shell integration has not yet been covered by a real Firebase/browser account switch; production build will be checked by CI after push.
- **Checkpoint:** code and test are pending commit/push with the Review page correction. Phase A remains PARTIAL.

## 2026-10-15 API object-authorization audit batch

| Finding | Root cause | Correction | Verification | Status |
|---|---|---|---|---|
| Audit endpoint distinguished nonexistent case IDs from cases owned by another tenant. | `GET /cases/{case_id}/audit` returned `200 []` when absent, but tenant guard returned `404 Case not found` for a foreign case, allowing ID existence probing. | Absent case now raises the same `404 Case not found`; added a regression asserting the exact status and response detail match for absent and cross-tenant cases. | Focused auth/tenant/analysis-variant/ACMG suite: 26 passed; `ruff --select F401,I` passed on changed Python files; `git diff --check` passed. | FIXED, locally verified |
| ACMG auto-assessment accepted a globally fetched variant without proving its membership in the requested analysis. | `auto_assess` called `db.get(Variant, variant_id)` instead of the existing analysis-scoped `get_analysis_variant` authorization helper. | Route now requires variant membership through the common helper before looking up annotation, population evidence, or persisting a specification assessment; regression proves nonmember variants are rejected with 404. | Focused auth/tenant/analysis-variant/ACMG suite: 26 passed; import lint passed on changed Python files. | FIXED, locally verified |

## 2026-10-15 follow-up authorization and ownership batch

| Finding | Root cause | Correction | Verification | Status |
|---|---|---|---|---|
| Pedigree member could link to a specimen from another case. | `add_member` accepted `specimen_id` from request without checking the specimen's owning case. | Resolve the specimen server-side and require `specimen.case_id == case_id`; otherwise return 404 with a case-scoped message. | Added a regression proving a foreign-case specimen is rejected before mutation; focused authorization, export integrity/download, mutation, variant access and reportability suites passed: 28 tests. | FIXED, locally verified |
| Case-export status/download, reportability signoff, evidence lookup and follow-up update could return different not-found details for absent versus foreign-tenant IDs. | Export routes fetched globally then applied tenant checks whose error detail identified a case; decision/evidence/follow-up routes returned an object-specific missing detail for absence but `Analysis not found` for a foreign tenant. | Centralized export lookup and tenant verification to return `404 Export not found`; remap only 404 analysis access failures to the matching object-specific 404 before continuing. | Regression tests in `tests/test_audit_tenant_authorization.py` compare absent and foreign responses for all four route types. Focused auth, export, variant and reportability suite passed: 31 tests. Updated an existing download test fixture to provide a realistic organization ID. Changed-file import lint (`ruff --select F401,I`) and `git diff --check` passed. | FIXED, locally verified |

The inventory continues. Nested resource/assay/specimen linkage and worker-owned tenant scope still need separate validation. The latest committed and pushed main correction is `dc3be3e`.

## 2026-10-15 browser account-context checkpoint (local, pending push)

- **Finding:** the app stored `siraloom.case_id`, `siraloom.case_identifier`, and `siraloom.analysis_id` globally in browser localStorage. `AppShell` did not clear them when Firebase identity changed or signed out. Server-side tenant checks prevented these IDs alone from granting access, but a different account inherited stale context and UI requests.
- **Change:** introduced `syncWorkspaceContext`, called from Firebase auth-state changes. It clears case/analysis context on signout or UID change, preserves it for the same UID, and tolerates restricted browser storage. Signout failures now display an English/Arabic alert. The `test:session` command now includes case artifact and account-context tests.
- **Verification:** `npm run test:session` passed 13 tests; `npm run validate:i18n` passed; `git diff --check` passed. `frontend/node_modules` is absent, so the TypeScript/Next build cannot run in this checkout.
- **Checkpoint:** implementation and tests are in the working tree and not yet pushed. After committing, continue frontend stale-data/error-state review and then worker tenant scope/recovery. Overall Phase A remains PARTIAL.

## 2026-10-15 API input and frontend regression CI correction (local, pending push)

- **Finding:** `/api/v1/variants/{variant_id}` accepted `str` and manually called `UUID(...)`, so malformed path IDs could raise an uncaught `ValueError` rather than FastAPI's normal 422 validation response.
- **Change:** typed the route parameter as `UUID` and added an API-level malformed-ID regression.
- **Finding:** the frontend CI job installed dependencies and built the app but never ran the existing Node behavior tests, including account-session routing and VCF artifact selection.
- **Change:** added `npm run test:session` to frontend CI. This command now includes safe redirect, session destination, case artifact selection, and account-context policy tests.
- **Verification:** focused backend API/auth tests passed 10; frontend Node behavior tests passed 13; localization guard passed; CI YAML parsed; `git diff --check` passed. These changes are uncommitted and will receive a new GitHub run after the direct-main push.
- **Checkpoint:** push this coherent input-validation/CI batch, then audit the remaining worker tenant/data lineage boundaries. Phase A remains PARTIAL.

## 2026-10-15 additional verified correction

- **A1 sign-in state misrouting (High):** an inactive or otherwise unauthorized provisioned Firebase identity received the same 403 as a new identity, and frontend redirect handling could send failed session checks to a requested internal route. Fixed with a stable unprovisioned-state response header, explicit CORS exposure, fail-closed frontend routing, and localized access/service messages. Unprovisioned accounts can continue to onboarding or invitation acceptance only; protected routes require a valid session.
- **Tests:** auth/principal/route/tenant focused suite 68 passed; frontend redirect/session-state Node tests 7 passed; i18n guard and JavaScript syntax checks passed. Local Next build unavailable because `next` is not installed. GitHub Actions run #1534 passed the backend, PostgreSQL/Celery integration, and frontend jobs, including the production frontend build/container and Compose validation.
- **Current branch state:** commit `324283b` is pushed to `main`. GitHub Actions run #1534 completed successfully across all three jobs; see [run details](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/38724143912). Do not mark Phase 1 complete based on focused checks.

## 2026-10-17 audit-snapshot persistence correction

- **Findings:** confirmation, follow-up, secondary-finding, and QC-observation create routes passed new ORM rows to serializers that read insert-generated `created_at` before the first flush. Separately, the secondary-finding endpoint read `body.status` although its Pydantic request model did not define that field, so the endpoint raised `AttributeError` for every request.
- **Corrections:** all four create routes flush new rows before serialization, inside the existing transaction. `SecondaryFindingInput` now defines `status` with a `DRAFT` default, matching the endpoint's allowed-state validation.
- **Regression coverage:** `tests/test_clinical_followup_persistence.py` invokes all four routes with a real SQLite session and asserts response status/timestamps and durable audit snapshots.
- **Verification:** frontend behavior suite passed 20/20 and localization guard passed; `git diff --check` passed. Python tests cannot run in this Windows runtime because no usable Python interpreter is available. CI #1582 exposed the missing request field (877 passed, 24 skipped, 1 failed); correction commit `9d14ef7` then passed CI #1583: backend 878 passed/24 skipped, PostgreSQL/Celery integration passed, and frontend behavior/build/container/Compose passed.
- **Status:** schema and flush corrections are pushed and CI-verified. A further local follow-up constrains all governance status fields to supported values and adds invalid-state validation tests; it still needs push and CI. Phase A remains PARTIAL.
- **Next action:** push and verify the state-enum validation, then continue the direct-object and reviewer-to-signout recovery audit. Live Firebase and deployed two-tenant verification remain environment-dependent acceptance gaps.

## 2026-10-17 clinical-governance status validation (local checkpoint)

- **Finding:** confirmation and follow-up status strings accepted arbitrary values, even though the API/UI workflow uses finite lifecycle states. Unsupported direct API input could persist misleading governance states. Secondary-finding status is likewise now declared explicitly and constrained to the endpoint's `DRAFT`/`FINAL` set.
- **Correction:** Pydantic request schemas constrain confirmation to `PENDING`, `COMPLETED`, `WAIVED`, `FAILED`, or `NOT_REQUIRED`; follow-up to `PLANNED`, `IN_PROGRESS`, `COMPLETED`, or `CANCELLED`; and secondary finding to `DRAFT` or `FINAL`.
- **Regression coverage:** parameterized schema tests require unsupported states to raise `ValidationError`; the SQLite persistence regression covers valid create requests and audit snapshots.
- **Verification:** `git diff --check` and frontend tests/localization guard pass. Python tests are unavailable locally. Main commit `9d14ef7` passed CI #1583; it predates this status-validation extension.
- **Status:** this extension is local and awaits push-triggered CI; Phase A remains PARTIAL.
- **Next action:** push the state-contract validation as part of the next bounded batch, verify its backend/frontend/PostgreSQL jobs, and continue remaining direct-object and integrated signout/recovery audit.
