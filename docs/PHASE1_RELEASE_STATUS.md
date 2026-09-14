# SIRALOOM Variant — Phase 1 Release Status

## Release candidate

**Service:** SIRALOOM Variant  
**Boundary:** VCF → validated/normalized/annotated/evidence-aware/reviewed/reportable result  
**Current milestone:** M15 — Phase-1 release and deployment validation gate  

## What the research-driven model required

The clinical-laboratory research model established that Phase 1 is not merely a VCF annotation script. The Case is the permanent root, and the service must preserve specimen/test context, phenotype, population evidence, literature, inheritance/segregation, technical QC, human review, reportability, confirmation/follow-up governance, reporting, audit and provenance.

That model is implemented across M1–M14. The system now contains the major tertiary-analysis and clinical-review workflow required for the Phase-1 boundary.

## Implemented software scope

- Case/organization/user authorization foundation
- Specimen and VCF artifact ingestion
- VCF structural validation and explicit GRCh37/GRCh38 selection
- Reference-aware normalization and canonical variant identity
- Bounded-memory streaming and durable analysis partitions
- Resource-aware partition leases, retries and recovery controls
- GeneBe provider adapter with batch limits, response matching and provenance
- Global population context and optional gnomAD Middle Eastern (`MID`) context
- Missing-resource semantics distinct from AF=0
- Evidence model with source/version provenance
- HPO phenotype observations and phenotype matching as decision support
- Gene–disease and literature context evidence
- Pedigree, inheritance and segregation context
- Assay and technical QC observations/gates
- ACMG/AMP + ClinGen-oriented assessment infrastructure
- Versioned human review and reviewer rationale/history
- Clinical reportability decisions separated from pathogenicity classification
- Confirmation, follow-up and secondary-finding governance
- Clinical and complete analytical reports
- Audit/provenance and artifact SHA-256 lineage
- Exportable case/report/provenance artifacts
- English/Arabic foundation
- Production-oriented Docker, readiness probes and durable worker configuration

## What this release does NOT claim

Passing the automated suite, processing a public benchmark VCF, or deploying the software does **not** establish clinical validity, clinical sensitivity/specificity, accreditation, regulatory authorization, or suitability for patient care. A deploying laboratory must validate the complete intended assay/workflow under its own quality system and jurisdictional requirements.

GeneBe remains a research/educational, non-commercial development provider in this configuration and is not a clinical diagnostic provider. It must not be represented as a clinical validation of SIRALOOM.

## Remaining Phase-1 validation gates

1. Live PostgreSQL + Redis + worker execution.
2. Production Firebase Authentication and tenant authorization.
3. Production artifact storage and secret management.
4. Real permitted GeneBe API execution with server-side credentials.
5. Real public benchmark VCF end-to-end through the deployed UI.
6. Benchmark/scientific validation against predefined expected outputs.
7. Frontend production build in the actual deployment environment.
8. Failure/retry/recovery and multi-user tests on deployed infrastructure.
9. Final requirement → implementation → test → validation traceability matrix.

These are validation/release gates, not excuses to add unrelated Phase-1 features.
