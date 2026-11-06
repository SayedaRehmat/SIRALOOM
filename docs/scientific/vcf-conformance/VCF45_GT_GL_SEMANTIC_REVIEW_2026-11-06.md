# VCFv4.5 GT and genotype-likelihood semantic review

**Review date:** 2026-11-06  
**Specification:** VCFv4.5, HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`  
**Source file:** `VCFv4.5.tex`  
**Source Git blob:** `307950e7eeafc33d524969ff906343f756adb7d7`  
**Source SHA-256:** `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5`  
**Disposition:** `AUTHOR_SOURCE_REVIEW_COMPLETE_FOR_CAPTURED_GT_GL_CONTEXT — INDEPENDENT_REVIEW_PENDING`

## 1. Scope and method

This review covers the VCFv4.5 FORMAT introduction and GT/GL/GP/PL/PP genotype semantics at source lines 498–516 and 612–683, including the genotype-ordering algorithm and its examples. It reconciles the existing candidate IDs in `genotype-format-atomic-candidates.v1.json`; it does not create new canonical requirement IDs or claim that any candidate is independently approved.

The source is pinned to the same immutable HTS-specs revision as the existing Phase A manifest. Line locators below refer to the exact pinned `VCFv4.5.tex`.

## 2. FORMAT-level obligations and semantics

Source lines 498–516 establish the following distinct statements:

| Source locator | Statement | Force / interpretation | Candidate reconciliation |
|---|---|---|---|
| 498 | If genotype information is present, the same types of data must be present for all samples. | MUST; the phrase “same types” needs careful interpretation and must not be expanded into identical values. | FMT-GT-001 |
| 499–500 | FORMAT specifies genotype data types and order; sample values are colon-separated and correspond to that FORMAT order. | Descriptive structural semantics. | FMT-GT-002 |
| 499–500 | FORMAT keys match the stated identifier regular expression; duplicate keys are not allowed. | Key grammar plus MUST_NOT uniqueness. | FMT-GT-002, FMT-GT-003 |
| 501 | If GT is present, it is the first FORMAT key. | MUST. | FMT-GT-004 |
| 502 | If any local-allele field is present, LAA must be present and precede all fields other than GT. | MUST; interpret with the narrower non-omitted/non-MISSING LAA condition at lines 693–695. | FMT-GT-017, FMT-GT-039 |
| 503 | There are no required FORMAT keys. | Descriptive global rule; does not override conditional dependencies. | FMT-GT-005 |
| 504–507 | Missing subfield values are represented by MISSING; a list of missing values may be represented by one MISSING token or an explicit list; trailing fields may be dropped. | Preserve the exact distinction: explicit MISSING representation; list form MAY; trailing fields MAY be dropped. | FMT-GT-006, FMT-GT-007, FMT-GT-008 |
| 507 | GT should always be present if GT is specified in FORMAT. | SHOULD, not MUST. Correct FMT-GT-008 if it currently promotes this to MUST. | FMT-GT-008 |
| 508–509 | If a field and its local-allele equivalent are both defined, they must encode identical information or one must be ignored by being MISSING or omitted. | MUST; retain the source's wording and its local/global interpretation. | FMT-GT-018 |

### 2.1 Candidate correction: trailing GT

The source says trailing FORMAT fields may be dropped, with the exception that GT **should** always be present if specified in FORMAT. The source does not use MUST for this exception. Any candidate, implementation rule or validator error that upgrades this to a hard MUST would strengthen the specification and is not justified by this passage. Keep SHOULD as the source force.

### 2.2 Candidate correction: no required keys

“No required keys” is a general statement about FORMAT keys, not a waiver of conditional requirements. For example, when a non-omitted/non-MISSING local-allele field is used, LAA is conditionally required. The general statement and conditional dependency must coexist.

## 3. GT semantics

Source lines 613–628 define GT:

1. Each allele value is preceded by a phasing indicator, either `/` or `|`, describing whether the allele is considered phased.
2. The first phasing indicator may be omitted. Its implicit value is `/` if any explicit phasing indicator is `/`; otherwise it is `|`.
3. Allele value 0 denotes REF; 1 denotes the first ALT allele; 2 denotes the second ALT allele; subsequent positive values follow ALT order.
4. Diploid examples include `0/1`, `1|0`, `/0/1`, and `1/2`.
5. Haploid calls (examples include Y, male non-pseudoautosomal X and mitochondria) should be represented with one allele value.
6. Higher ploidy is represented by multiple allele values; the source gives triploid and partially phased triploid examples.
7. If a genotype call cannot be made, each missing allele is represented by MISSING in GT; examples include `./.` for diploid and `.` for haploid.
8. `/` means unphased; `|` means phased according to the phase set indicated by PS or PSL.
9. For symbolic structural-variant alleles, GT=0 indicates absence of any symbolic SV ALT allele defined in that record.
10. Merging a record containing only symbolic SV ALT alleles with a record containing other alleles changes the meaning of GT=0 haplotypes from the symbolic-only record.

Candidate reconciliation: FMT-GT-009, FMT-GT-010, FMT-GT-024, FMT-GT-025, FMT-GT-026 and the separate SV/breakend candidate set.

### 3.1 GT interpretation boundary for local alleles

The local-allele prose at lines 691–697 says genotype can be specified against a subset of local alleles. The first local/global example pair at lines 703–704 has GT `2/4` in the local row and `2/2` in the paired global row, while the other paired examples show matching GT tokens. This discrepancy remains unresolved.

Therefore:
- the ordinary GT definition above is captured as written;
- the local-allele exception is not resolved by this review;
- implementations must not silently rewrite GT allele numbers to local ordinals or assume that local GT values always retain global ALT indices;
- preserve the raw GT token and LAA vector separately until the source inconsistency is clarified;
- do not use the first paired example as a GT equivalence test oracle.

This is a source ambiguity, not permission to invent a new GT numbering convention.

## 4. GL semantics and ploidy

Source lines 629–630 define GL as comma-separated floating-point log10-scaled likelihoods for all possible genotypes over the REF and ALT allele set.

- When GT is present, GL is expected to use the same ploidy.
- When GT is absent, diploidy is assumed.
- GL cardinality is therefore linked to the allele set and applicable ploidy; this must be kept distinct from a parser's arbitrary list-length limit.

Candidate reconciliation: FMT-GT-011 and FMT-GT-019. Split the source obligations into separate ledger entries for likelihood scale, genotype domain, ploidy dependency, cardinality and ordering.

## 5. Genotype ordering algorithm

Source lines 632–669 define the canonical ordering for ploidy P and N alternate alleles, with allele 0 as REF and 1..N as ALT:

1. The genotype tuple values are nondecreasing.
2. The primary algorithm uses as many nested loops as ploidy.
3. The loop bounds are inclusive; the source explicitly states this in a footnote.
4. The recursive algorithm is stated as an equivalent alternative.
5. The zero-based index for nondecreasing allele tuple (k_1 \le k_2 \le \ldots \le k_P) is the sum of binomial coefficients shown in the source.
6. The source gives examples for haploid, diploid biallelic/triallelic and triploid triallelic ordering.

Candidate reconciliation:
- FMT-GT-019: all possible genotype enumeration;
- FMT-GT-020: inclusive loop bounds;
- FMT-GT-021: nondecreasing allele tuple;
- FMT-GT-022: diploid index formula;
- FMT-GT-023: general-ploidy combinatorial index.

The triangular diploid matrix is an illustration, not a substitute for the general nested-loop/recursive algorithm. Conformance tests must use the algorithm and include ploidy 1, 2, 3 and higher supported values, with multiple alternate alleles and index round trips.

## 6. Related genotype fields

- **GP:** Float genotype posterior probabilities in the range 0 to 1, using the same ordering as GL. Source line 612.
- **PL:** Integer phred-scaled genotype likelihoods rounded to the closest integer, using the GL genotype semantics. Source reserved table line 590 and field prose around line 690.
- **PP:** Integer phred-scaled genotype posterior probabilities rounded to the closest integer. Source reserved table line 591.
- **GQ:** Conditional genotype quality; it is not the genotype-likelihood vector and remains genotype quality under local-allele encoding. Source lines 611 and 697.

Do not conflate GL/PL likelihoods with GP/PP posterior probabilities. Their value domains and scaling differ even where the genotype ordering is shared.

## 7. Atomicity and source-reconciliation actions

The current candidate set has useful proposed atomic statements but still needs the following refinements before ledger promotion:

| Candidate | Required action |
|---|---|
| FMT-GT-001 | Resolve what “same types of data” means from complete context; do not equate it automatically with identical values. |
| FMT-GT-003 | Applicability begins in VCFv4.3 in the captured evidence; do not backport to 4.1/4.2 without source support. |
| FMT-GT-004 | Preserve GT-first as a MUST when GT is present. |
| FMT-GT-005 | Retain “no required keys” but link conditional LAA/GT dependencies. |
| FMT-GT-006/007 | Split missing scalar, list-of-missing alternative, and field-specific exceptions. |
| FMT-GT-008 | Correct the trailing-GT exception to SHOULD, not MUST. |
| FMT-GT-009 | Preserve the local-allele GT index ambiguity; do not apply one mapping across all contexts. |
| FMT-GT-010 | Preserve “should” for the haploid one-allele wording; keep examples distinct from hard requirements. |
| FMT-GT-011 | Split GL scale, genotype domain, ploidy, cardinality and ordering. |
| FMT-GT-019–023 | Keep algorithm, inclusive bounds, tuple ordering and index formula as separately testable obligations. |
| FMT-GT-024/025 | Preserve the omitted-first-indicator inference rule and its exact conditional behavior. |
| FMT-GT-026 | Tie `|` to PS or PSL phase-set context. |

## 8. Conformance test design derived from this review

These are test specifications, not executed tests:

- FORMAT sample value count/order aligns with declared FORMAT keys.
- Duplicate FORMAT key is rejected for VCFv4.5.
- GT first when present; GT absent is allowed by the general rule.
- Local-allele LAA ordering and conditional presence are tested separately.
- Trailing non-GT FORMAT fields can be omitted; GT trailing-field SHOULD behavior is reported without inventing MUST.
- Single MISSING versus explicit all-MISSING list representation is tested where field cardinality permits.
- GT: slash, pipe, omitted first indicator, first-indicator inference with mixed explicit separators, and all-phased indicators.
- GT haploid, diploid, triploid and higher ploidy; each missing allele represented separately.
- REF/ALT allele index mapping and out-of-range allele indices.
- GL same-ploidy as GT; GL without GT uses diploidy.
- GL ordering enumeration and inverse-index formula property tests across ploidies and ALT counts.
- GP 0..1 range and same genotype ordering as GL.
- PL/PP integer scaling and shared ordering semantics.
- Symbolic SV GT=0 interpretation and merge-induced semantic change.
- Local GT ambiguity fixtures remain quarantined from pass/fail equivalence until source clarification.

## 9. Completion boundary

This is an author-level review of the cited VCFv4.5 GT/GL passages. It does not establish full VCFv4.5 requirement completeness, independent review, implementation mapping, executed tests, CI pass, or laboratory qualification. Candidate IDs remain candidates until reconciled against the full canonical ledger and independently reviewed.
