# SIRALOOM Phase 1 — Milestone 4 Implementation Report

## Scope

Milestone 4 establishes the durable, asynchronous scientific execution foundation for the existing SIRALOOM Variant workflow:

`validated VCF → normalization → GeneBe annotation → population evidence → evidence construction → ACMG/ClinGen assessment → human review required`

The existing scientific modules were preserved. This milestone does not claim clinical validation and does not turn GeneBe into a clinical/diagnostic provider.

## Implemented

### Durable analysis queue identity
- Added `analyses.queue_task_id` through additive migration `0012_durable_analysis_queue`.
- Repeated start requests for an already queued/running analysis are idempotent when a queue task identity exists.
- Analysis status API now exposes the persisted queue task ID.

### GeneBe resilience
- Added authenticated-provider retry handling for transient HTTP/network failures.
- Retryable conditions: HTTP 408, 429, and 5xx plus transport errors.
- Honors `Retry-After` when supplied; otherwise uses bounded exponential backoff.
- Non-transient 4xx errors are not retried.
- Credentials remain server-side.
- Batch size is capped at 1000 even if misconfigured above the provider limit.

### Durable annotation checkpoints
Each GeneBe batch is persisted in `workflow_steps.metadata_json.batches` with:
- start/end offsets
- status
- attempt
- timestamp
- provider
- variant count
- returned/new annotation counts
- transient error state where applicable

The workflow commits annotation rows before marking a batch successful. A worker restart can therefore reconcile persisted rows and skip completed batches rather than restarting the entire annotation operation.

### Worker retry behavior
- Transient GeneBe failures move the batch to `RETRYING` and raise a dedicated `TransientWorkflowError`.
- Celery retries the durable analysis task.
- The workflow's outer exception handler no longer converts a transient retry into a permanent analysis failure.
- Analysis task completion returns the actual persisted analysis status.

### Real scientific sequence preserved
The existing workflow remains:

1. input validation
2. reference-aware normalization
3. authenticated GeneBe annotation
4. population observations (GeneBe global and optional gnomAD MID)
5. traceable evidence construction
6. specification-aware ACMG/ClinGen assessment
7. `REQUIRES_REVIEW`

### Frontend
- Existing server-side workflow polling remains intact.
- Annotation checkpoint progress is now displayed when checkpoint metadata is available.
- The UI explicitly communicates that workflow state is server-persisted.

## Important limitations that remain

1. The current normalization implementation returns canonical variants in memory; it is not yet a fully streaming, constant-memory pipeline for very large VCFs.
2. Population, evidence, and ACMG loops remain durable at the workflow-step level but do not yet have the same fine-grained per-batch checkpoint granularity as GeneBe annotation.
3. Cloud/object-storage production execution still requires deployment validation against a real environment.
4. Celery/Redis production execution was not run in this build environment.
5. Frontend production build was not run because frontend dependencies are not installed in the workspace environment.
6. GeneBe remains a development/research provider and must not be represented as a clinically validated diagnostic resource.
7. Clinical laboratory validation, regulatory/accreditation validation, and site-specific SOP validation remain outside software implementation.

## Validation actually executed

- Python compilation: successful for changed Python modules.
- Automated Python suite: **76 passed**.
- No test result is claimed for frontend production build.
- No real GeneBe API call was made and no GeneBe credentials are stored in the repository.
- No claim is made that a production Redis/Celery/Firebase environment was exercised.

## Changed files

- `backend/app/config.py`
- `backend/app/adapters/annotation/genebe.py`
- `backend/app/application/analysis.py`
- `backend/app/api/v1/analyses.py`
- `backend/app/infrastructure/db/models.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `backend/app/workflows/variant.py`
- `frontend/app/(app)/app/workspace/page.tsx`
- `.env.example`
- `migrations/versions/0012_durable_analysis_queue.py`
- `tests/test_genebe_retry.py`
- `MILESTONE_4_IMPLEMENTATION_REPORT.md`

## Next recommended milestone

Milestone 5 should focus on the clinical review workspace and complete end-to-end integration testing around:

`analysis → variant/evidence review → classification review → reportability → clinical report → analytical report → audit/history`.

Before production claims, add deployment/E2E testing and complete durable checkpointing for population/evidence/ACMG stages.
