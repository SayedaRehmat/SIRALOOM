# Controlled laboratory end-to-end validation: analysis to report sign-out

## Purpose and validation boundary

This runbook is for a **staging deployment or an explicitly disposable laboratory workspace**. It defines the evidence required to demonstrate a complete SIRALOOM workflow using the lab's registered resources and storage configuration. It is not a substitute for clinical validation, laboratory accreditation, or local verification/validation approval.

Do not use identifiable patient data for this exercise. Use an approved, non-sensitive VCF fixture with known expected properties and a disposable case. Record the deployed commit SHA, configuration/resource-profile version, organization, operator roles, UTC start/end times, and every generated analysis/report/artifact ID.

A passing API smoke test or CI run alone does not demonstrate a successful end-to-end deployment.

## Preconditions (must be verified before creating the test analysis)

1. **Deployment identity:** record the exact backend commit SHA, API base URL, frontend deployment, environment, database migration revision, worker image/version, and broker configuration.
2. **Authentication and role separation:** use separate authorized identities for case preparation, scientific review, and report sign-out where required by the laboratory's policy. Never paste tokens into tickets, logs, shell history, or this runbook.
3. **Organization storage:** confirm the active organization storage profile, writable capacity, retention/backup policy, and access controls. Verify artifact download returns the stored bytes whose SHA-256 matches the database record.
4. **Resource governance:** register each required provider as a candidate; complete the organization's approval, qualification, and activation/binding process; verify the selected analysis resource profile resolves to the intended organization-bound resources. Record provider identity, version/build, configuration digest, and qualification evidence. A resource being registered or qualified is not enough if it is not bound to this organization/profile.
5. **Tool execution:** confirm the required reference build and executable tool/cache/data are actually available to the worker. Do not infer execution readiness from a resource-registry row alone.
6. **Test fixture:** verify the VCF is non-empty, valid for the declared build, has a documented expected variant set, and contains no patient-identifying information. Store its SHA-256 before upload.
7. **Capacity baseline:** record free bytes/inodes for ingress/proxy temporary storage, ASGI upload spooling, application staging, persistent artifact storage, and worker scratch space. Enable API, worker, database, broker, and filesystem monitoring.

If any precondition cannot be verified, stop and record a blocked validation result. Do not substitute an unapproved provider or silently change reference/build.

## Execution sequence

Use the authenticated API under the target organization's own tenancy. The API paths below are relative to `/api/v1`. Use the OpenAPI schema deployed with the tested commit for request details; do not copy production tokens or real patient identifiers into examples.

### 1. Intake and durable artifact storage

1. Create or select a disposable case: `POST /cases`.
2. Confirm the specimen belongs to that case using the case/specimen API available in the deployed OpenAPI schema.
3. Upload the fixture to `POST /cases/{case_id}/artifacts` with the required `specimen_id`, explicit `genome_build` (`GRCh37` or `GRCh38`), and file.
4. Record the returned `artifact_id`, byte size, validation status, and SHA-256. Compare the server hash with the fixture hash.
5. List case artifacts with `GET /cases/{case_id}/artifacts`, then download the uploaded artifact using `GET /artifacts/{artifact_id}/download`. Verify the downloaded bytes and hash.

**Pass evidence:** metadata and payload persist across a fresh request; the downloaded hash matches the upload; the artifact belongs to the expected case/specimen/organization.

### 2. Analysis plan, preflight, and dispatch

1. Create an analysis with `POST /cases/{case_id}/analyses`, using the uploaded `input_artifact_id`, explicit reference build, intended workflow ID/version, and the lab's `resource_profile_id`.
2. Start it with `POST /analyses/{analysis_id}/start`.
3. Inspect the response. If the resource plan is not ready, record the reported status and each `resource_issues` capability/code/message. **Do not continue by bypassing the block.** Correct the organization binding/qualification/capacity through the governed process, then re-check the persisted plan and start/recovery behavior.
4. Poll `GET /analyses/{analysis_id}` until a documented terminal state or a human gate. Preserve all workflow-step statuses, attempts, error codes, timestamps/heartbeats, next-step values, queue task IDs, and resource-plan/snapshot identifiers exposed by the API.
5. Verify that normalization and annotation used the declared reference/toolchain; confirm normalized variant representation and persisted annotations against the fixture's expected properties.
6. Verify population observations and evidence records were persisted for the expected variants. Record provider, dataset release/build, query outcome, and evidence provenance. An empty response must not be treated as a successful lookup without examining its status/reason.

**Pass evidence:** the intended organization-bound resources were actually executed; the immutable plan/snapshots identify what ran; no silent fallback occurred; persisted results match the test fixture; retry/restart does not create duplicate dispatch or duplicate durable outputs.

### 3. Variant review and classification

1. List analysis variants using `GET /analyses/{analysis_id}/variants`. Record the total and the IDs selected for the test.
2. Inspect the per-variant review bundle using `GET /analyses/{analysis_id}/variants/{variant_id}/review`.
3. Verify evidence and population records are linked to the correct analysis and variant. Every criterion proposed for ACMG assessment must reference persisted evidence; do not fabricate evidence IDs or use synthetic clinical claims.
4. Where the workflow requires an ACMG assessment, use the deployed `/analyses/{analysis_id}/variants/{variant_id}/acmg/assess` or `/auto-assess` route only according to the approved validation protocol. Automated output is not a substitute for an authorized reviewer.
5. Use the reviewer identity to start review, review the applicable criteria with documented reasons/evidence, and approve the classification using the API's expected-version/concurrency fields. Record classification version, framework/specification version, reviewer, decision, and audit event.
6. If a workflow human gate is reached, resolve it through `POST /analyses/{analysis_id}/workflow/{step_id}/human-gate` only when the domain acceptance conditions are satisfied. A retry must document a genuine input/context/resource change.

**Pass evidence:** the final classification is versioned, attributable to an authorized reviewer, linked to its supporting evidence, and retrievable after a new session. No automation-only result is represented as a signed clinical interpretation.

### 4. Reportability, report generation, and sign-out

1. Evaluate reportability with `POST /analyses/{analysis_id}/reportability/evaluate`.
2. Review every variant decision with `GET /analyses/{analysis_id}/reportability`. Finalize decisions through `POST /reportability/{decision_id}/finalize` with the expected version and a documented reason. Ensure the policy allows the chosen disposition.
3. Generate a draft report with `POST /analyses/{analysis_id}/reports`. Report generation should be rejected while required classification review or reportability is incomplete.
4. Retrieve the report using `GET /reports/{report_id}`; inspect content, report type/language, version, source analysis, and draft artifact. Download and verify the draft artifact if the deployed artifact API exposes it for the authorized user.
5. Have an authorized sign-out identity finalize using `POST /reports/{report_id}/finalize` with the required reason. Record the response and whether workflow resume was queued.
6. Re-read `GET /reports/{report_id}` and `GET /analyses/{analysis_id}/reports`. Confirm final status, sign-out actor/time, signed artifact ID, signed SHA-256, version/supersession links, and matching artifact bytes. Confirm the audit trail contains the expected report-generation and sign-out events.
7. Open a fresh authenticated session and retrieve the case, analysis, variants, report, and signed artifact again. Restart a worker or use the approved recovery test procedure in staging, then verify the durable state remains consistent.

**Pass evidence:** sign-out is performed by an authorized identity only after review and reportability gates are satisfied; the signed artifact is durable and checksum-verifiable; provenance/audit events are present; a fresh session sees the same finalized state; no duplicate report version or dispatch appears after recovery.

## Frontend case-dossier acceptance

After the API workflow has produced durable records, verify the same case through the authenticated workspace UI:

1. Open **Cases**, locate the exact case identifier, and use **Open case dossier**. Confirm the dossier case ID matches the API response and that the specimen count, analysis versions, file inventory, and report count agree with the API.
2. For every listed artifact, compare filename, artifact type, byte size, genome build, validation status, and SHA-256 with the API response. Download a small fixture and verify its bytes/hash. For a large fixture, verify save-to-disk streaming on the supported browser; do not test multi-gigabyte downloads in a browser path that buffers the entire response into memory.
3. Open each analysis from the dossier. Confirm the selected case and analysis IDs are preserved, and that the workflow steps, human gates, variant review, phenotype/family context, evidence, and provenance are visible for the selected analysis.
4. Open reports for the same analysis. Confirm draft/final status, version, signed artifact identity/hash, and report download correspond to the API. The UI must show report-loading errors rather than silently representing a failed request as “no reports.”
5. Change the workspace language to English, Arabic, and bilingual. Verify that the selection persists after refresh and that Arabic layout uses RTL direction without clipping tables, hashes, action buttons, or status labels.
6. Reload the dossier in a fresh authenticated browser session. Confirm that case files, analyses, reports, and audit links resolve to the same persisted IDs without relying on stale component state.

**Pass evidence:** record screenshots or a screen recording with test identifiers only, the API IDs/hashes, browser/version, selected locale, and any console/network errors. A successful frontend build is not a substitute for these browser checks.

## Required negative and recovery tests

Run these as separate cases or isolated test runs so they cannot contaminate the positive test:

- Required resource is missing or not organization-bound: analysis remains blocked and no work is dispatched.
- Upload exceeds ingress cap: proxy returns HTTP 413 and request is absent from application intake logs.
- Upload exceeds application cap while below proxy cap: application returns HTTP 413.
- Unauthorized user attempts classification approval or report sign-out: request is rejected and no state mutation is committed.
- Report generation before classification/reportability finalization: request is rejected with HTTP 409.
- Reviewer submits a stale expected version/attempt: request is rejected as a concurrency conflict.
- Worker/broker is interrupted after a durable state mutation: recovery does not lose the mutation or create duplicate dispatch/output.
- Storage write or checksum verification fails: no artifact is marked successful while payload bytes are missing or inconsistent.

## Acceptance record

Complete one record for every run:

- [ ] Tested commit/deployment, migrations, worker image, configuration, and resource-profile version recorded.
- [ ] Case, specimen, input artifact, analysis, variant, report, and signed artifact IDs recorded (test IDs only).
- [ ] Input and stored/downloaded artifact hashes match.
- [ ] Actual selected provider identities, versions/builds, bindings, and qualification records captured.
- [ ] Normalization, annotation, population, and evidence steps have persisted outputs and provenance.
- [ ] Human classification review and reportability decisions have authorized actors, versions, reasons, and audit records.
- [ ] Signed report and signed artifact hash verified after a fresh session.
- [ ] Negative authorization/resource/upload tests pass.
- [ ] Recovery and concurrency tests pass without duplicate dispatch, inconsistent artifact rows, or orphaned temporary files.
- [ ] Peak disk/inode, CPU/memory, latency, throughput, queue age, API error rates, and database/broker health recorded.
- [ ] Laboratory owner has documented numeric acceptance thresholds and signed the validation record.

A run is **NOT ACCEPTED** if any required evidence is missing, any step silently falls back to an unapproved resource, any provenance/hash mismatch occurs, or any required human gate is bypassed. Report failures with the exact stage and reason; do not summarize an incomplete run as end-to-end success.
