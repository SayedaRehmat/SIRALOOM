# SIRALOOM Variant — Milestone 11
## Technical QC + Assay/Test Quality

M11 adds a first-class quality layer between assay/test execution and clinical interpretation. It deliberately separates **observed QC metrics**, **laboratory-defined assay thresholds**, and the **analysis QC gate**.

### Implemented
- `Analysis.assay_id` links an analysis to a versioned organization-owned assay profile.
- `TechnicalQCObservation` persists individual QC metrics with value, unit, source, version, status and metadata.
- `QCAssessment` persists the evaluated QC snapshot, profile/version, rule results, gate status and reviewer provenance.
- Assay `configuration.rules` supports MIN, MAX, RANGE and EXACT rules with WARN or FAIL severity.
- Missing metrics are `NOT_ASSESSED`, never silently treated as zero/pass.
- Overall gate is deterministic: FAIL > WARN > PASS; no rules = NOT_ASSESSED.
- API endpoints create/list assay profiles, attach an assay during analysis creation, record QC observations, retrieve QC state and perform a QC assessment.
- Clinical Review Workspace now exposes assay profile, QC observations and latest QC gate.
- Review bundle carries quality context so the review surface can inspect technical readiness alongside phenotype, pedigree, population and evidence.
- Audit events are emitted for assay creation, QC observations and QC assessments.

### Deliberate scientific boundary
SIRALOOM does **not** hard-code universal clinical QC cut-offs. Coverage, depth, mapping, duplication, contamination, callable fraction, Ti/Tv and other metrics are assay/platform/pipeline dependent. The laboratory must define and validate its own profile and thresholds.

A QC gate is a technical readiness signal; it is not a pathogenicity classification and does not replace human clinical review.

### Validation
- Full backend test suite: expected to pass after migration-head update.
- M11 unit tests cover minimum/maximum/range/exact rule mechanics, warning handling, missing metrics, deterministic gate behavior and strict rule validation.
- SQLite full Alembic replay reaches migration `0016_technical_qc_assay_quality`.
- Python compilation checked.
- Live PostgreSQL/Redis/Celery/Firebase/GeneBe execution is not claimed in this environment.
- Frontend production build is not claimed because dependencies are not installed here.
