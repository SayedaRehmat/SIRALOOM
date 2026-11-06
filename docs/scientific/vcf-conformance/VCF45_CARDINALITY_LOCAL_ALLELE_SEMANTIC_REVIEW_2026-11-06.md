# VCFv4.5 cardinality and local-allele semantic review

**Review date:** 2026-11-06  
**Specification:** VCFv4.5 at HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`  
**Source file:** `VCFv4.5.tex`  
**Source Git blob:** `307950e7eeafc33d524969ff906343f756adb7d7`  
**Source SHA-256:** `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5`  
**Disposition:** `SOURCE_REVIEWED_FOR_THIS_TOPIC — IMPLEMENTATION_AND_CONFORMANCE_NOT_ASSESSED`

## 1. Scope and evidence boundary

This review extracts the VCFv4.5 source semantics relevant to FORMAT cardinalities `P`, `M`, `LA`, `LR`, and `LG), and to local-allele projection/equivalence. Source line numbers below refer to the exact pinned `VCFv4.5.tex` bytes identified above. This is a focused semantic review, not a whole-specification review or an independent second-person approval.

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

### 3.3 Global GT indices versus local likelihood domain

The source's worked example at lines 703–710 retains GT values such as `2/4` while LAA is `2,4`; the corresponding LPL vector is reduced to the six genotypes over REF, ALT[2], ALT[4]. This demonstrates that the GT allele identifiers in the example remain record-level ALT indices, while the local likelihood vector is indexed over the local-allele domain.

Do not rewrite GT allele numbers to local ordinals as a side effect of decoding LPL/LGL/LGP/LPP. The implementation must maintain separate, explicit mappings for:
- global VCF allele index;
- local allele ordinal in the LAA-derived domain;
- genotype tuple/index in the local genotype-ordering domain.

### 3.4 Worked projection example from the source

Source lines 703–704:

- Global ALT: `A,C,T,<*>`
- LAA: `2,4`
- Local allele domain: `REF, C, <*> `
- GT: `2/4`
- LAD: three values (REF, local ALT 1, local ALT 2)
- LPL: six diploid genotype values in local ordering

For diploidy and three local alleles, the genotype order is:

`00, 01, 11, 02, 12, 22`

The equivalent global AD/PL representation uses full record allele space and missing entries for excluded alleles. The source gives both encodings as equivalent records. Conformance tests must compare the decoded semantic values, not merely compare raw vectors.

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

The reserved table defines:
- PSL: Number=P, String;
- PSO: Number=P, Integer;
- PSQ: Number=P, Integer.

Source lines 742–743 of the version-change history say Number=P was added for fields whose cardinality matches sample ploidy/local copy number. The detailed definitions at lines 747 onward (and subsequent PSL/PSO/PSQ definitions) provide field-specific list semantics:

- PSL is a list of phase sets, one for each allele value specified in GT. Unphased alleles (no preceding `|`) use MISSING at the corresponding list position.
- PSO is a list of phase-set ordinals. Its MISSING value is used when the corresponding PSO value is missing. It describes derivative-chromosome traversal order; it is required in the specified symbolic-SV/breakpoint circumstances.
- PSQ is the list of phasing-quality values, one for each phase set in PSL. MISSING is used when the corresponding PSL value is missing or phasing quality is unknown.

The source's examples show per-allele list alignment for PSL/PSO and matching PSQ positions. A validator must retain the distinction between:
- Number=P as the declared cardinality class;
- actual list semantics for each key;
- ploidy/local-copy-number context;
- MISSING entries, which preserve positional alignment.

**Open review item:** independently reconcile the general Number=P phrase (“sample ploidy/local copy number”) against all PSL/PSO/PSQ field-specific list definitions and examples. Do not impose a simplistic `len(value) == GT ploidy` rule without handling the PSL/PSO/PSQ alignment rules and the relevant local-copy-number cases.

## 7. Number=M and base-modification fields

The reserved table at lines 556–588 assigns Number=M to:
- `M[0-9]+[ACGTUN]` (Float);
- `DPM[0-9]+[ACGTUN]` (Integer);
- `ADM[0-9]+[ACGTUN]` (Integer);
- named modification aliases and their DPM/ADM counterparts.

The detailed text at lines 720–744 specifies:
- M fields are fractions of DNA or RNA bases modified with the given ChEBI ID;
- the key regex families are reserved even when a ChEBI ID does not correspond to a valid base modification;
- values are in [0,1];
- the named aliases should be used instead of corresponding ChEBI-keyed names;
- base-modification annotations on reference-block records apply to all applicable bases covered by that reference block;
- DPM is depth able to detect the modification; ADM is depth with the modification;
- the unstranded ADFM/ADRM forms are explicitly not reserved; the text states that Number=M fields are intrinsically stranded.

**Unresolved source-semantic question:** this focused source review has not found a standalone general definition of the cardinality symbol `M` comparable to the explicit LAA/LA/LR/LG prose. The field-specific descriptions and reference-block semantics must be decomposed further before writing a generic cardinality validator for `M`. Do not reinterpret `M` as a fixed integer, allele count, ploidy, or arbitrary variable length without source-backed evidence.

**Source consistency flags for independent review:**
1. The change-history text says “Reserved all FORMAT keys of the form M[0-9]+”, whereas the reserved table and detailed definitions use `M[0-9]+[ACGTUN]`. The narrower full pattern must be reconciled with the abbreviated history statement.
2. The table spells the xanthosine alias `MXaoN`; the detailed prose lists `MxaoN`. Do not silently normalize this case discrepancy.
3. The detailed prose at line 742 says “Type=M fields” even though the reserved table places M in the Number column and uses Float/Integer in the Type column. Treat this as a source wording inconsistency for second-person review, not as permission to invent a Type=M declaration.
4. The VCFv4.4 errata note says “Type=P added to FORMAT field type list” while the VCFv4.5 reserved table uses P in the Number column for PSL/PSO/PSQ. Preserve the source wording and require review of the intended distinction between Number=P and Type=P.

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
- GT remains global allele-indexed while local payloads use the LAA-derived domain.

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
