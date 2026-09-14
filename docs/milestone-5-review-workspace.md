# SIRALOOM Variant — Milestone 5: Clinical Review Workspace

## Scope

Milestone 5 turns the existing versioned review service into a dedicated reviewer-facing interpretation workspace. It does not replace automated ACMG assessment or the scientific pipeline.

The workflow is:

`Completed analysis → review queue → variant context → evidence/population → ACMG criteria → reviewer decision → versioned history`

## Review queue

`GET /api/v1/analyses/{analysis_id}/review-queue`

Supported filters:

- `status`
- `classification`
- `chromosome`
- `reportability`
- `limit`
- `offset`

The queue resolves the latest classification version per variant and returns interpretation context counts plus normalized annotation fields when available. It is tenant-scoped through the existing Case → Organization authorization dependency.

## Review mutations

Existing versioned endpoints remain authoritative:

- start review
- review an ACMG criterion
- approve classification
- request more evidence

Every mutation records reviewer identity, reason, before/after state, expected/resulting version, and an audit event.

### Evidence integrity

When a reviewer links evidence to an ACMG criterion, SIRALOOM now verifies every selected evidence record belongs to the same `analysis_id` and `variant_id`. Cross-variant or cross-analysis evidence references are rejected.

## Frontend

The authenticated application now exposes `/app/review` as the dedicated Clinical Review Queue. The interface provides:

- queue filtering
- variant selection
- classification/review/reportability status
- population context
- evidence context
- ACMG criterion cards
- reviewer strength and rationale controls
- evidence linking
- accept/modify/reject actions
- classification approval
- request-more-evidence action
- versioned review history

The existing `/app/workspace` remains available as the broader case/analysis workspace.

## Security

The review queue is read-only. Mutation endpoints continue to enforce reviewer roles and case-derived tenant access. Evidence retrieval is now explicitly analysis/case authorized.

## Validation

Backend test suite: **80 passed** in the development environment.

Frontend production build remains environment-dependent and must be executed after installing the declared Next.js dependencies.
