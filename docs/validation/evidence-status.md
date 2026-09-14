# SIRALOOM Variant — Evidence Layer Validation Status

**Milestone:** evidence construction and persistence
**Status:** implemented in development; not clinically validated

## Implemented

- Traceable evidence record domain model.
- Deterministic evidence fingerprints for idempotent creation.
- Analysis-scoped population observation lineage.
- Evidence construction from normalized annotation payloads.
- Population observation evidence.
- ClinVar assertion evidence preservation.
- Computational predictor observation preservation.
- Splicing predictor observation preservation.
- Consequence annotation facts.
- Provider ACMG assertion preservation as provider output, not final SIRALOOM classification.
- GET APIs for analysis-level and single evidence records.
- Explicit distinction between observation and interpretation.

## Deliberately not implemented

- Final ACMG/AMP classification.
- Criterion-specific ClinGen rule execution.
- Automatic PM2/BA1/BS1/PP3/PVS1 or other clinical criterion assignment.
- Clinical sign-out.
- Clinical validation.

## Validation performed

- Python compilation: PASS.
- Full test suite: PASS (16 tests).
- Evidence engine unit tests: PASS.
- Deterministic fingerprint test: PASS.
- Conflicting ClinVar assertion is represented as neutral evidence: PASS.
- Population evidence retains explicit resource/population provenance: PASS.
- Population observations are scoped to the analysis to prevent cross-reanalysis contamination: PASS.

## External validation gates remaining

- Current production GeneBe endpoint behavior.
- Current gnomAD release and schema for each supported adapter.
- ClinGen criteria/specification implementation against curated benchmark sets.
- Performance on large real-world VCFs.
- PostgreSQL/Celery/workflow integration in a Docker environment.
