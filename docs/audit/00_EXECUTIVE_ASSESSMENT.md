# SIRALOOM independent readiness assessment — 2026-10-09

## Status and scope

This is an initial, evidence-based repository audit, not a certification, clinical validation, penetration test, or live deployment acceptance. Evidence was collected from the public GitHub repository, current `main` files, GitHub Actions run metadata, open pull requests, and a focused review of architecture, workflow, VCF, resource, auth, storage, and reanalysis code. The production runtime and Vercel/backend configuration were not independently authenticated or exercised in this pass.

## Baseline

- Repository: [SayedaRehmat/SIRALOOM](https://github.com/SayedaRehmat/SIRALOOM)
- Default branch: `main`
- Observed HEAD: `72cf5b703c1d0ce48d18ba2b14a1abb376b3298f`
- Latest observed main CI: [run 1043](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/37917001590), completed successfully. Backend tests/compile, PostgreSQL migration + dispatch concurrency integration, and frontend production build steps all reported success.
- Open PRs observed: #84 resource profiles (draft; no workflow run found for its latest head), #78 upload capacity (CI success observed on its head but still open), #2 and #1 bcftools normalization, and #10 workflow state-machine qualification. Do not assume open-PR changes are in `main`.
- Migration files extend through `0046_organization_storage_profiles.py`; the current main CI successfully applies migrations to PostgreSQL 16.
- The repository's own release status and acceptance matrix explicitly state that live end-to-end validation, scientific benchmark validation, and production deployment validation remain open.

## Readiness verdict

**Software engineering foundation: substantial, actively hardened, and CI-tested. External research pilot: not yet evidenced as ready. Clinical use: not authorized by this audit and not supported by current evidence.**

The latest green CI is a meaningful engineering signal, but it cannot substitute for real permitted provider execution, a public truth-set benchmark, live tenant isolation tests, production recovery tests, and traceable sign-off. The project itself correctly disclaims clinical validation and identifies these gates in `docs/PHASE1_RELEASE_STATUS.md` and `docs/PHASE1_ACCEPTANCE_MATRIX.md`.

## Strong evidence already present

- Case-centered FastAPI/SQLAlchemy domain and Next.js frontend.
- Firebase token verification and server-side organization membership resolution.
- VCF ingestion, reference-package metadata/checksum utilities, normalization/tool adapters, and explicit unsupported-variant errors.
- Resource registry/qualification/organization approval and resource provenance migrations.
- Durable workflow steps, dispatch outbox, partition lease/fencing, reanalysis models, and recovery schedules.
- Report versioning, review gates, audit events, artifact hashes, and export provenance.
- CI includes backend suite, PostgreSQL migration/concurrency integration, pinned bcftools 1.19 check, and frontend production build.

## Highest-priority unresolved gates

1. **Live end-to-end proof:** no current evidence in the inspected records demonstrates a fresh deployed case through upload → worker execution → persisted outputs → authorized review → report/export using production-like services.
2. **Scientific concordance:** repository documentation states independent transcript/annotation and ACMG/ClinGen correctness remain unvalidated; a reproducible benchmark acceptance dossier is still required.
3. **Variant-support truth table:** align actual validator, normalization, annotation provider and report behavior for SNVs, MNVs, indels, multiallelic records, symbolic alleles, breakends, SVs, GVCF blocks, phasing and sample genotypes. Accepted input must not be confused with fully analyzed input.
4. **Governed resource preflight:** verify the complete production path from organization-approved binding through deterministic resource plan, runtime adapter, fallback, stage provenance and safe blocking. Open PR #84 is not evidence of merged/validated behavior.
5. **Failure recovery:** exercise worker loss after claim, dispatch relay failure, stale dispatch reconciliation, lease expiry, queue outage, storage partial write and reanalysis retries against PostgreSQL/Redis/worker infrastructure.
6. **Tenant/security assurance:** current code-level controls exist, but adversarial cross-tenant API/storage/report/export tests and live configuration review are still required.
7. **Deployment readiness:** production secrets, object storage, ingress upload limits, backups/restores, monitoring, incident response and deployment revision provenance need evidence from the actual environment.

## Release decision

- Internal engineering: appropriate with normal development safeguards.
- Restricted research demonstration: only after data handling and live execution are checked; use non-sensitive benchmark data and explicit limitations.
- External research-laboratory pilot: HOLD pending live E2E, benchmark concordance, tenant isolation, operational recovery and support/retention documentation.
- Clinical workflow / patient-care use: HOLD pending intended-use definition, laboratory validation under the deploying laboratory's quality system, authorized clinical review/sign-out, and applicable jurisdictional/regulatory assessment.

See the companion audit documents in this directory for architecture, workflow, standards, threat model, validation, deployment, roadmap and release gates.
