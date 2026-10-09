# Threat model and tenant-isolation assessment — initial

## Assets

Genomic VCFs and derived annotations; case/specimen metadata; evidence and interpretation decisions; reports/exports; resource packages and licensing; user identities and organization memberships; API/provider secrets; audit records; workflow/queue state; backups.

## Trust boundaries and threat actors

Boundaries include browser/API, identity provider/backend, tenant/shared database, API/worker, worker/resource storage, external providers, and hosted operator access. Threat actors include unauthenticated internet users, malicious or compromised tenant users, compromised credentials, malicious uploaders, compromised workers/dependencies, and privileged insiders.

## Primary attack scenarios and required controls

| Threat | Required control | Verification evidence |
|---|---|---|
| Cross-tenant case/artifact/report/export access | Server-side tenant predicate for every read/write/download; deny by default | Two-tenant adversarial API tests using guessed UUIDs and indirect references |
| Role escalation or unauthorized sign-out | Central role/permission checks; separation of reviewer/approver where policy requires | Negative role matrix; audit trail; concurrency tests on review state |
| Malicious VCF/compression bomb | Ingress limits, bounded streaming/decompression, timeouts, parser limits, temp-disk quotas | Oversized, truncated, deeply malformed and high-expansion fixtures; resource exhaustion tests |
| Path traversal / unsafe filenames | Basename normalization, generated storage keys, no user-controlled filesystem path | Fuzzed filenames and storage-key tests |
| Command injection via resource configuration | Argument arrays, no shell, strict executable/argument allowlists, resource-admin authorization | Adversarial resource contract tests and command construction inspection |
| SSRF / malicious remote resource URL | HTTPS/host allowlist or governed provider registry, redirect/IP protections, egress policy | DNS/IP/redirect and private-address test cases |
| Secret exposure | Secret manager/runtime env; redact logs and errors; no public frontend env | Repository secret scan, built frontend inspection, logs/error tests |
| Artifact tampering / partial writes | SHA-256 verification, atomic publication, immutable source, reconciliation | Corrupt/truncated upload and worker-download tests |
| Queue/task spoofing or replay | Persisted dispatch intent, generation fence, idempotency, authorization on task-status APIs | Duplicate delivery, stale generation, worker-loss integration tests |
| Audit tampering or missing events | Append-only/controlled audit writes, transaction coupling where appropriate, external retention policy | Mutation/rollback tests and audit reconstruction |
| Denial of service / noisy neighbor | Per-tenant quotas, ingress concurrency caps, queue fairness, storage capacity alarms | Load tests and tenant quota bypass tests |
| Backup exposure or failed restore | Encryption, least privilege, retention, tested restore and key recovery | Recorded restore drill against stated RPO/RTO |

## Existing controls observed in code/docs

Firebase ID tokens are verified server-side; organization membership is resolved from the database; case/artifact routes contain tenant checks; Firestore/Storage rules are documented as default-deny; server secrets are documented as server-only; artifact SHA-256 and worker-download integrity checks have recent commits; durable dispatch and partition lease mechanisms exist.

These are code/documentation observations, not proof that every route, deployment secret, storage rule, log stream or backup is secure.

## Release-blocking tests

- Two-organization matrix covering case, specimen, artifact, analysis, workflow status, resource, review, report, download and export endpoints.
- Expired/revoked/invalid Firebase token and removed-membership cases.
- Cross-tenant artifact index pairing and storage profile manipulation.
- Malicious VCF, compressed payload, filenames, resource URLs and provider response.
- Trial limit, quota race, upload cap and concurrent upload pressure.
- Queue task replay, stale dispatch generation, worker crash and orphan reconciliation.
- Audit consistency for failed and rolled-back operations.
- Production configuration review for public variables, credentials, TLS, ingress and storage permissions.

Residual risk cannot be considered accepted until a named owner documents the risk, compensating controls, and approval appropriate to the intended use.
