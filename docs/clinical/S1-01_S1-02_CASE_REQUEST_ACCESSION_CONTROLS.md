# S1-01 / S1-02: Case, Clinical Request and Accession Controls

**Status:** Implementation in progress on `feat/stage1-case-request-accession-20261110`.
**Scope:** Case identity, multiple clinical requests, external referrer provenance and verification, accession authority, and the boundary between accession and clinical attestation.
**Clinical qualification:** This specification describes software controls. It does not establish laboratory accreditation, clinical validity, or regulatory compliance.

## Governing decisions

1. A case may have multiple independent clinical requests.
2. External referrers do not need SIRALOOM accounts.
3. Referrer identity verification is required before ordinary request acceptance.
4. An exception is allowed only when an explicitly approved, current laboratory procedure permits it. The exception records the procedure identity/version, decision-maker, rationale, timestamp, and outstanding verification state. It never changes the referrer verification status to verified.
5. Accession authority is a separate, organization-scoped, assignable and revocable capability.
6. Clinical attestation is a separate capability and event; accession authority does not imply clinical authority.
7. Historical cases without sufficient evidence remain unreconciled. No request, verification, or acceptance is fabricated.
8. Request revisions, verifications, decisions, capability assignments/revocations, and attestations retain attributable history.
9. Existing SIRALOOM Variant SNV/small-indel interpretation scope is unchanged.

## Domain boundaries

- **Case:** organization-scoped laboratory record and accession identity.
- **Clinical request:** a particular requested examination associated with a case.
- **Request revision:** immutable snapshot of the referral and requested examination scope.
- **Referrer verification:** a separate attributable record of the laboratory's identity check.
- **Accession decision:** accept, reject, or request information against one exact request revision.
- **Capability assignment:** organization-scoped grant/revocation history for accession, referrer verification, clinical attestation, capability administration, and historical reconciliation.
- **Clinical attestation:** a distinct clinical action against an exact request/intake revision. It is not inferred from request acceptance.

## External referrer policy

A request records the referrer's stated name, professional role, organization, optional professional identifier, contact details, and referral channel. These are claims supplied by the referral source, not proof of identity.

Verification must record:
- status (verified / unable to verify / verification pending);
- method and verification date;
- evidence reference and concise outcome;
- verifier identity and timestamp.

Ordinary acceptance is blocked unless an applicable verification record is verified for the current request revision. A verification of an older revision is not automatically transferable to a materially changed revision.

### Approved-procedure exception

An exception requires a laboratory-controlled procedure record with a stable identifier, version, effective date, expiry where applicable, and a controlled procedure-document evidence reference. Registration creates PENDING_APPROVAL and does not make the procedure effective. A different authorized organization procedure authority must approve it, recording a separate approval-evidence reference; the submitter cannot approve their own procedure. Only APPROVED, currently effective, non-withdrawn procedures that explicitly permit an unverified-referrer exception may authorize that exception. The accession decision references the exact procedure version and includes a rationale. Procedure-document evidence and independent approval evidence are stored separately and preserved. Exception acceptance remains visibly distinct from verified-referrer acceptance; outstanding verification remains open and auditable.

## Capability and permission principles

- Case read/write grants do not grant accession, referrer-verification, clinical-attestation, capability-administration, or historical-reconciliation authority.
- Capabilities are scoped to one organization and one user.
- Grants record grantor, reason, creation time and optional expiry.
- Revocation records revoker, reason and time; it prevents future use but does not invalidate or erase historical actions.
- Users cannot grant or revoke their own capabilities.
- Capability administration is separate from clinical attestation. The initial grantor policy must be constrained to an approved organization-level administrative authority and must not infer clinical qualification.
- Every endpoint performs server-side authorization and tenant checks.

## Historical cases

Cases that predate this workflow and lack documentary evidence are marked `LEGACY_UNRECONCILED` by migration. New cases receive an explicit new-workflow state. A historical case is reconciled only by a separately authorized actor who records the source evidence, decision, reason, and timestamp. Reconciliation appends evidence; it does not invent a historical request or overwrite prior case/report history.

## Revision and decision rules

- Only a submitted request revision may be assessed.
- Every accession decision references the exact revision assessed.
- A request may have multiple revisions and decisions, but concurrent decisions must serialize; contradictory terminal decisions cannot both succeed.
- A material revision after acceptance requires reassessment before further clinical processing.
- Materiality must be explicit and versioned; at minimum it includes requested examination/scope, specimen identity, clinical indication/question, and any field the laboratory's approved accession procedure designates as critical.
- A new request under the same case receives no inherited acceptance.
- Rejected requests cannot enter the normal analysis path.
- Clinical attestations reference the exact request and clinical-intake revisions reviewed.

## Required acceptance tests

### Case and request identity
- Multiple requests can coexist under one case.
- Request identifiers are unique within their defined organization/case scope.
- Requests cannot be attached to a case in another tenant.
- Request revisions are append-only, ordered, and uniquely fingerprinted.
- Repeated submission is idempotent where the request contract defines it.
- Concurrent revision/decision attempts cannot create duplicate versions or contradictory decisions.

### External referrer verification
- External referrers can be recorded without SIRALOOM user accounts.
- Stated identity is never represented as verified merely because it was submitted.
- Ordinary acceptance is blocked while verification is pending, absent, or unsuccessful.
- Verification requires method, evidence reference, verifier, and timestamp.
- Verification must apply to the current request revision.
- Unauthorized users cannot verify a referrer.
- An exception cannot be used without an approved, current, in-scope procedure version.
- Exception decisions require rationale and authorized decision-maker.
- Exception status remains distinct from verified status and outstanding verification remains visible.
- Verification and exception history cannot be silently overwritten.

### Accession capabilities
- Case writers cannot accept/reject requests unless separately assigned the accession capability.
- Capability grants are organization-scoped and cannot be self-granted.
- Unauthorized users cannot grant or revoke capabilities.
- Expired/revoked grants cannot authorize new actions.
- Revocation preserves historical attribution.
- Stale token role claims cannot override current organization membership or capability state.

### Procedure approval separation of duties

- Procedure registration is pending and cannot authorize an exception.
- Any legacy procedure previously marked approved without independent approval is returned to pending approval during migration; no old single-person approval is grandfathered.
- The procedure submitter cannot approve the same procedure version.
- Approval requires a distinct evidence reference and is audited.
- Procedure document evidence is never overwritten by approval evidence.
- Withdrawal is audited and prevents future exception use.
- Downgrade must refuse to discard pending or approved procedure history.

### Clinical attestation
- Accession capability alone cannot create clinical attestation.
- Clinical attestation requires its own capability.
- Attestation records actor, action, rationale, timestamp and exact revisions.
- Case access administrators are not automatically clinical attestors.

### Historical reconciliation and preservation
- Existing cases without evidence are marked unreconciled; no synthetic request or acceptance is inserted.
- Unreconciled cases cannot pass new clinical readiness gates solely due to legacy case status.
- Reconciliation requires evidence and separate authority.
- Historical decisions, reports, audit records and request revisions are not deleted or rewritten.
- Cross-tenant access attempts return non-disclosing not-found responses.

### Database and integration
- Migration preserves existing case, intake, report and audit data.
- PostgreSQL integration tests cover uniqueness, locking, tenant isolation and concurrent decisions.
- Migration downgrade refuses to discard request/decision/capability history.
- API tests verify authentication and authorization on every write route.
- Full backend, PostgreSQL, frontend and deployment-image CI must pass on the exact PR head.

## Existing repository work and dependencies

- PR #247 adds referral provenance fields to the existing case-level clinical-intake JSON. It is open and based on an older main commit. This implementation must not duplicate those fields or silently merge that PR. Request-level referrer identity/verification remains a distinct concept.
- PR #220 documents the broader genomic laboratory workflow and SIRALOOM boundary. It is an open documentation PR and should be treated as contextual work, not as proof of implemented controls.
- Main currently includes migration revision `0061_analysis_toolchain_profiles`. Before adding a migration, check all current open branches/PRs for competing revision IDs and establish the correct parent.
- The existing `ClinicalIntakeRevision` is retained. Request revisions should reference it where appropriate rather than creating a competing clinical-intake model.

## Implementation and release gates

Implementation is staged into small changes: persistence/migration, request and verification API, capability administration and enforcement, clinical-attestation boundary, historical reconciliation/readiness integration, then tests and documentation.

No change in this branch is a clinical validation claim. Do not use real patient data or production clinical workflows until the laboratory has approved its procedures, qualified the complete workflow, and independently reviewed the implementation and validation evidence.
