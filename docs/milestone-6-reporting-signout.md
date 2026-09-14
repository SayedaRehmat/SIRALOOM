# Milestone 6 — Clinical + Analytical Reporting & Sign-out

Status: implemented and software-tested; not clinically validated.

## Scope

M6 connects classification → reportability → clinical/analytical report → authorization/sign-out → immutable version lineage → audit/provenance.

### First-class reportability
- `reportability_decisions` is a versioned database entity rather than classification metadata.
- Default germline policy is deterministic and configurable: P/LP → REPORT; VUS → REVIEW; LB/B → DO_NOT_REPORT.
- Priority score is triage metadata and is not a pathogenicity/classification score.
- Every proposal records policy name/version and rationale.
- Finalization requires an authorized clinical/report-finalization role, expected review version, and written reason.
- Classification and reportability are independent gates.

### Clinical report
- Contains only findings with a FINAL reportability decision of REPORT.
- Includes case/test/clinical question/specimen context, findings, ACMG evidence, population context, methodology, limitations, recommendations and references.
- Arabic, English and bilingual modes remain supported.

### Analytical report
- Retains the complete latest classified variant set and can include full evidence/annotation payloads.
- It is distinct from the concise clinical interpretation report.

### Sign-out
- Finalization requires all latest classifications to be FINAL + APPROVED and all reportability decisions to be FINAL.
- A report must have an immutable stored artifact before approval.
- The approval actor, timestamp, reason, report version and supersession relationship are audited.
- A newer final report of the same case/report type supersedes the previous final version. Clinical and analytical report types maintain separate version streams.

### Case package
Case exports now retain versioned reportability decisions in `evidence.json`, preserving decision lineage alongside evidence, ACMG, population and review records.

## Verification
- Python compilation: PASS
- pytest: 84/84 PASS
- SQLAlchemy model creation: PASS
- Frontend production build: not run in this environment because Node dependencies are not installed.
- Live Firebase/Redis/Celery/provider integration: not run.

## Clinical boundary
This milestone implements a governed software workflow. It does not establish clinical validation, accreditation, regulatory authorization, or laboratory-specific reporting policy. Final release remains the responsibility of the qualified laboratory/signatory.
