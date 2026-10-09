# Release readiness dossier — stage gates

## Gate 0: Internal engineering

**Entry:** reviewed code, isolated test data, controlled secrets, automated CI.  
**Exit:** CI green for the exact commit; migration and dependency checks; known limitations documented; no unresolved critical defect.  
**Allowed claims:** software development/testing only.  
**Current assessment:** largely supported by recent CI, but confirm the exact desired workflow and deployment.

## Gate 1: Restricted research demonstration

**Entry:** Gate 0; public/de-identified benchmark only; trial limits and data policy configured; real auth and artifact store tested.  
**Exit:** one reproducible live E2E run; visible stage failures; provenance/export verified; no patient-care claim; support and deletion procedure ready.  
**Allowed claims:** research demonstration within tested scope, not clinical diagnostic validity.  
**Current assessment:** HOLD until live evidence is captured.

## Gate 2: External research-laboratory pilot

**Entry:** Gate 1; customer responsibilities and data-processing terms agreed; tenant isolation and capacity tested.  
**Exit:** multi-user/tenant adversarial tests, resource approval/fallback tests, recovery matrix, benchmark discrepancy review, backup restore and incident runbook accepted.  
**Allowed claims:** only the exact tested research workflow and explicit limitations.  
**Current assessment:** HOLD.

## Gate 3: Laboratory workflow evaluation

**Entry:** intended-use and jurisdiction analysis; quality-system owner identified; risk and validation protocols approved.  
**Exit:** laboratory-controlled validation on representative assay/workflow data, authorized review/sign-out, traceable verification records, SOPs, change control and training.  
**Allowed claims:** only as authorized by the laboratory and applicable jurisdiction.  
**Current assessment:** NOT AUTHORIZED by this software audit.

## Gate 4: Clinical production / broad commercialization

**Entry:** Gate 3 where applicable; regulatory/legal assessment; security and privacy controls; validated operating model and support.  
**Exit:** documented laboratory validation, applicable regulatory/contractual approvals, independent review, monitored production operations, recovery drills and customer governance.  
**Allowed claims:** bounded by evidence, approvals and jurisdiction.  
**Current assessment:** NOT READY based on available evidence.

## Mandatory release dossier contents

- Exact source commit, frontend/backend/worker image digests and configuration version.
- Intended use, supported variant classes and exclusions.
- Requirements-to-code-to-test traceability.
- Reference/resource identity, versions, checksums and organization approval.
- Golden dataset and concordance report, including adjudicated discrepancies.
- Security/tenant test results and residual-risk approvals.
- Live end-to-end evidence with non-identifying case IDs and artifact hashes.
- Migration, rollback, backup/restore and worker-recovery evidence.
- Monitoring/alert verification, incident response, retention/deletion and support ownership.
- Release approval by the accountable engineering owner and, for laboratory use, the appropriate laboratory/regulatory authorities.

A green CI run, responsive website, successful upload, or generated PDF is not sufficient for any later gate on its own.
