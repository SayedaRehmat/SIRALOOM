# SIRALOOM Variant — Phase 1 Validation Status

## Current status

**Software/data-path implementation:** partial and unit-tested.

**Clinical validation:** not performed; no clinical-use claim.

## Validated in this development environment

- Python compilation: PASS
- Canonical variant identity tests: PASS
- FASTA `.fai` random-access tests: PASS
- Reference allele mismatch detection: PASS
- Reference-aware indel left-normalization tests: PASS
- Multiallelic splitting via BCFtools: basic genotype-bearing fixture passes in CI; it checks GT remapping, INFO Number=A values, FORMAT AD Number=R cardinality and PL Number=G cardinality. Expanded phase/multi-sample/missing-value qualification remains open.
- GeneBe response normalization fixture tests: PASS
- gnomAD INFO field parsing tests: PASS
- Current CI evidence: [GitHub Actions run 1043](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/37917001590) reports the backend suite, PostgreSQL migration/dispatch integration, and frontend production build as successful.

## Not yet validated

- live GeneBe API connection using a real account
- exact production gnomAD GraphQL schema/availability for every deployment dataset
- large-scale local gnomAD tabix performance on actual laboratory resources
- transcript correctness against an independent annotation truth set
- ACMG/ClinGen classification correctness
- clinical report correctness for clinical release
- production PostgreSQL/Redis/Docker deployment
- security/tenant isolation in production

## Scientific boundary

The current mainline workflow requires a qualified reference package and runs pinned BCFtools reference-aware normalization. Short-variant multiallelic records are split by `bcftools norm -m -any`; dedicated genotype-bearing golden fixtures are still needed to validate FORMAT/INFO allele-index remapping. The workflow explicitly rejects GVCF reference-confidence input and symbolic/breakend/SV records before normalization. See `docs/VARIANT_CLASS_SUPPORT.md` for the current scope and unvalidated boundaries.
## ClinGen specification selection validation
- Specification matcher tests: PASS
- Ambiguity fail-closed behavior: PASS
- Unvalidated specification exclusion: PASS
- Structural activation validation tests: PASS
- Alembic 0006 upgrade/downgrade smoke test: PASS

Clinical validation status remains: NOT CLAIMED.


## 2026-09-07 — Specification-aware ACMG integration

Implemented the binding between the ClinGen specification selector and the ACMG criterion evaluators.

### Behavior

- Select only `APPROVED_FOR_AUTOMATION` ClinGen specifications.
- Require an unambiguous gene/disease match.
- Stop with `AMBIGUOUS` when equally specific specifications tie.
- Stop with `REQUIRES_REVIEW` for alternative/point-based combination methods not yet implemented.
- Execute only registered, structured criterion evaluators.
- Persist the exact ClinGen provider/specification/version on each ACMG criterion assessment and classification snapshot.
- Keep automated results as `PROPOSED` and reviewable.
- Preserve missing population data as missing; never convert it to zero.
- Scope population lookups and duplicate checks to the current analysis.

### Current automated criteria bound to specification configuration

`PM2`, `BA1`, `BS1`, `PP3`, `BP4`, `PVS1`.

This remains a software decision-support implementation, not a claim of complete clinical ACMG/ClinGen automation or laboratory validation.

### Verification

- 41/41 pytest tests pass.
- Python compilation passes.
- Alembic migration chain passes on SQLite: upgrade to head, downgrade to base, upgrade to head.
- API route registration passes with required development settings.

### Environment limitation

Production PostgreSQL migration execution was not performed in this environment because the PostgreSQL `psycopg` driver is not installed. The migration chain was validated against SQLite only. No claim of PostgreSQL runtime validation is made.


## Milestone 3 ingestion status

Implemented in the recovered workspace: case intake UI, specimen registration, VCF/VCF.GZ/BGZ validation, explicit GRCh37/GRCh38 selection, TBI/CSI association, artifact SHA-256, validation metadata, tenant-scoped storage, and ingestion audit events. The primary uploaded artifact remains immutable.

Python validation in this workspace: 73 tests passing. Frontend production build remains environment-dependent and must be run with installed Node dependencies.


## 2026-10-09 — current-mainline support clarification

The original statements above about multiallelic rejection and the 12-test suite were historical and no longer describe the current mainline CI evidence. Current workflow behavior is defined by `backend/app/workflows/variant.py`, `backend/app/domain/vcf_tools.py`, and the explicit support matrix in `docs/VARIANT_CLASS_SUPPORT.md`. CI success is software test evidence only; independent scientific concordance and clinical validation remain unclaimed.


## 2026-10-09 — genotype-bearing multiallelic regression fixture

PR #137 added a BCFtools 1.19 fixture for a diploid `1/2` genotype and allele-indexed INFO/FORMAT fields. [CI run 37928636733](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/37928636733) passed backend, PostgreSQL integration and frontend jobs. This is bounded tool-level regression evidence, not independent scientific concordance or clinical validation.
