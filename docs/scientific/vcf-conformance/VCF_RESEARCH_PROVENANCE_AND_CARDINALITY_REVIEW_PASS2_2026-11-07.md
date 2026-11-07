# VCF research provenance repair and cardinality addendum review — pass 2

**Date:** 2026-11-07  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Pull request:** [#293](https://github.com/SayedaRehmat/SIRALOOM/pull/293)  
**Scope:** Research artifacts under `docs/scientific/vcf-conformance/` and the isolated VCF research schema-validation workflow.

## 1. Provenance dependency repair

A repository-blob audit found three stale dependency-hash fields across two artifacts. The VCF specification source hashes were not changed.

| Artifact | Dependency | Stale recorded blob SHA-1 | Correct current blob SHA-1 |
|---|---|---|---|
| `vcf4.5-table-review-debt-adjudication.v1.json` | `vcf4.5-table-semantic-review-queue.v1.json` | `16d348b0a9f0523ed965914c9a69daf05ba1c353` | `7a8bee44406cd49ff405b29b061f4be762fcdb90` |
| `vcf4.1-4.5-version-delta-register.v1.json` | `vcf4.5-table-semantic-review-queue.v1.json` | `4e1c0e88cb7b19c03e5f836d8acfdbac76e46aa3` | `7a8bee44406cd49ff405b29b061f4be762fcdb90` |
| `vcf4.1-4.5-version-delta-register.v1.json` | `vcf4.5-table-review-debt-adjudication.v1.json` | `575f00ce36fc2e030a5e6f3cd64f9e95803451fe` | `453a2a8103a1642c53d8739abb7f329b142202c9` |

The version-delta register contains 21 declared input dependencies. Nineteen matched the repository's current blob IDs; two were stale and have been repaired. The table-review adjudication's separate queue pointer was also repaired. The updated dependency chain was re-fetched and the three repaired fields matched their current target blobs.

Repair commits:
- `d83f547186ff80e5bbdd43dff61df6cef6aa043a` — repair table-review queue provenance.
- `9c227f1be16a0cea0c4d66976346e305291961a` — repair version-delta register dependency hashes.

## 2. VCFv4.5 cardinality addendum: atomicity and source-context corrections

The prior cardinality/local-allele addendum contained 34 provisional records (`VCF-REQ-000227`–`VCF-REQ-000260`). Contextual review found compound records, modality drift and one malformed locator.

The corrected addendum now contains **42 provisional records** (`VCF-REQ-000227`–`VCF-REQ-000268`). Eight new child records were added:

| New ID | Separated obligation |
|---|---|
| `VCF-REQ-000261` | LAA FORMAT ordering, separated from LAA presence |
| `VCF-REQ-000262` | Genotype-dependent Number=M cardinality, separated from the Number=M per-modification definition |
| `VCF-REQ-000263` | PSO equality across breakend mates, separated from PSL equality |
| `VCF-REQ-000264` | DPM named-alias recommendation |
| `VCF-REQ-000265` | ADM named-alias recommendation |
| `VCF-REQ-000266` | DPM reserved-key family for unrecognized ChEBI IDs |
| `VCF-REQ-000267` | ADM reserved-key family for unrecognized ChEBI IDs |
| `VCF-REQ-000268` | ADRM non-reserved key-family statement, separated from ADFM |

Corrections to existing records:
- `VCF-REQ-000232` now contains the LAA-presence obligation only; its FORMAT-ordering obligation is `VCF-REQ-000261`.
- `VCF-REQ-000237` now contains the Number=M one-value-per-possible-modification definition; genotype-dependent cardinality is `VCF-REQ-000262`.
- `VCF-REQ-000254` now contains PSL equality across breakend mates; PSO equality is `VCF-REQ-000263`.
- `VCF-REQ-000257`, `000258` and `000260` now describe the M, M-alias and ADFM families respectively; DPM/ADM/ADRM obligations are separated into their own records.
- The malformed `VCF-REQ-000257` locator (`7-2`, with string-valued and reversed line bounds) was replaced by the exact VCFv4.5 source line 722. The new DPM and ADM reserved-key records cite lines 732 and 738.
- Normative force was corrected: `VCF-REQ-000233` MUST → SHOULD; `VCF-REQ-000234` MUST → DESCRIPTIVE; `VCF-REQ-000235` DESCRIPTIVE → SHOULD.
- The scope text now correctly states the complete ID range 000227–000268.

The addendum's 42 records have unique IDs and all source locators now have integer, positive, ordered line bounds. This is a provenance/structure audit, not formal JSON Schema validation.

## 3. Retained LAA source ambiguity

A seventh source ambiguity was added as `VCF45-AMB-007`.

- VCFv4.5 line 502 says LAA must be present if any local-allele field is present.
- VCFv4.5 lines 692–696 say LAA must be present if any local-allele fields are neither omitted nor MISSING.

The scope of “present” is not unambiguously reconciled by the source. The candidate ledger preserves the line-502 statement and records the later narrower condition as an unresolved question. No broad or narrow implementation predicate is selected.

The ambiguity register now contains seven issues. This author-level finding is not an upstream correction or independent standards approval.

## 4. Supplemental GT/FORMAT candidate reconciliation

The addendum-to-`genotype-format-atomic-candidates.v1.json` crosswalk now contains 42 unique mappings:

| Relationship | Count |
|---|---:|
| Supplemental records | 42 |
| Related to existing GT/FORMAT candidates | 33 |
| No GT/FORMAT candidate match identified | 9 |
| Direct overlaps | 25 |
| Partial/combined relationships, including retained scope conflict | 8 |

These are candidate relationships only. They do not establish canonical-ledger deduplication or approval. The full 226-record canonical ledger comparison remains outstanding for this addendum. The existing 61 GT/FORMAT candidates remain provisional and independently unapproved.

## 5. Formal schema validation expansion

The isolated research-only validator was expanded to validate both:
1. `VCF45_ATOMIC_CANDIDATE_REGISTRY_PASS1_2026-11-07.json` (161 records); and
2. `vcf4.5-cardinality-local-allele-atomic-addendum.v1.json` (42 records).

It uses `jsonschema==4.26.0`, checks the Draft 2020-12 schema with `Draft202012Validator.check_schema`, and validates each complete registry with `Draft202012Validator.iter_errors`. The updated workflow run is pending at the time this audit was written; no formal-validation PASS is claimed for the 42-record addendum until that run completes successfully.

The only workflow/code change is to the isolated research schema validator and its dedicated research workflow. No production parser, validator, normalizer, BCFtools/HTSlib toolchain, or existing production CI job was changed.

## 6. Current gates and next execution order

1. Confirm the updated GitHub Actions run passes formal Draft 2020-12 validation for both registries.
2. Reconcile all 42 addendum records against the complete 226-record canonical ledger; distinguish covered, partial, duplicate and genuinely net-new semantics.
3. Continue clause-level VCFv4.1–4.5 semantic reconciliation for all reserved INFO and FORMAT fields, including the GLE removal, Number=P/PSL/PSO/PSQ, local alleles, Number=M, END/SVLEN and SV-specific semantics.
4. Complete GT semantic reconciliation across VCFv4.1–4.5 without projecting later Number/Type semantics backward into prose-only versions.
5. Continue VCFv4.5 FORMAT cardinality/projection work for LA, LR, LG, M and P, including local/global equivalence, genotype likelihood ordering and missing-value behavior.
6. Acquire and qualify exact historical VCFv4.0 core source bytes; keep 1000 Genomes producer conventions separate.
7. Obtain independent standards review before promoting any candidate to the canonical ledger.
8. Only after review, map requirements to implementation and execute version-specific conformance tests. Laboratory qualification remains a separate later gate.

## 7. Non-claims

- No requirement in the 42-record addendum is independently approved.
- The 226-record canonical ledger was not changed and no canonical IDs were allocated.
- The 42-record addendum has not yet been reconciled against the complete canonical ledger.
- No parser/validator/normalizer implementation mapping or executable conformance tests were added or run.
- No VCF version is claimed laboratory-qualified.
- Exact VCFv4.0 source bytes and SHA-256 remain unavailable.
