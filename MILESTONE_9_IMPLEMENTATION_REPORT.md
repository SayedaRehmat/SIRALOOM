# SIRALOOM Variant — Milestone 9: Clinical Review Workspace 2.0

## Objective

M9 adapts the existing Phase 1 review queue into the **case-first clinical interpretation workspace** defined after the SIRALOOM clinical-genomics research pass. The implementation is additive: it keeps the M8 review/classification/reportability/audit foundations and exposes the missing clinical decision context in one reviewer dossier.

## Clinical workflow represented in the workspace

1. Clinical question / indication
2. Positive and negative HPO phenotype observations
3. Phenotype-match and gene–disease context
4. Inheritance and pedigree context
5. Segregation evidence
6. Variant and annotation context
7. Global / regional / configured population observations
8. Technical QC context when supplied by the annotation provider
9. ClinVar / ClinGen / literature / functional-computational evidence when persisted
10. ACMG/AMP criterion review with evidence linkage
11. Classification governance
12. Clinical relevance / reportability
13. Confirmation and follow-up context
14. Sign-out gate and versioned reviewer history

## Scientific guardrails

- HPO phenotype is displayed as case relevance / disease-fit evidence and is **not silently converted into an ACMG pathogenicity criterion**.
- A triage/priority score remains distinct from pathogenicity classification.
- Literature records are shown with source context; a citation is not automatically an ACMG criterion.
- Population observations preserve availability semantics; missing local resources are not displayed as allele frequency zero.
- Classification approval remains a human governance action.
- Report finalization remains separately governed by the existing M6 reportability/finalization gates.
- The workspace does not claim clinical validation, accreditation, or regulatory certification.

## Backend changes

- `ReviewResponse` now exposes the case-level clinical context and variant-level interpretation dossier.
- Review service aggregates case HPO observations, clinical indication, inheritance/pedigree context, confirmation/follow-up context, annotations, population observations, contextual evidence, ACMG criteria, classification and reportability.
- Evidence is grouped into gene–disease, phenotype, literature, functional/computational and segregation context without changing their scientific meaning.
- Existing tenant-scoped review authorization and mutation endpoints remain in force.

## Frontend changes

The `/app/review` workspace now presents a structured clinical dossier rather than an evidence-only ACMG screen. It includes a reviewer-facing HPO entry control, phenotype chips, disease-fit evidence, inheritance/pedigree, population context, technical context, literature/functional evidence, ACMG review controls, reportability, confirmation/follow-up and sign-out/audit sections.

## Validation

- Python compilation: run during milestone build.
- Backend tests: to be run after implementation.
- Frontend production build: only claim if Node dependencies are available and the build actually completes.
- Live PostgreSQL/Redis/Celery/Firebase/GeneBe execution remains a separate deployment gate.

## M9 validation results

- Focused clinical-review tests: 19/19 passed.
- Full backend suite: 95/95 passed.
- Python compilation: PASS.
- Migration replay tests: 5/5 passed.
- Direct Alembic execution was not run against PostgreSQL because psycopg is unavailable in this environment.
- Frontend production build was not run because frontend/node_modules is absent.
- No live PostgreSQL/Redis/Celery/Firebase/GeneBe execution was performed.
