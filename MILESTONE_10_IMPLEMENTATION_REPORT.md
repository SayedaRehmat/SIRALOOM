# SIRALOOM Variant — Milestone 10 Implementation Report

## Scope

M10 adds first-class pedigree, inheritance and segregation support to the clinical interpretation workspace. The implementation is additive to M9 and does not replace the existing Case, Analysis, Variant, Evidence, ACMG/ClinGen, Review or Report domains.

## Implemented

- First-class `PedigreeMember` records per case.
- First-class parent→child `PedigreeRelationship` records.
- First-class per-analysis/per-variant `SegregationObservation` records for family genotypes, zygosity, phase and phenotype status.
- Version-independent, fingerprinted `InheritanceAssessment` snapshots so an interpretation can be reproduced against the exact family observations used at assessment time.
- Supported model contexts: autosomal dominant (AD), autosomal recessive (AR), X-linked, mitochondrial and de novo, with an explicit UNKNOWN option.
- Deterministic consistency engine returning `CONSISTENT`, `CONTRADICTED` or `INSUFFICIENT_DATA` rather than silently declaring a disease mechanism.
- Segregation context is persisted as `SEGREGATION` evidence with source/version and observation IDs.
- No automatic mapping from inheritance consistency to ACMG/ClinGen strength. Human review remains responsible for criterion applicability/strength.
- Tenant-scoped API endpoints for pedigree, segregation observations and inheritance assessment.
- M9 review bundle now exposes structured pedigree members/relationships, segregation observations and inheritance assessment history.
- Clinical Review Workspace can consume these structures without relying on opaque `clinical_context` JSON.

## API

- `GET /cases/{case_id}/pedigree`
- `POST /cases/{case_id}/pedigree/members`
- `POST /cases/{case_id}/pedigree/relationships`
- `GET /analyses/{analysis_id}/variants/{variant_id}/segregation`
- `POST /analyses/{analysis_id}/variants/{variant_id}/segregation`
- `POST /analyses/{analysis_id}/variants/{variant_id}/inheritance/assess`

## Scientific boundary

The engine is a review aid. It does not infer pathogenicity, establish a gene–disease relationship, or assign an ACMG/ClinGen evidence strength automatically. Family structure and genotype observations can support or contradict a proposed inheritance model, but incomplete family testing, phenotype uncertainty, de novo confirmation requirements, phase, penetrance, phenocopies and technical quality remain human-review considerations.

## Remaining validation boundary

M10 still requires production-infrastructure testing, real family/pedigree fixtures, laboratory-specific segregation policies and clinical validation before clinical use. No CLIA/CAP/ISO or diagnostic validation claim is made by this milestone.
