# Live VCF Validation Runbook

This runbook validates the **deployed software**, not a clinical assay.

## 1. Test data

Use one of:

- a public benchmark VCF such as the GIAB HG001 GRCh38 small-variant truth VCF; or
- a de-identified/non-sensitive VCF that you are authorized to use.

Do not upload identifiable patient data to a public demo.

The GIAB HG001 GRCh38 v4.2.1 benchmark VCF is publicly documented by the GA4GH benchmarking resources and nf-core variant benchmarking documentation.

## 2. Required deployed components

- Next.js frontend
- FastAPI backend
- PostgreSQL
- Redis
- Celery worker
- Firebase Authentication
- artifact storage
- a configured GRCh38 reference FASTA + FAI
- a permitted annotation provider configuration

## 3. Deployment test

1. Open the production frontend.
2. Create a test account in the dedicated demo Firebase project.
3. Verify email.
4. Create a case with a non-identifying case ID.
5. Register a specimen.
6. Upload the benchmark VCF and select the matching genome build.
7. Confirm artifact SHA-256 and validation state.
8. Create/start the analysis.
9. Observe each durable workflow step.
10. Confirm annotation provider source/version is shown.
11. Confirm population observations distinguish unavailable resources from zero frequency.
12. Open the Clinical Review Workspace.
13. Inspect evidence, phenotype/context, inheritance/QC where provided.
14. Do not treat automated ACMG output as final clinical interpretation.
15. Finalize reportability only as an authorized reviewer in the demo organization.
16. Generate the clinical and complete analytical reports.
17. Download the report/provenance package.
18. Verify the audit trail contains the material actions.

## 4. Expected release evidence

Capture:

- frontend URL
- backend health URL
- analysis ID
- case ID (non-identifying)
- input VCF filename and SHA-256
- VCF record count
- normalization count/change count
- annotation provider + version
- population resource + version/status
- workflow step timestamps/statuses
- report artifact SHA-256
- export/provenance package SHA-256
- deployment revision/image digest

## 5. Failure tests

At minimum:

- malformed VCF
- missing/invalid genome build
- provider timeout/429 simulation
- worker restart during a checkpointed batch
- expired partition lease
- unauthorized case access
- cross-tenant artifact access
- frontend/backend origin mismatch

A failure must remain visibly FAILED/BLOCKED/REQUIRES_REVIEW; it must never appear complete.
