# Target-state architecture and decision principles

## Target architecture

1. **Identity and policy plane:** verified identity, organization membership, role-based authorization, trial/plan entitlements, tenant quotas, audited administration and break-glass support.
2. **Case and artifact plane:** immutable source VCF, specimen/test context, checksums, upload limits, content-type/format validation, tenant-scoped storage and retention.
3. **Scientific execution plane:** deterministic workflow definitions; reference/build preflight; pinned normalization; versioned annotation and population adapters; stage-specific retry/failure classification; immutable outputs.
4. **Resource governance plane:** resource registry → integrity verification → technical qualification → organization approval → active binding → runtime resolution. Technical qualification and laboratory approval remain distinct.
5. **Evidence/interpretation plane:** source assertions and observations with identifiers, provenance and versions; criterion proposals linked to eligible evidence; human adjudication; versioned classification and reportability.
6. **Durable orchestration plane:** transactional dispatch intent/outbox, idempotent generation-fenced tasks, worker leases/heartbeats, reconciliation of orphaned work, bounded retries and explicit terminal states.
7. **Reporting plane:** draft, review, authorized sign-out, immutable report versions, amendments/supersession, export packages and provenance manifest.
8. **Operations plane:** structured logs without genomic payloads, metrics, traces/correlation IDs, health/readiness, capacity controls, backup/restore drills and incident procedures.
9. **Deployment profiles:** hosted multi-tenant and lab-controlled private deployment, using the same scientific contracts but different resource/storage/network policy.

## Decisions and trade-offs

- **Keep PostgreSQL authoritative for workflow state.** Redis/Celery transport is not the source of truth. Outbox + reconciler increases complexity but reduces lost-dispatch windows.
- **Prefer explicit resource plans over provider auto-selection.** Determinism and auditability outweigh silent convenience. If required resources are absent or ambiguous, block before dispatch.
- **Keep VCF normalization separate from variant identity/interchange models.** BCFtools normalization and any GA4GH VRS identifier generation solve related but distinct problems; do not treat a local canonical key as a VRS identifier.
- **Separate observation, evidence assertion, criterion proposal, expert decision and report authorization.** This reduces the risk of an API response or score being mistaken for clinical interpretation.
- **Use organization-scoped authorization at every object boundary.** A UUID or organization_id field alone is not proof of isolation.
- **Prefer lab-controlled resources for clinical deployments when licensing, data governance and intended use require it.** Remote APIs require explicit authorization, retention/egress review, release semantics and failure behavior.
- **Do not advertise unlimited uploads as a security control.** Application ceilings must be coordinated with ingress body limits, temporary disk, persistent storage, concurrency and tenant quotas.

## Required architectural invariants

- Original input artifacts are immutable and content-addressed by SHA-256.
- Every output references its analysis, exact input hash, workflow version, tool versions, reference build/package and resource snapshot.
- A rejected resource cannot be silently substituted. Fallback must be explicitly allowed and approved, with both requested and selected resource recorded.
- An unavailable required resource blocks; an unavailable optional resource is reported as a limitation.
- No task message or broker acknowledgement is treated as proof of completion.
- Retries are idempotent and fenced by dispatch generation/lease ownership.
- A signed-out report and historical analysis are never silently rewritten.
- A clinical classification cannot be finalized solely from unreviewed automated proposals.
- Cross-tenant access fails closed, including artifacts, reports, exports, queue status and resource management.
- Unsupported variant classes are explicitly represented as unsupported/review-required; no silent dropping.

## Architecture qualification still required

The target design is not yet a deployment claim. Validate transaction boundaries, concurrency semantics, resource execution identity, tenant isolation, storage consistency, operational capacity and recovery against PostgreSQL/Redis and real object storage.
