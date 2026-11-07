# VCFv4.5 FORMAT, GT, local-allele and base-modification audit

**Audit date:** 2026-11-07  
**Research branch:** `research/vcf-conformance-phase-a-20261105`  
**Pinned specification:** `samtools/hts-specs`, commit `510c107ba89aa13113818c9e4fa3071283cb7f7`, `VCFv4.5.tex`  
**Pinned source Git blob:** `307950e7eeafc33d524969ff906343f756adb7d7`

This is a source-context audit and implementation reconciliation, not independent standards approval or laboratory qualification.

## 1. Source coverage and locators

The audit reviewed the complete relevant source contexts, not only isolated table rows:

| Topic | VCFv4.5.tex lines | Normative content reviewed |
|---|---:|---|
| FORMAT Number extensions | 192–218 | LA, LR, LG, P and M meanings; base-modification cardinality |
| Genotype column rules | 501–508 | GT ordering, LAA placement, missing values and local/non-local equivalence |
| GT semantics | 613–627 | allele indices, implicit/leading phasing separator, ploidy, missing alleles and symbolic SV interpretation |
| Number=G ordering | 629–683 | colexicographic ordering for arbitrary ploidy and genotype index formula |
| LAA and local fields | 686–718 | LAA order, 1-based ALT indexes, BCF empty-vector behavior, local field equivalence and LPL |
| Reserved genotype keys | 534–596 | Number/Type/description for all table entries and base-modification aliases |
| Base-modification semantics | 720–744 | allowed IDs, alias spellings, value ranges, strandedness, unstranded storage and excluded ADFM/ADRM keys |
| SV FORMAT keys | 1142–1161 | CN, CICN, CNQ, CNL, CNP, NQ, HAP and AHAP definitions and semantics |

## 2. Reserved FORMAT definitions

The primary reserved genotype table maps as follows:

| Key(s) | Number | Type |
|---|---:|---|
| AD, ADF, ADR | R | Integer |
| DP, GQ, GT, LEN, MQ, PQ, PS | 1 | Integer, except GT is String |
| EC | A | Integer |
| FT | 1 | String |
| GL, GP | G | Float |
| HQ | 2 | Integer |
| LA, LAA | . | Integer |
| LAD, LADF, LADR | LR | Integer |
| LEC | LA | Integer |
| LGL, LGP | LG | Float |
| LPL, LPP | LG | Integer |
| PL, PP | G | Integer |
| PSL | P | String |
| PSO, PSQ | P | Integer |
| M[0-9]+[ACGTUN] | M | Float |
| DPM[0-9]+[ACGTUN], ADM[0-9]+[ACGTUN] | M | Integer |

The explicit base-modification aliases in the table are:

- Fraction: M5mC, M5hmC, M5fC, M5caC, M5hmU, M5fU, M5caU, M6mA, M8oxoG and the xanthosine alias.
- Total detectable depth: DPM5mC, DPM5hmC, DPM5fC, DPM5caC, DPM5hmU, DPM5fU, DPM5caU, DPM6mA, DPM8oxoG and the xanthosine alias.
- Modified-base depth: ADM5mC, ADM5hmC, ADM5fC, ADM5caC, ADM5hmU, ADM5fU, ADM5caU, ADM6mA, ADM8oxoG and the xanthosine alias.

The VCFv4.5 source also defines these structural-variant FORMAT keys in a separate section:

| Key | Number | Type | Meaning |
|---|---:|---|---|
| CN | 1 | Float | Copy number |
| CICN | 2 | Float | Copy-number confidence interval |
| CNQ | 1 | Float | Copy-number genotype quality |
| CNL | G | Float | Copy-number genotype likelihood |
| CNP | G | Float | Copy-number posterior probabilities |
| NQ | 1 | Integer | Novelty quality |
| HAP | 1 | Integer | Unique haplotype identifier |
| AHAP | 1 | Integer | Ancestral haplotype identifier |

The validator's VCFv4.5 reserved-definition registry now includes these eight SV FORMAT definitions in addition to the main reserved genotype table and dynamic base-modification patterns. This enforces declared Number/Type compatibility; it does not implement the structural-variant interpretation or make SVs part of the supported Phase 1 variant scope.

The source explicitly says ADFM[0-9]+[ACGTUN] and ADRM[0-9]+[ACGTUN] are **not** reserved fields. They must not be added as aliases for ADF/ADR.

## 3. Number=M semantics and executable coverage

The source defines Number=M cardinality using both GT and the allele sequences:

1. The FORMAT ID suffix A, C, G, T, U or N specifies the base(s) that can carry the modification.
2. U is synonymous with T.
3. For a concrete allele, count sequence positions on either strand that can contain the specified modification. A complementary base in the stored allele sequence can represent a modifiable position on the opposite strand.
4. For N, emit positive-strand and negative-strand values for every base, with the negative-strand value immediately after its positive-strand value.
5. Concatenate values in GT order. Repeated unphased allele values are aggregated at the first occurrence; phased copies remain distinct.
6. Missing GT alleles and symbolic alleles contribute no base-modification values.
7. Unstranded values are stored at the lowest POS; the complementary position is MISSING or omitted. Unstranded N values use the positive-strand position and leave the negative-strand value MISSING.

The new test suite covers:

- M5mC on CGA, where C and complementary G represent two strand-specific modifiable positions.
- N modification cardinality on a two-base allele, requiring four values.
- repeated unphased allele aggregation versus repeated phased allele copies.
- missing GT alleles and symbolic ALT alleles contributing no values.
- U/T equivalence.
- cardinality mismatch rejection.

**Validation boundary:** the current validator computes and checks Number=M cardinality. It cannot determine whether an arbitrary submitted numeric value is biologically assigned to the correct base/strand position: VCF values carry no per-value base label. The required value order is therefore source-defined, but value-to-position semantic verification is not claimed by these tests. Likewise, unstranded placement across adjacent records is not established by a single-record cardinality check.

## 4. Local-allele semantics and validator correction

The source defines:

- LA: one value for each local alternate allele in LAA.
- LR: one value for REF followed by each local alternate allele in LAA order.
- LG: one value for each possible genotype over REF plus the LAA alleles, using the VCF genotype-ordering algorithm and sample ploidy.
- P: one value for each allele value in GT.
- LAA: distinct, 1-based indices into ALT. Its order is meaningful and defines the local allele order.

The source requires LAA to be present whenever a local-allele FORMAT field is used and to precede every FORMAT field other than GT. The validator previously checked LAA values when LAA existed, but did not enforce the FORMAT-key presence/order rule. This has now been corrected for VCFv4.5. Detection covers both reserved local fields and user-defined fields declared with Number=LA, LR or LG.

The validator also interprets a missing LAA vector as an empty local ALT vector (REF-only) for local-field cardinality, consistent with the source's BCF zero-length-vector convention. This does not mean a missing LAA can be silently omitted from the FORMAT key list.

Local/non-local pairs are required by the source to encode identical information, or one representation must be MISSING/omitted. The current equivalence checker projects the standard A/R/G vector through the ordered local allele list and checks the local representation. New tests exercise LAD/LADF/LADR, LEC, LGP and LPP in addition to PL/LPL and GL/LGL, including reversed LAA order and mismatch errors.

### Retained source ambiguity: example GT mismatch

The source's local-allele equivalence example at lines 703–704 shows the local record with `GT=2/4`, `LAA=2,4`, but its paired expanded record with `GT=2/2`. These genotypes do not encode the same allele pair under the source's earlier global allele-index definition. This contradiction remains unresolved. The implementation and tests do not reinterpret GT indices as local indexes or silently correct the source example. Independent standards adjudication is required.

## 5. GT and Number=G reconciliation

The VCFv4.5 source defines allele values as 0 for REF and 1..N for ALT order. Ploidy is the number of allele values, not a diploid assumption. A missing allele is represented by a dot for that allele. Haploid, diploid, triploid and higher-ploidy genotypes are valid.

The first phasing indicator may be omitted. It is implicitly '/' if any phasing indicators are '/', and otherwise '|'. VCFv4.5 also permits a leading separator, including the source's partially phased examples. '/' marks an unphased allele; '|' marks an allele phased according to PS or PSL.

Number=G uses colexicographic genotype ordering. For sorted genotype alleles k1 <= ... <= kP, the index is:

`Index(k1,...,kP) = sum(m=1..P) choose(km + m - 1, m)`

The validator's genotype-order generator and index mapping implement this ordering; existing and new tests cover haploid, diploid and triploid projection cases. PS and PSL are distinct phase-set representations and cannot both be populated for one sample. PSL is one entry per GT allele; unphased allele positions use MISSING. PSO and PSQ are Number=P fields associated with PSL.

The following issues remain outside a claim of complete GT qualification:

- The local GT/LAA example contradiction above requires adjudication.
- The full GT/PS/PSL/PSO/PSQ rule set still requires an independent row-by-row standards review across all VCF versions.
- Conformance tests establish implemented cases, not exhaustive proof for every mixed-ploidy, partial-phase and missing-value combination.

## 6. Xanthosine alias capitalization: explicitly unresolved

The pinned VCFv4.5 source is internally inconsistent:

- Reserved table, lines 586–588: `MXaoN`, `DPMXaoN`, `ADMXaoN` (uppercase X).
- Narrative alias lists, lines 724, 734 and 740, and the unstranded example at line 218: `MxaoN`, `DPMxaoN`, `ADMxaoN` (lowercase x).

Both spellings are currently recognized by the validator and have tests, but neither is designated as the sole canonical spelling. Do not silently normalize one spelling to the other. Retain this as a source ambiguity for independent adjudication.

## 7. Change and qualification status

Changes on this research branch:

- Added VCFv4.5 reserved SV FORMAT definitions to `_reserved_vcf45_format_definition`.
- Enforced LAA key presence and placement for local-allele FORMAT fields, including custom LA/LR/LG declarations.
- Added Number=M tests and reserved SV FORMAT / xanthosine alias tests.
- Added LAA requirement/order tests.

The changes are provisional until the full CI workflow for the latest commit passes and the source ambiguities receive independent review. They do not qualify VCFv4.5 or complete the VCF 4.0–4.5 stage.
