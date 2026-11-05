# VCF conformance atomic-ledger — independent review package

**Prepared:** 2026-11-05  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Primary ledger:** `atomic-requirements.v1.json`  
**Pinned VCFv4.1–4.5 source revision:** `510c107ba89aa13113818c9e4fa3071283cb7f7b`

## 1. Review package status

This package prepares the current proposed ledger for independent standards review. It does **not** claim that an independent reviewer has been appointed, has reviewed any record, or has approved any requirement.

The current ledger contains 75 records:
- 15 initial file-structure/encoding/header seed records.
- 60 proposed FORMAT/GENOTYPE records reconciled from the 61-candidate review artifact.
- All 75 records remain `IN_REVIEW`.
- Independent second-person review: 0 records.
- Production implementation mappings: 0.
- Executed clause-specific tests: 0.
- Laboratory-qualified VCF versions: 0.

The 61-candidate artifact retains `FMT-GT-017` as a split parent; it is not a separate ledger requirement. The 60 other candidates map to ledger IDs `VCF-REQ-000016` through `VCF-REQ-000075`.

## 2. Review scope and source boundary

### In scope
- The exact source passages cited by each ledger record for VCFv4.1–4.5.
- Version applicability and semantic deltas.
- Normative force and whether a statement is mandatory, prohibited, recommended, permitted, or descriptive.
- Atomicity: one independently verifiable behavior per requirement.
- Actors, conditions, exceptions, observable acceptance conditions and unresolved questions.
- Correct treatment of examples, definitions, table rows, footnotes and cross-references.

### Explicitly not in scope for approval
- Production implementation correctness.
- BCF binary serialization conformance inferred from VCF text.
- Producer-specific gVCF or 1000 Genomes conventions treated as universal VCF requirements.
- Clinical assay validation or laboratory method verification.
- VCFv4.0 applicability. The historical VCFv4.0 source has not been accepted/pinned; current VCFv4.0 statuses are `SOURCE_NOT_PINNED`.

## 3. Required independent reviewer competencies

At least one reviewer independent of the initial author should have demonstrable experience with:
- VCF specifications and variant representation, including multiallelic records and ploidy.
- Genotype likelihood cardinality/order and phasing semantics.
- Structural-variant and breakend representation where those clauses are in scope.
- Reading normative technical specifications and distinguishing MUST/SHOULD/MAY from descriptive examples.
- Reproducible standards review and evidence traceability.

A separate reviewer with BCF implementation experience is recommended for any BCF-specific interpretation. A clinical laboratory representative is required for later laboratory workflow qualification, not for changing the normative meaning of the VCF specification.

## 4. Review procedure

For each ledger record, the reviewer should:

1. Open the exact pinned source file and inspect the cited line range plus the full surrounding subsection.
2. Follow all relevant references to definitions, tables, grammar, footnotes, examples and change-history entries.
3. Confirm that the source version and applicability status are correct.
4. Confirm the normative force. Do not convert recommendations or descriptive conventions into rejection rules.
5. Confirm the actor and condition; distinguish producer obligations from reader interoperability expectations.
6. Confirm the statement is atomic. Split it if independent counterexamples or tests can exercise different parts.
7. Check exceptions, optionality, missing-value behavior, ploidy, multiallelic behavior and relevant version-specific changes.
8. Confirm the observable acceptance condition is objectively testable and does not overstate the source.
9. Record a disposition: AGREE, DISAGREE, NEEDS_SPLIT, NEEDS_SOURCE_CONTEXT, or NOT_APPLICABLE, with rationale and exact citations.
10. Record reviewer identity/role, review date, source revision and any adjudication reference in a separate review record. Do not overwrite the initial review history.

## 5. High-risk review topics

The following topics should receive explicit scrutiny:

- **GT and ploidy:** allele index semantics, haploid/polyploid examples, missing alleles, and version-specific phasing grammar.
- **Number=G ordering:** all genotype tuples, inclusive loop boundaries, ordering algorithm, inverse index, ploidy and allele-count assumptions.
- **VCFv4.4–4.5 phasing:** allele-level indicators, implicit first indicator, partial phasing and difference from VCFv4.3 and earlier.
- **PS versus PSL:** cardinality, unphased placeholders, cross-chromosome identity, mutual exclusion and non-interoperability.
- **PSO/PSQ:** derivative-chromosome traversal, breakpoint-pair consistency, cardinality and SHOULD versus MUST semantics.
- **VCFv4.5 local alleles:** LAA distinct one-based ALT indices, order, conditional presence, local Number LA/LR/LG, BCF empty-vector/MISSING caveat, and global/local equivalence.
- **VCFv4.5 base modifications:** M/DPM/ADM key forms, aliases, ChEBI identifiers, U/T synonymy, GT dependency, sequence/strand/genotype/phasing-dependent cardinality, and unstranded conventions.
- **Reserved FORMAT rows:** distinguish a reserved field definition from a requirement that the field be present in every record/sample.
- **Version omissions:** absence from a later reserved list is not, by itself, proof that a field is invalid or forbidden.

## 6. Adjudication rules

- The primary author must not self-approve an independent review.
- Disagreements remain visible; do not silently average or erase them.
- Normative-force disagreements require direct source quotation/paraphrase and clause-level adjudication.
- A version-scope dispute must remain `UNRESOLVED` until supported by the exact version source.
- A candidate requiring multiple independent tests must be split before approval.
- A source gap must be marked `SOURCE_NOT_PINNED` or `UNRESOLVED`, not inferred from a later version.
- Approval of a requirement does not imply implementation, tests, interoperability, or laboratory qualification.

## 7. Review record template

For every reviewed requirement, capture:
- Requirement ID
- Reviewer role and independence declaration
- Review timestamp
- Exact source revision and locator(s)
- Disposition
- Normative-force confirmation
- Atomicity confirmation or child requirement IDs
- Version applicability decision
- Exceptions and unresolved questions
- Rationale and evidence references
- Adjudication outcome, if applicable

## 8. Coverage limitations before review can be called complete

The 75-record ledger is not the complete VCF conformance requirement universe. Outstanding source-review work includes:
- Full semantic decomposition of the remaining reserved INFO and FORMAT entries.
- Structural-variant INFO/FORMAT definitions and cross-references.
- Breakend syntax and reciprocal-record constraints.
- gVCF conventions, explicitly separated from core VCF where applicable.
- Remaining tables, grammar productions, footnotes, examples, definitions and change-history clauses.
- Full per-version semantic deltas across all identified requirements.
- VCFv4.0 historical source acquisition, exact-byte capture, SHA-256 and provenance adjudication.

Independent review can begin on the current 75 records as a bounded review tranche, but it must not be represented as approval of the complete VCF specification.

## 9. Current decision

**Ready for bounded independent review of the current 75 proposed records, subject to reviewer appointment and review-record capture. Not ready for a complete VCF conformance declaration or parser implementation sign-off.**
