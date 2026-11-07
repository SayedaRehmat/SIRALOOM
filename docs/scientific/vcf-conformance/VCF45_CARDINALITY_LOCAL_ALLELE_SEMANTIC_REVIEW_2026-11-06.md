# VCFv4.5 cardinality and local-allele semantic review

**Review date:** 2026-11-06  
**Specification:** VCFv4.5 at HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`  
**Source file:** `VCFv4.5.tex`  
**Source Git blob:** `307950e7eeafc33d524969ff906343f756adb7d7`  
**Source SHA-256:** `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5`  
**Disposition:** `SOURCE_REVIEWED_FOR_THIS_TOPIC — IMPLEMENTATION_AND_CONFORMANCE_NOT_ASSESSED`

## 1. Scope and evidence boundary

This review extracts the VCFv4.5 source semantics relevant to FORMAT cardinalities `P`, `M`, `LA`, `LR`, and `LG`, and to local-allele projection/equivalence. Source line numbers below refer to the exact pinned `VCFv4.5.tex` bytes identified above. This is a focused semantic review, not a whole-specification review or an independent second-person approval.

## 2. Normative reserved FORMAT inventory

The reserved genotype table is at source lines 534–596.

| FORMAT key | Number | Type | Source-defined meaning |
|---|---:|---|---|
| LAA | . | Integer | 1-based indices into ALT identifying alleles relevant (local) to the sample |
| LAD | LR | Integer | Local-allele representation of AD |
| LADF | LR | Integer | Local-allele representation of ADF |
| LADR | LR | Integer | Local-allele representation of ADR |
| LEC | LA | Integer | Local-allele representation of EC |
| LGL | LG | Float | Local-allele representation of GL |
| LGP | LG | Float | Local-allele representation of GP |
| LPL | LG | Integer | Local-allele representation of PL |
| LPP | LG | Integer | Local-allele representation of PP |
| M[0-9]+[ACGTUN] | M | Float | Fraction of bases modified with the given ChEBI ID |
| DPM[0-9]+[ACGTUN] | M | Integer | Total read depth able to detect the modification |
| ADM[0-9]+[ACGTUN] | M | Integer | Read depth with the modification |
| M5mC, M5hmC, M5fC, M5caC, M5hmU, M5fU, M5caU, M6mA, M8oxoG, MXaoN | M | Float | Named aliases for ChEBI-keyed modification fields |
| DPM*/ADM* aliases | M | Integer | Corresponding aliases for modification-depth fields |
| PSL | P | String | Phase-set list |
| PSO | P | Integer | Phase-set list ordinal |
| PSQ | P | Integer | Phase-set list quality |

The table is not just a list of familiar keys: every row above is reserved and its Number/Type pairing must be represented in the version-specific profile. Source lines 556–588 define the base-modification key families and aliases; lines 594–596 define PSL/PSO/PSQ.

## 3. Local allele model

### 3.1 LAA definition and activation

Source lines 686–697 establish the local-allele model:

1. LAA is a list of distinct integers.
2. Each integer is a **1-based index into ALT**.
3. LAA identifies the ALT alleles observed in the sample.
4. The order in LAA defines the order in which local alleles are interpreted.
5. LAA is required when interpreting local-allele fields and must be present if any local-allele field is neither omitted nor MISSING.
6. In BCF, a zero-length vector is encoded as MISSING. If local fields are present and LAA contains MISSING, the LAA value is interpreted as an empty vector (a REF-only site).
7. All specification-defined A, R and G FORMAT fields have corresponding local-allele representations with the same semantics, except that only the local ALT alleles are considered and their LAA order is used.
8. GQ remains the genotype quality even when the genotype is represented against local alleles.

A local-allele decoder must therefore resolve the LAA vector before decoding any LA/LR/LG payload. It must not infer local order by sorting ALT indices unless a separate source rule establishes that constraint.

### 3.2 Projection domains

Let the record have REF plus global ALT alleles, and let LAA be the ordered list of distinct global ALT indices:

`LAA = [i_1, i_2, \ldots, i_n]`

The local allele domain is:

`[REF, ALT[i_1], ALT[i_2], \ldots, ALT[i_n]]`

The cardinality mapping is:

| Number | Projection domain | Expected value count |
|---|---|---|
| LA | Local ALT alleles only | `n` |
| LR | REF plus local ALT alleles | `n + 1` |
| LG | All unordered genotypes over REF plus local ALT alleles at sample ploidy `P` | `C((n+1)+P-1, P)` |

The LG count follows the source's genotype-ordering definition at lines 632–669 (combinations with repetition, ordered by the specified nested-loop procedure). The source's LPL paragraph at lines 717–718 directs local likelihood ordering back to the GL paragraph.

### 3.3 GT allele-index interpretation: unresolved source/example inconsistency

The local-allele prose at lines 691–697 says genotype, allele depth and genotype likelihood can be specified against a subset of local alleles, and line 697 explicitly says GQ remains genotype quality when GT is given against local alleles. The worked example at lines 703–710, however, contains a material inconsistency that prevents this review from declaring the exact GT index mapping settled:

- The first local-allele row has ALT `A,C,T,<*>`, LAA `2,4`, and GT `2/4`.
- The paired global AD/PL row at the same POS has the same ALT but GT `2/2`.
- The remaining paired examples at POS 2, 3 and 4 show matching GT values between local and global rows.

The first pair therefore does not establish a consistent global-index-to-local-index conversion. It may be an upstream example error, but that cannot be assumed without authoritative clarification. The prose's statement that GT can be given against local alleles must be reconciled with the example and with the general GT definition.

**Disposition:** do not assert either that GT always remains globally indexed or that GT is always locally reindexed based solely on the current example. Preserve the raw GT token, LAA vector, and source allele domain independently in the parser design; block semantic GT remapping until the source ambiguity is resolved. Do not use the first worked example as a passing equivalence oracle.

### 3.4 Local-allele likelihood projection example

Source lines 703–710 show the local/global AD and PL encodings. For the first paired record:

- Global ALT: `A,C,T,<*>`
- LAA: `2,4`
- Local allele domain for LPL: `REF, ALT[2], ALT[4]`
- Local row GT: `2/4`
- Local LAD: three values (REF, local ALT 1, local ALT 2)
- Local LPL: six diploid genotype values in local ordering
- Paired global row GT: `2/2`, which conflicts with the local-row GT token under a straightforward identity mapping

For diploidy and three local alleles, the genotype order is:

`00, 01, 11, 02, 12, 22`

The local LPL cardinality and allele-domain reduction are clear from the prose and vector lengths. The GT correspondence in the first example is not clear. Conformance tests must separately test local likelihood projection and GT semantics; they must not assert full-record equivalence for the first pair until the source inconsistency is adjudicated.

## 4. Local-allele missing-value and equivalence rules

Source lines 693–715 and the FORMAT introduction specify the following requirements:

- If any local-allele field is present, LAA must also be present and precede all fields other than GT (FORMAT introduction immediately before the reserved genotype table).
- A local-allele field without a usable LAA context is invalid for semantic interpretation; do not silently treat it as a global field.
- If a field and its local-allele equivalent are both defined, they must encode identical information, or one must be ignored by being MISSING or omitted (FORMAT introduction).
- A field containing a list of missing values may be represented by a single MISSING value or an explicit list of missing values when its Number is fixed (FORMAT introduction).
- BCF zero-length vectors are represented as MISSING. At REF-only sites, implementation-defined Number=LA fields must not be used when distinguishing zero-length from missing is required (source lines 713–714).

### Required equivalence assertions

For each supported local field pair, construct a semantic projection from global to local and compare values:

- AD ↔ LAD (R ↔ LR)
- ADF ↔ LADF (R ↔ LR)
- ADR ↔ LADR (R ↔ LR)
- EC ↔ LEC (A ↔ LA)
- GL ↔ LGL (G ↔ LG)
- GP ↔ LGP (G ↔ LG)
- PL ↔ LPL (G ↔ LG)
- PP ↔ LPP (G ↔ LG)

Excluded global alleles must not leak into the local vector. The local vector must preserve LAA order. Genotype likelihood/posterior entries must use the source-defined genotype ordering for the local allele count and the sample ploidy.

## 5. Genotype ordering requirements for LG

Source lines 629–669 define GL/PL/GP/PP ordering:

- With ploidy `P` and `N` alternate alleles (allele 0 is REF and 1..N are ALT), genotype tuples are enumerated by nested loops from the highest allele index down to the first allele, with nondecreasing allele values.
- Equivalent recursive pseudocode is supplied.
- The source gives the index formula:

`Index(k_1/k_2/.../k_P) = sum_{m=1..P} C(k_m + m - 1, m)`

- Diploid examples: for N=1, `00,01,11`; for N=2, `00,01,11,02,12,22`.
- Triploid example for N=2: `000,001,011,111,002,012,112,022,122,222`.

The same ordering is used for LGL/LGP/LPL/LPP after restricting the allele domain to REF plus LAA. Tests must cover haploid, diploid, triploid and higher supported ploidies; multiallelic local sets; and non-monotonic LAA order if permitted by the profile's source interpretation.

## 6. Number=P and phase-set list semantics

### 6.1 General Number=P cardinality

The general FORMAT Number definitions at VCFv4.5 source lines 195–197 define Number=P as one value for each allele value defined in GT. This is more precise than describing P only as “ploidy/local copy number”: the actual cardinality is anchored to the allele-value positions represented in GT. The version-delta review records Number=P and PSL/PSO/PSQ as introduced in VCFv4.4 and retained in VCFv4.5.

Reserved table rows at lines 594–596:
- PSL: Number=P, String;
- PSO: Number=P, Integer;
- PSQ: Number=P, Integer.

The VCFv4.4 general definition is at lines 198–202 and the reserved rows at 496–498. The VCFv4.5 general definition and reserved rows are at 195–197 and 594–596 respectively.

### 6.2 Field-specific list semantics

The detailed definitions provide field-specific behavior:

- **PSL** is a list of phase sets, one for each allele value specified in GT. Unphased alleles (no preceding `|`) use MISSING at the corresponding list position.
- **PSO** is a list of phase-set ordinals. Its MISSING value represents a missing PSO value. It describes derivative-chromosome traversal order. For each phase-set name, PSO should be defined if any allele with that name on any record is a symbolic SV or uses breakend notation. Breakend records must have matching PSL and PSO on both records.
- **PSQ** is a list of PQ values, one for each phase set in PSL. VCFv4.5 says MISSING should be used when the corresponding PSL value is MISSING or when phasing quality is unknown.

### 6.3 Cardinality reconciliation still required

A validator must preserve the distinction between:
- the general Number=P definition: one value per allele value defined in GT;
- PSL and PSO's per-GT-allele list semantics;
- PSQ's field-specific description as one value per phase set in PSL;
- MISSING entries, which preserve positional meaning;
- the fact that Number=P is distinct from Number=G genotype-combination cardinality.

**Open review item:** independently reconcile the general Number=P definition with PSQ's “one for each phase set in PSL” wording, including cases where phase-set identifiers repeat across GT allele positions. Do not impose a simplistic `len(value) == GT ploidy` rule without resolving the field-specific semantics and the relevant local-copy-number cases.

## 7. Number=M and base-modification fields

### 7.1 General Number=M cardinality

The previous draft of this review incorrectly stated that no standalone definition of Number=M had been located. That statement is withdrawn. The general FORMAT Number definitions at source lines 195–197 explicitly define M as one value for each possible base modification for the corresponding ChEBI ID. The following prose at lines 198–218 defines how that cardinality is determined and how values are ordered.

This is a material correction to the earlier review; the prior “unresolved general definition” claim must not be used.

The source-grounded semantics are:

1. Number=M cardinality is determined by the genotype and the number of possible base modifications for the corresponding alleles.
2. The key suffix must be one of A, C, G, T, U or N, identifying the base(s) on which the modification can occur.
3. U is treated as synonymous with T.
4. If any base-modification key is present for a sample, GT must be defined for that sample.
5. For each allele, the number of values equals the number of bases on either strand in that allele sequence that could contain the modification.
6. Values for an allele follow the order in which eligible bases occur in that allele sequence.
7. For N modifications, both positive- and negative-strand values are represented, with the negative-strand value immediately after the positive-strand value.
8. The number and order of alleles are determined by genotype order and phasing. Values follow GT allele order.
9. Values for unphased alleles are aggregated and encoded at the position of the first occurrence of the unphased allele value.
10. MISSING allele values and symbolic alleles contain no relevant bases and contribute no base-modification values.
11. Unstranded base-modification information is stored at the base with the lowest POS; other values are MISSING.
12. For unstranded N modifications, the value is stored on the positive strand and the negative-strand value is MISSING.

Source locators: general Number definitions and governing prose, lines 195–218; reserved key table, lines 556–588; field-specific definitions and alias prose, lines 720–744; examples, lines 223–229 and 749–758.

### 7.2 Reserved FORMAT key families and aliases

The reserved table at lines 556–588 assigns Number=M to:
- `M[0-9]+[ACGTUN]` (Float);
- `DPM[0-9]+[ACGTUN]` (Integer);
- `ADM[0-9]+[ACGTUN]` (Integer);
- named modification aliases and their DPM/ADM counterparts.

The detailed text at lines 720–744 specifies:
- M fields are fractions of DNA or RNA bases modified with the given ChEBI ID and their values must be between 0 and 1;
- the key regex families are reserved even when the ChEBI ID does not correspond to a valid base modification;
- the named aliases should be used instead of corresponding ChEBI-keyed names;
- base-modification annotations on reference-block records apply to all applicable bases covered by that reference block;
- DPM is depth for reads able to detect the modification; ADM is depth for reads with the modification;
- ADFM/ADRM key families are explicitly not reserved.

The Number=M cardinality algorithm must be sequence- and genotype-aware. It is not a fixed count, allele count, ploidy count, or unconstrained variable-length list. A validator must derive expected positions from the allele sequence, eligible base identity, strand rules, GT allele order/phasing, and missing/symbolic-allele handling.

### 7.3 Source consistency flags requiring independent adjudication

1. The change-history text says “Reserved all FORMAT keys of the form M[0-9]+”, whereas the reserved table and detailed definitions use `M[0-9]+[ACGTUN]`. The narrower full pattern must be reconciled with the abbreviated history statement.
2. The table spells the xanthosine alias `MXaoN`; the detailed prose lists `MxaoN`. Do not silently normalize case or accept both spellings without authoritative clarification.
3. The detailed prose at line 742 says “Type=M fields” even though the reserved table places M in the Number column and uses Float/Integer in the Type column. Preserve this wording as a source inconsistency; do not invent a Type=M declaration.
4. The VCFv4.4 errata note says “Type=P added to FORMAT field type list” while VCFv4.5's reserved table uses P in the Number column for PSL/PSO/PSQ. Preserve the source wording and require review of the intended distinction between Number=P and Type=P.\n5. The first local/global example pair at VCFv4.5.tex:703-704 has GT `2/4` in the local row and `2/2` in the paired global row. This prevents a definitive GT index-mapping interpretation from being inferred from that example.

## 8. Conformance corpus requirements derived from this review

The following are test requirements to add to the VCFv4.5 corpus. They are not claims that tests already exist or have passed.

### Local allele activation and mapping
- valid LAA with one, multiple and all ALT alleles;
- LAA order differs from sorted ALT order;
- duplicate LAA index;
- zero, negative, out-of-range and non-integer LAA entries;
- LAA omitted while a non-missing local field is present;
- LAA present but all local fields omitted or MISSING;
- LAA MISSING with local payload at REF-only site;
- BCF empty-vector/MISSING round trip;
- local fields present before LAA in FORMAT order (invalid);
- GT token/index interpretation remains unresolved until the prose and first paired example discrepancy is adjudicated.

### LA/LR/LG cardinality and payloads
- LA count equals local ALT count;
- LR count equals local allele count including REF;
- LG count equals genotype combination count for local allele count and ploidy;
- haploid, diploid, triploid and higher-ploidy genotype order;
- likelihood values preserve GL/PL ordering;
- posterior values preserve GP/PP ordering;
- invalid short and long vectors;
- scalar MISSING versus explicit all-MISSING list;
- local/global field pair equivalence;
- local/global pair conflict when both are non-missing and differ;
- local/global pair with one side MISSING or omitted;
- REF-only site and the Number=LA empty-versus-missing caveat.

### Number=P
- PSL list positions align with GT alleles;
- unphased GT allele has MISSING PSL position;
- PSO missing-position preservation and ordinal ordering;
- PSQ aligns to PSL and is MISSING when PSL or quality is missing;
- haploid, diploid, polyploid and local-copy-number cases;
- symbolic-SV and breakend cases requiring PSO;
- invalid under/over-length arrays and malformed ordinal values.

### Number=M / base modifications
- valid ChEBI-keyed M/DPM/ADM names for each permitted base suffix;
- reserved-key recognition even for unknown ChEBI identifiers;
- named aliases and exact case;
- fraction boundary values 0 and 1, plus out-of-range values;
- DPM/ADM integer and non-negative constraints where explicitly specified;
- reference-block propagation over applicable bases;
- strand-specific and unstranded missing-value cases;
- non-reserved ADFM/ADRM key forms;
- explicit handling of the source wording inconsistencies listed above.

## 9. Completion boundary

This review is a source-grounded semantic decomposition for one VCFv4.5 topic. It does not establish:
- completeness of the VCFv4.5 requirement universe;
- completion of the remaining 132 VCFv4.5 table questions;
- completion of VCFv4.1–4.4 or VCFv4.0;
- independent second-person approval;
- implementation mappings or parser/validator corrections;
- executed conformance tests or passing CI;
- laboratory qualification.

The requirements ledger, source manifest, and implementation remain unchanged by this review. A later ledger update must create atomic requirements with exact source locators and preserve all open questions above rather than treating this document as independent approval.
