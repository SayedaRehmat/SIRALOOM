# SIRALOOM Phase 1 — Milestone 13 Implementation Report

## Milestone
**M13 — Large-file streaming, bounded-memory processing, and durable genomic partitions**

## Objective
Remove the principal scalability boundary identified in M8: the workflow previously materialized the complete normalized variant set in Python memory before downstream processing.

## Implemented

### 1. Streaming normalization boundary
- `normalize_vcf_file()` now supports `collect_variants=False`.
- M13 workflow uses this mode, so normalization writes the normalized VCF and retains only counters/metadata in memory.
- Existing callers/tests that expect `result["variants"]` remain supported through the backwards-compatible default.
- Added `iter_normalized_vcf()` for one-record-at-a-time canonical variant iteration.

### 2. Bounded variant batching
- Added `_iter_variant_batches()` in the workflow.
- Annotation now consumes a single streaming iterator and sends bounded GeneBe batches.
- The complete normalized variant list is no longer constructed.
- GeneBe batch size remains capped at 1000.

### 3. Durable partition manifest
- Added `AnalysisPartition` and migration `0018_analysis_partitions`.
- Partitions record:
  - analysis
  - workflow step
  - deterministic partition key
  - ordinal
  - record start/end
  - variant count
  - status
  - input artifact lineage
  - bounded variant-id manifest
  - metadata
- The normalization step creates a durable logical partition manifest over the normalized artifact.
- This is a **record/chunk partition**, not a claim of genomic-region partitioning.

### 4. Downstream memory hardening
- Population processing no longer loads every GeneBe annotation into memory at once.
- Evidence generation now queries annotations in bounded database batches and loads population observations only for the current batch.
- ACMG assessment already used checkpointed database batches; M13 removes its full annotation-row materialization as well.
- Direct gnomAD processing iterates the normalized VCF stream rather than a full variant list.

### 5. Recovery characteristics
- Existing annotation/evidence/ACMG checkpoint mechanisms remain intact.
- M13 keeps database commits before successful checkpoint transitions.
- A worker restart does not require rebuilding a Python-resident whole-genome variant list.

## Validation
- **111/111 backend tests passed.**
- Python compilation passed.
- Full Alembic SQLite replay passed.
- Migration head: `0018_analysis_partitions`.
- New M13 tests verify:
  - normalization can run without collecting variants
  - 1,200-record synthetic input is streamed as 500/500/200 bounded batches
- No live PostgreSQL, Redis, Celery, Firebase, or GeneBe execution was performed in this environment.
- No WES/WGS production throughput or memory benchmark is claimed from the synthetic unit test alone.
- Frontend production build was not run because frontend dependencies are not installed in this environment.

## Remaining scalability boundary
M13 removes the major **Python full-variant-list** memory boundary, but the workflow still performs database-backed per-variant operations in several places and the normalized VCF remains a single artifact. A later optimization can add physical/index-aware genomic region partitioning, bulk database operations, and distributed partition scheduling when real production infrastructure is available.

## Scientific/clinical scope
M13 changes execution architecture, not interpretation policy. It does not change ACMG/ClinGen decision rules, reportability policy, phenotype interpretation, pedigree assessment, confirmation policy, or clinical sign-out requirements.
