# SIRALOOM Variant — Milestone 6 Implementation Report

**Milestone:** M6 — Clinical + Analytical Reporting & Sign-out  
**Status:** Implemented and software-tested; not clinically validated.

## Delivered

1. **First-class reportability domain**
   - Added `reportability_decisions` with immutable version lineage.
   - Stores classification linkage, policy name/version, disposition, priority score/band, rationale, reviewer, approval time and review version.
   - Default germline decision-support policy: PATHOGENIC/LIKELY_PATHOGENIC → REPORT; VUS → REVIEW; LIKELY_BENIGN/BENIGN → DO_NOT_REPORT.
   - Priority is explicitly triage metadata, not pathogenicity classification.

2. **Human reportability review**
   - Added evaluate, list and finalize APIs.
   - Finalization requires an authorized report-finalization role, expected review version and written rationale.
   - Decisions are audited.

3. **Clinical report gate**
   - Finalization requires every latest classification to be `FINAL + APPROVED`.
   - Finalization also requires every latest reportability decision to be `FINAL`.
   - A final report must reference a stored immutable report artifact.
   - Clinical reports contain only findings with finalized `REPORT` disposition.

4. **Analytical report separation**
   - `CLINICAL_INTERPRETATION` is concise and reportability-filtered.
   - `ANALYTICAL` retains the complete latest classified variant set and can include full evidence/annotation payloads.

5. **Report content contract**
   - Schema version advanced to `1.1.0`.
   - Includes case/test/clinical question/specimen context, findings, ACMG criteria, population context, methodology, limitations, recommendations and references.
   - English, Arabic and bilingual rendering retained.
   - Draft artifacts explicitly identify themselves as `NOT_FOR_CLINICAL_RELEASE`.

6. **Sign-out and version lineage**
   - Approval records actor and timestamp in the report row and audit chain.
   - New final reports supersede the previous final report of the same case/report type.
   - Clinical and analytical report types therefore have separate version streams.

7. **Audit/case export**
   - Versioned reportability decisions are included in case evidence exports.
   - Existing artifact SHA-256 and audit/provenance lineage remain preserved.

8. **UI**
   - Added `/app/reports` reporting/sign-out workspace.
   - Replaced the Reports navigation placeholder with the real route.
   - UI supports reportability evaluation, human disposition, draft generation, version history, approval/sign-out and PDF download.

## Verification

- Python compilation: **PASS**
- Pytest: **84/84 PASS**
- SQLAlchemy metadata/model table creation: **PASS**
- Migration file added: `0013_reportability_decisions.py`
- Full Alembic chain was not claimed as SQLite-verified because the existing M11 migration uses PostgreSQL-style `ALTER CONSTRAINT` behavior that SQLite cannot execute; this is an existing migration portability limitation, not an M6 test failure.
- Frontend production build: **NOT RUN** because Node dependencies are not installed in this environment.
- Live Firebase / PostgreSQL / Redis / Celery / GeneBe integration: **NOT RUN**.

## Clinical boundary

M6 establishes a governed software workflow and reproducible report/sign-out data model. It does **not** establish clinical validation, accreditation, regulatory authorization, or a laboratory-specific reporting policy. A laboratory must validate its complete assay/workflow and configure qualified personnel, local policies and jurisdictional requirements before clinical release.
