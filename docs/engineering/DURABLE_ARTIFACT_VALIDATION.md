# Durable artifact validation

## Scope

This document describes the asynchronous intake-validation boundary introduced by migration
`0062_artifact_validation_dispatches`. It covers primary VCF structural validation and uploaded
TBI/CSI concordance validation. It does not claim clinical validation, accreditation, or regulatory
conformity.

## Request and persistence boundary

`POST /cases/{case_id}/artifacts` performs authorization, tenant/case checks, filename and
build declaration checks, upload-size/capacity checks, request fingerprinting and durable byte
storage. It does not invoke BCFtools or classify VCF/index validity.

The API creates the Artifact row with `validation_status=PENDING` and creates one
`ArtifactValidationDispatch` in the same database transaction. The dispatch stores the
organization, case and artifact identities and an immutable BCFtools/HTSlib profile snapshot.
The upload idempotency reservation remains the stable HTTP retry identity.

A successful HTTP response means **the bytes and validation request were durably accepted**. It
does not mean that the VCF has passed scientific validation or is eligible for analysis.

## State model

### Dispatch state

- `PENDING`: committed outbox record, not yet published.
- `PUBLISHED`: broker publication recorded with a deterministic task ID.
- `RUNNING`: a worker has claimed the dispatch.
- `RETRYING`: a transient execution failure is being retried by Celery.
- `COMPLETED`: validation completed, whether the input was valid or invalid.
- `FAILED`: execution could not complete after a non-retryable failure or bounded retries.

The periodic relay runs every 15 seconds. It publishes to the exact queue captured in the
dispatch profile. The task ID is the dispatch ID. The relay commits the task identity before
publishing so a fast worker cannot observe an uncommitted dispatch. If the broker reports
`PENDING` for more than three minutes, the relay republishes the same task ID; this is a
conservative recovery heuristic, not proof that the original message was lost.

### Artifact state

- `PENDING`: no validation decision has been made.
- `VALID`: structurally valid sample-bearing VCF with required specimen/sample mapping.
- `VALID_SITE_ONLY`: structurally valid sites-only VCF; not eligible for sample-level analysis.
- `INVALID`: scientific/file validation completed and rejected the input.

A dispatch failure leaves the artifact `PENDING`. It must never be interpreted as valid or invalid
input. The workspace exposes the dispatch failure and stops polling that terminal dispatch.

## Worker responsibilities

The worker:

1. Verifies dispatch, artifact, case and organization identities.
2. Verifies the stored artifact SHA-256 and byte size before reading it.
3. Stages data under the configured worker scratch directory.
4. For VCFs, runs the existing strict parser and BCFtools structural check, then applies explicit
   specimen/sample mapping and declared-build consistency checks.
5. For indexes, requires the paired primary VCF to have passed validation, verifies both stored
   artifacts, then runs the existing TBI/CSI structure and indexed-record concordance checks.
6. Persists validation metadata, artifact status, case intake status and an audit event.

The worker checks the exact BCFtools/HTSlib profile persisted by the API. A worker with a
different profile rejects/requeues the task rather than silently substituting its installed binary.

## Recovery and idempotency

- Duplicate HTTP requests with the same idempotency key and request fingerprint return the
  existing artifact identity.
- Artifact bytes and dispatch intent commit together.
- Broker publication uses a deterministic task ID.
- Celery late acknowledgement and worker-loss rejection enable broker redelivery.
- If the artifact validation transaction committed but dispatch completion did not, redelivery
  observes the non-PENDING artifact and completes the dispatch without revalidating or rewriting
  the scientific decision.
- Transient BCFtools unavailability, timeout and worker scratch/storage I/O failures use bounded
  Celery retries. They do not turn the artifact into `INVALID`.

## Case readiness

A case with pending primary VCF validation is `VALIDATING`, unless a previously validated
sample-bearing VCF already keeps it `READY_FOR_ANALYSIS`. When validation completes, readiness
is recomputed from all persisted primary VCFs. An optional index upload does not change primary
VCF readiness.

## Remaining qualification gates

This implementation is a software architecture change, not proof of production or clinical
readiness. Before merge/release, qualify:

- PostgreSQL migration upgrade/downgrade and dispatch identity immutability.
- Concurrent uploads, duplicate HTTP retries and transaction rollback/compensation.
- Worker crash before validation, during validation, and after validation commit but before
  dispatch completion.
- Broker outage, delayed delivery, duplicate publication and bounded retry exhaustion.
- Valid/invalid VCFs, sample mapping, build declaration mismatch, BGZF indexes, stale indexes,
  per-contig count/digest disagreement and storage-integrity failures.
- Tenant isolation across artifact bytes, dispatch records, logs and API reads.
- Frontend pending/valid/invalid/terminal-dispatch behavior.

The API image still contains the default BCFtools installation because the API and default worker
currently share a Dockerfile. The upload route no longer calls BCFtools, but removing it from the
API image requires a separate tool-free API image and a full runtime executable audit.

A terminal `FAILED` dispatch currently requires operator reconciliation or a new upload; a
laboratory-facing retry/reconciliation operation is a follow-up requirement. No clinical sign-out
or result is produced by this validation stage.
