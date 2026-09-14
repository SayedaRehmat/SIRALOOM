# SIRALOOM Variant — Phase 1

SIRALOOM is the platform. **SIRALOOM Variant** is Service 01.

Phase 1 implements the foundation for:

```text
VCF
 → validation
 → reference-aware normalization
 → canonical identity
 → provider annotation
 → population context
 → evidence
 → ACMG/ClinGen-aware assessment
 → human review
 → report
 → audit/provenance export
```

The web UI is intentionally not the execution engine. Long-running analyses are persisted on the backend and monitored by the UI.

## Development stack

- Backend: FastAPI + SQLAlchemy + PostgreSQL
- Background execution: Celery-compatible queue boundary + Redis
- Frontend: Next.js + React + TypeScript
- Artifacts: streaming file-backed store with SHA-256
- Reporting: HTML/CSS to PDF with RTL-capable rendering

## Frontend

The frontend now has public routes (`/`, `/about`, `/services`, `/services/variant`, `/contact`, `/privacy`, `/terms`, `/login`, `/signup`) and protected application routes under `/app`. Configure Firebase before production use; see `docs/firebase.md` and `docs/security.md`.

Set:

```text
NEXT_PUBLIC_SIRALOOM_API_BASE=http://localhost:8000/api/v1
```

The current development Docker Compose definition exposes the frontend on port 3000 and the API on port 8000.

The frontend dependency installation could not be completed in the current sandbox because npm package installation timed out. The source was TypeScript-checked with temporary dependency stubs; a real `npm install`/`next build` remains an environment-level validation step.

## Backend tests

Run:

```bash
PYTHONPATH=. DATABASE_URL=sqlite:///./ui_test.db REDIS_URL=redis://localhost:6379/0 \
GENEBE_ENABLED=false GNOMAD_ENABLED=false pytest -q
```

Current result in the development environment:

```text
84 passed
```

## Deployment boundary

Phase 1 intentionally begins at VCF. Future SIRALOOM Pipeline will feed FASTQ-derived VCFs into this same interpretation core.

For laboratory deployment, external genomic resources are configured through resource adapters. Large patient files and laboratory databases should remain on the laboratory-controlled infrastructure unless an explicitly authorized remote resource is used.

## Clinical boundary

This package is not a declaration that SIRALOOM Variant is clinically validated or regulatorily certified. The software must be validated for its intended assay/workflow by the deploying laboratory before clinical use.

## Case-centered workspace milestone

Phase 1 is being hardened around the clinical laboratory case as the permanent root. The service exposes case listing/detail/update and specimen registration endpoints alongside the existing analysis, review, report, and audit APIs.

Phase 1 has two report layers:

- Clinical report: concise, reportable, reviewer-authorized interpretation.
- Complete variant report: all analyzed variants with canonical identity, annotation-derived fields, global/MID/local population observations, evidence counts, ACMG state, classification, review state, and reportability disposition.

The complete variant report is available as live JSON for inspection and as downloadable CSV/JSON. The audit API retains before/after state, artifact references, software/workflow/resource metadata; the next UI iteration exposes those details directly.


## Current milestone

**Milestone 6 — Clinical + Analytical Reporting & Sign-out** is implemented and software-tested. It adds first-class versioned reportability decisions, explicit human reportability finalization, clinical-vs-analytical report separation, report artifact/sign-out gates, immutable report version/supersession lineage, audit linkage, case-export preservation, and the `/app/reports` workspace.

Verification: **84/84 Python tests passed** and backend compilation passed. Frontend production build and live Firebase/PostgreSQL/Redis/Celery/provider integration remain deployment-level validation steps.

## Milestone 7 — deployment and validation foundation

M7 adds production-oriented liveness/readiness probes, migration-safe API startup,
durable worker startup, a production Docker Compose profile, secret/configuration
boundaries, and a deployment smoke-test script. See `docs/milestone-7-deployment-validation.md`.

## Milestone 8 status
M8 adds durable batch recovery for evidence/ACMG, structured HPO phenotype context and matching, gene-disease and literature evidence domains, contextual evidence intake APIs, and report preservation of phenotype/context evidence. HPO and literature context are decision support and are not autonomous pathogenicity classification.

## Milestone 10 — pedigree, inheritance and segregation

M10 adds first-class family interpretation context: pedigree members, parent-child relationships, variant-specific segregation observations, and fingerprinted inheritance-model assessments. The Clinical Review Workspace can record and review family structure and observations without relying on free-text `clinical_context`. Inheritance consistency is explicitly decision support; it does not automatically assign pathogenicity or ACMG/ClinGen criterion strength. See `MILESTONE_10_IMPLEMENTATION_REPORT.md`.


## Milestone 12 — Confirmation, follow-up and secondary-finding governance

M12 adds explicit clinical-governance records for orthogonal confirmation, variant/case follow-up actions, and policy-controlled secondary findings. Confirmation can be marked required and blocks final clinical release until COMPLETED or WAIVED. Secondary findings remain separate from primary diagnostic reportability; a REPORT decision can be finalized only with documented ACCEPTED consent. All records are versioned/audited and exposed in the Clinical Review Workspace.

These features are workflow infrastructure, not clinical validation, and SIRALOOM does not silently impose a universal confirmation rule or secondary-finding gene list.

## Milestone 13 — Streaming and durable genomic partitions
M13 removes the prior full-normalized-variant Python memory boundary. Normalization can run without collecting variants, downstream annotation/population/evidence/ACMG processing uses bounded batches, and a durable `analysis_partitions` manifest records deterministic logical partitions with artifact lineage. This improves resumability and memory behavior for large VCFs without claiming WGS-scale production benchmarking in the development environment.


## Milestone 14 — Resource-aware partition scheduling

M14 adds a database-backed resource scheduler for the durable genomic partitions introduced in M13. Partitions now carry a resource class, CPU request, memory request, retry attempt, worker lease, lease expiry, completion state, and failure information. Expired leases are recoverable; active leases are counted against configured CPU/RAM capacity; retry attempts are bounded.

The annotation workflow now obtains a durable execution lease for each annotation partition before invoking the provider and releases it only after annotation rows and the checkpoint are persisted. Celery production configuration now explicitly applies `CELERY_CONCURRENCY`, while partition capacity is controlled independently through `PARTITION_SCHEDULER_CPU_CAPACITY`, `PARTITION_SCHEDULER_MEMORY_MB`, `PARTITION_LEASE_SECONDS`, and `PARTITION_MAX_ATTEMPTS`.

M14 is an execution-control milestone, not a claim of clinical validation or a completed WGS benchmark. Live PostgreSQL/Redis/Celery/Firebase/GeneBe deployment and representative WGS-scale performance testing remain deployment/validation gates.

## Phase 1 Release Candidate — M15

M15 is the **release and validation gate**, not another feature expansion. The research-driven clinical-laboratory model is now represented in the software through the case-first tertiary workflow, phenotype/context, population evidence, literature, pedigree/inheritance/segregation, technical QC, human review, reportability, confirmation/follow-up governance, reporting, audit and provenance.

The current codebase is a **Phase-1 release candidate**, not a clinically validated diagnostic product.

### Current verified software baseline

- Migration head: `0019_partition_scheduler_resources`
- Backend automated suite: **113/113 tests passed at M14 baseline**
- M15 adds release/deployment validation artifacts and hardens partition lease handling.
- Frontend production build could not be executed in this sandbox because npm dependency installation timed out; CI/deployment must execute the real `npm install` + `npm run build`.
- Live PostgreSQL/Redis/Celery/Firebase/artifact-storage/GeneBe execution is a deployment gate, not claimed by the repository.

### Phase 1 boundary

```text
VCF
 → case/specimen/artifact intake
 → validation
 → reference-aware normalization
 → canonical variant identity
 → streaming durable partitions
 → resource-aware execution
 → annotation
 → global/Middle Eastern population context
 → evidence + literature + phenotype context
 → ACMG/ClinGen decision support
 → human clinical review
 → reportability
 → confirmation/follow-up/secondary-finding governance
 → clinical + complete analytical report
 → audit/provenance/export
```

### Deployment

See:

- `docs/DEPLOYMENT.md`
- `docs/LIVE_VCF_VALIDATION.md`
- `docs/PHASE1_ACCEPTANCE_MATRIX.md`
- `docs/PHASE1_RELEASE_STATUS.md`

Recommended public demonstration topology is a Next.js frontend on Vercel and a containerized FastAPI API with PostgreSQL, Redis and a separate Celery worker. The reference FASTA and patient artifacts remain server-side/laboratory-controlled.

### Live demo policy

Use only a public benchmark VCF or authorized de-identified data. Do not upload identifiable patient data to a public demonstration environment.

A successful live VCF run demonstrates software integration and reproducibility. It does **not** establish clinical validity, regulatory authorization, accreditation, or diagnostic performance.
