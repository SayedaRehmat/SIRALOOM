# Family member, specimen and VCF sample identity contract

**Status:** implementation in progress; not qualified for clinical inference.

## Scope

This contract binds a case-scoped pedigree member to a specimen, a specific source VCF artifact, a specific analysis, and the exact VCF sample-column name selected by that analysis. It is an identity/provenance contract only. It does not calculate segregation, inheritance compatibility, pathogenicity, or ACMG/ClinGen evidence.

## Existing behavior retained

- Specimen intake accepts `vcf_sample_name` and stores it in specimen metadata. This remains an intake hint only.
- An analysis selects one VCF sample through `analysis.configuration.vcf_sample_name` and pins its source artifact through `analysis.configuration.input_artifact_id`.
- Normalization persists the selected sample's per-variant calls in `AnalysisPartition.metadata_json.sample_calls`. Normalized partitions reference the normalized artifact, not the original source VCF. The original source artifact therefore must be obtained from the analysis configuration; it must not be confused with `AnalysisPartition.input_artifact_id`.

## Binding record

Migration `0063_pedigree_sample_identity_bindings` adds `pedigree_sample_bindings` with:

- case, pedigree member, specimen, analysis and source artifact IDs;
- exact VCF sample name and immutable source-artifact SHA-256 digest;
- binding method and optional external evidence reference;
- immutable source-artifact SHA-256 digest;
- status `UNVERIFIED`, `VERIFIED` or `REJECTED`;
- version and superseded-binding pointer;
- recorder and reviewer provenance, review reason and timestamp;
- deterministic fingerprint and lookup indexes.

Rows are immutable at the database level. Review creates a new version linked to the previous row; it does not overwrite the original claim. Downgrade refuses to discard any binding history.

## API behavior implemented

- A write-authorized user can record an `UNVERIFIED` binding only when the member and specimen belong to the case, the analysis and source artifact belong to the same case, the artifact is a VCF source, and the artifact is the exact source artifact selected by the analysis.
- A specimen's optional registered sample-name hint must not conflict with the binding's sample name.
- A reviewer can append a `VERIFIED` or `REJECTED` version with a mandatory reason. Binding creators cannot approve their own claims.
- Verification re-fetches the source artifact and checks its SHA-256 against the recorded digest, requires the analysis configuration to select that same source artifact and sample name, requires the successful normalization workflow step to name that source artifact in its inputs, and requires persisted normalized calls containing the exact sample name.
- Verification additionally requires exactly one reviewer-accepted PASS `CHAIN_OF_CUSTODY` record and exactly one reviewer-accepted PASS `SAMPLE_IDENTITY_QC` record. Evidence records include method/version, evidence reference, optional source artifact and metrics; review/correction creates append-only successor revisions.
- Creation and review retries are idempotent under the case-row lock; the database permits at most one successor revision for a binding or evidence record.
- A missing call remains missing. This endpoint does not synthesize reference genotypes or create genotype evidence.

## Important limitations before inheritance integration

1. The current analysis model selects one sample per analysis. Family members may therefore require separate analyses; no family-level analysis aggregate exists yet.
2. Verification that the sample name appears in normalized calls is not proof of biological identity. A laboratory identity method (for example, validated fingerprint/relatedness testing and chain-of-custody) must be captured and reviewed under the organization's SOP before a binding can support de novo or segregation interpretation.
3. This first implementation does not yet enforce a single active verified binding for every member/specimen/assay combination, provide a binding-list endpoint, or implement correction/replacement UX.
4. Existing specimen metadata values are not silently migrated into verified bindings. They remain unverified hints until explicitly reconciled.
5. The inheritance endpoint still accepts manually entered segregation observations and has not yet been switched to consume only verified bindings and normalized calls. Do not enable scientific inheritance conclusions on this basis.

## Qualification gates

- Migration upgrade from empty and current-head PostgreSQL databases; SQLite migration tests; immutable-row trigger tests; downgrade protection.
- API tests for cross-case member/specimen/analysis/artifact rejection, source-artifact mismatch, sample-name mismatch, reviewer authorization, idempotency/concurrency, and append-only review revisions.
- Known-answer multi-member family fixtures with separate analyses, exact sample names, no-calls, low-quality calls, multi-allelic projections, phase/phase-set and source-record provenance.
- Identity QC/relatedness and chain-of-custody review under an approved laboratory SOP.
- Only after those gates may the inheritance engine consume this evidence; the current conservative `REQUIRES_REVIEW` behavior remains in force.

## Laboratory identity evidence and correction lifecycle

Migration `0064_pedigree_sample_identity_evidence` adds immutable evidence records for chain of custody and sample identity QC. Evidence is recorded as `PENDING`, then an independent reviewer appends an `ACCEPTED` or `REJECTED` revision with a reason. An accepted record may accurately report `FAIL` or `INDETERMINATE`; only accepted `PASS` evidence satisfies the binding-verification gate. Evidence corrections append a successor revision; the previous evidence remains preserved. The evidence history is readable through the case-scoped API.

A verified specimen/sample binding is not evidence of biological parentage or relatedness. Relatedness/kinship QC remains a separate prerequisite for de novo and segregation interpretation.

## Family genotype matrix

The case-scoped matrix endpoint accepts explicit binding IDs and canonical variant IDs. It composes each selected member's independently normalized sample calls and pins the matrix to the source VCF digest, binding fingerprint, analysis version, sample name, normalized workflow provenance, source-record hashes and any specimen-scoped ploidy evidence revision. It permits one selected specimen/analysis binding per family member for a matrix request; repeated specimens and assays require an explicit selection.

Call states distinguish `NO_RECORD`, `GENOTYPE_UNAVAILABLE`, `NO_CALL`, `PARTIAL_NO_CALL` and `CALL_PRESENT`. An absent record is never imputed as `0/0`. DP/GQ/AD/PL/GL/FT values are preserved as source values; callability remains `NOT_ASSESSED` until a lab-approved QC policy is applied. Phase and phase-set values are preserved. The matrix does not calculate segregation, inheritance compatibility, pathogenicity or ACMG/ClinGen criteria, and it does not establish biological relatedness.
