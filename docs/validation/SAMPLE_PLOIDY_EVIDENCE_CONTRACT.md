# Specimen ploidy evidence and caller policy contract

## Why this is required

The existing SIRALOOM data model has case-level specimens and pedigree members with a \`sex\` field, but no dedicated, typed, provenance-backed specimen ploidy assessment. Pedigree sex is not a karyotype and must not be converted into chromosome copy number. VCF GT establishes the number of alleles encoded in that call; it does not establish the biological copy number expected for the specimen.

The existing VCF validator derives FORMAT \`Number=G\` cardinality from each sample's GT ploidy. That is a structural VCF check. Whether the GT ploidy is consistent with the specimen and the validated caller/assay is a separate qualification check.

## Contract implemented

This change adds a pure domain contract and resolver. It does not yet persist evidence in the database or connect it to the VCF workflow.

### Specimen-level evidence

A versioned evidence object is scoped to a specimen UUID and exact reference build. It contains explicit integer copy-number assertions for:

- \`PAR\`: total copy number across the homologous pseudoautosomal region.
- \`X_NON_PAR\`: X-specific non-PAR copy number.
- \`Y_NON_PAR\`: Y-specific non-PAR copy number.

Every VERIFIED assertion requires:
- Evidence source type.
- Traceable evidence reference (for example, a controlled artifact/LIS reference; do not embed raw clinical documents).
- Reviewer identity.
- Timezone-aware review timestamp.
- Exact assembly identity (GRCh37 or GRCh38 family).

Evidence status can be VERIFIED, UNVERIFIED, CONFLICTED, or MOSAIC_OR_COMPLEX. Only VERIFIED evidence is eligible for resolution. Missing, complex, or conflicted evidence remains unresolved.

The schema rejects unrecognized fields. It does not accept \`sex\`, \`karyotype\`, GT, or allele balance as ploidy evidence.

### Caller/assay policy

A separate policy is bound to exact caller ID, caller version, assay ID, policy version, and reference build. It maps an explicit region copy number to either:
- A positive expected GT ploidy, or
- \`NOT_CALLABLE\`, for a region/copy-number combination where that caller/assay does not emit a genotype.

A policy is usable only when its status is QUALIFIED and it carries validation evidence, a qualified-by identity, and a timezone-aware qualification timestamp. A different caller version, assay, assembly, or unsupported copy-number mapping does not inherit the policy.

### Resolver behavior

\`resolve_expected_gt_ploidy\` returns one of:
- \`RESOLVED_CALLABLE\`: expected GT ploidy is explicit and supported by the exact qualified caller policy.
- \`RESOLVED_NOT_CALLABLE\`: the exact policy declares the region/copy-number combination non-callable.
- \`UNRESOLVED\`: evidence/policy is absent, unverified, conflicted, malformed, mismatched, or unsupported.

It never guesses. It is intentionally not called by the VCF workflow yet.

## Important limitations

1. This is a domain contract, not yet a persisted database entity or user-facing intake workflow.
2. PAR copy number is represented as one combined region because X and Y PAR sequences are homologous; representation/duplicate handling remains caller- and reference-package-specific.
3. Mosaic/complex states are explicitly unresolved; a single integer copy number is insufficient.
4. Mitochondrial ploidy and heteroplasmy are outside this sex-chromosome contract.
5. Caller policies must be built from actual versioned assay validation evidence. Test fixtures are software tests, not clinically qualified production policies.
6. Before workflow enforcement, persist immutable evidence revisions, audit who entered/reviewed them, bind them to the specimen and assay, and include exact policy/evidence versions in analysis provenance.

## Standards and scientific basis

- GA4GH/HTS VCF v4.5 defines genotype representation and likelihood ordering; GT allele count informs per-sample genotype ploidy and FORMAT \`Number=G\` cardinality. It does not define a patient's karyotype or a laboratory's assay-specific expected ploidy policy.
- ACMG NGS technical standards require sample/data integrity monitoring and validation of the complete assay/pipeline for its intended use.
- The Genome Reference Consortium defines build-specific human PAR intervals; region classification must use the exact reference assembly.

## References

- GA4GH/HTS VCF specification: https://samtools.github.io/hts-specs/VCFv4.5.pdf
- ACMG 2021 NGS technical standard: https://www.nature.com/articles/s41436-021-01139-4
- GRC human assembly/PAR definitions: https://www.ncbi.nlm.nih.gov/grc/human
- Ensembl human PAR definitions: https://www.ensembl.org/info/genome/genebuild/human_PARS.html


## Persistence and authenticated specimen intake (PR #271)

The specimen evidence contract is persisted as append-only revisions in
`specimen_ploidy_evidence_revisions`. Each row is bound to one specimen UUID
and contains a monotonically increasing specimen-local version, schema version,
normalized reference build, explicit region copy-number assertions, evidence
source/reference, reviewer identity/time when verified, recording identity/time,
a content fingerprint, and a unique audit-event reference.

Authenticated API routes:

- `POST /api/v1/cases/{case_id}/specimens/{specimen_id}/ploidy-evidence`
  appends a new evidence revision.
- `GET /api/v1/cases/{case_id}/specimens/{specimen_id}/ploidy-evidence`
  returns the ordered revision history.

A VERIFIED submission requires the case-level review permission and an
authorized review role. The API derives `reviewed_by` from the authenticated
principal and `reviewed_at` from the server clock; clients cannot nominate a
reviewer or backdate the review. Non-verified statuses require case write
permission and remain unresolved by the ploidy resolver.

The evidence row and its hash-chained audit event are committed in one database
transaction. The audit record captures the revision number, build, status,
region copy-number assertions, evidence reference, and reviewer attestation.
The database enforces unique specimen/version and specimen/fingerprint keys,
a unique audit-event link, VERIFIED provenance constraints, and append-only
UPDATE/DELETE triggers. Corrections are represented by a new revision; existing
revisions are not edited or deleted through the application.

The API stores only a traceable evidence reference, not the underlying clinical
document. The referenced source must remain governed by the laboratory's
controlled document/LIS retention and access process.

This persistence layer does not yet persist or qualify caller/assay policies,
does not invoke the ploidy resolver during VCF validation, and does not enforce
expected GT ploidy in the production workflow. Those are explicit downstream
integration gates, not implied by evidence intake.


## Caller/assay policy registry (PR #272)

Caller policies are persisted separately from specimen evidence in
`caller_ploidy_policy_revisions`. Each immutable revision is bound to the
assay UUID, exact caller ID and version, policy version, reference build,
qualification status, validation-evidence reference, region-copy-number to
GT-ploidy mapping, recording actor/time, and a unique audit event.

Authenticated API routes:

- `POST /api/v1/assays/{assay_id}/ploidy-policies` appends a policy revision.
- `GET /api/v1/assays/{assay_id}/ploidy-policies` returns the assay's policy history.

DRAFT policy registration requires an assay-management role. QUALIFIED and
RETIRED submissions require a review role. For QUALIFIED policies, the API
derives the qualifying reviewer from the authenticated principal and records
the server-generated timezone-aware qualification timestamp. The client cannot
supply or backdate the qualification attestation.

An exact assay/caller/caller-version/policy-version/reference-build/status
identity is immutable. Changed content requires a new policy version. DRAFT,
QUALIFIED, and RETIRED states are separate append-only records; only QUALIFIED
policies are eligible for the resolver. Database constraints and UPDATE/DELETE
triggers protect the revision history, and the policy record is transactionally
linked to the hash-chained audit event.

This registry does not itself establish clinical qualification. The referenced
validation dossier must contain laboratory evidence appropriate to the assay
and intended use, including documented validation scope, expected genotype
encoding, performance characteristics, approval and effective version. The
registry does not yet select a policy for an analysis or enforce it during VCF
validation; production workflow binding and enforcement remain a separate
integration gate.
