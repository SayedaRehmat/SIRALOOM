# VCFv4.5 ambiguity adjudication and semantic test addendum

**Date:** 2026-11-07  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Pinned source:** `samtools/hts-specs` commit `510c107ba89aa13113818c9e4fa3071283cb7f7`, `VCFv4.5.tex`  
**Scope:** source-level adjudication and executable test expansion; not independent approval or laboratory qualification.

## 1. Xanthosine alias spelling — unresolved source defect

The pinned specification is internally inconsistent:

- Reserved genotype table (source lines 586–588): `MXaoN`, `DPMXaoN`, `ADMXaoN`.
- Base-modification narrative alias lists (lines 724, 734, 740) and unstranded example (line 218): `MxaoN`, `DPMxaoN`, `ADMxaoN`.

The current upstream `samtools/hts-specs` VCFv4.5 source still exposes the same table/narrative discrepancy: the table contains uppercase-X aliases while the narrative recommends lowercase-x aliases. Neither a canonical spelling nor a versioned erratum was located in the reviewed source context.

**Decision:** keep both spellings recognized as compatibility aliases; do not rewrite, normalize, or designate either as canonical. Record the issue for upstream standards-owner adjudication. A standards maintainer must clarify whether one spelling is canonical, both are valid aliases, or the table/narrative needs correction. New production-validator conformance tests now exercise all six table/narrative spellings (fraction, total-detectable depth and modified-base depth) and assert that the original field ID is preserved in each slot assignment. Passing these tests establishes compatibility handling only; it does not adjudicate canonical spelling.

## 2. Local GT example — source inconsistency with a defensible normative interpretation

VCFv4.5 defines GT allele values globally: 0 is REF and 1..N are ALT positions. The local-allele section defines LAA as 1-based indices into ALT and says LAA controls the local allele subset and order used to interpret local-allele fields.

For the source example:

- REF=G; ALT=A,C,T,<*>.
- LAA=2,4 selects local alleles [G,C,<*>] for LAD/LPL.
- GT allele values remain global ALT indexes; LAA changes only the local A/R/G vector interpretation.
- For three local alleles and diploid ploidy, LPL colexicographic order is 00, 01, 11, 02, 12, 22. The supplied LPL vector `90,80,0,100,110,120` has its minimum at local genotype 1/1, which maps to global allele 2/2 (C/C).
- The expanded PL vector likewise has its minimum at global genotype 2/2. The expanded row's GT=2/2 is therefore consistent; the local row's GT=2/4 instead calls C/<*> and is inconsistent with the paired likelihood representation.

An independent comment by `ecrum19` on upstream [samtools/hts-specs issue #871](https://github.com/samtools/hts-specs/issues/871#issuecomment-5637479778) makes this same local-row correction and explains the LPL-to-global mapping. The issue remains open; this is independent supporting review, not a standards-maintainer resolution. The conformance suite now retains both fixtures: the normalized/corrected GT=2/2 example, and the literal source-row GT=2/4 example, which confirms that GT allele values remain global ALT indexes and that LAA projection does not reinterpret GT as local indexes. The latter fixture does not assert that GT must equal the minimum-PL genotype; that relationship is not a general VCF syntax invariant.

**Decision:** do not reinterpret GT as local-vector indexes. Preserve global ALT allele indexes in GT; apply LAA only to the local A/R/G FORMAT vectors. Treat the source's local-row GT=2/4 as the apparent example typo; the consistent value is GT=2/2. A regression fixture now uses GT=2/2 with LAA=2,4 and checks local/global LAD/AD and LPL/PL projection equivalence.

## 3. PSL, PSO and PSQ — separate positional and cross-record obligations

The pinned source establishes these distinct rules:

- **PSL:** one phase-set entry for each GT allele value; unphased allele positions use `. `. Phase-set names are global across CHROM. A given sample-genotype cannot populate both PS and PSL. A PS identifier cannot be referenced by PSL in another record.
- **PSO:** one ordinal per GT allele position (Number=P). The ordinal describes the order in which variants are encountered on a derivative chromosome for a given phase-set name. PSO should be defined for a phase-set name if any allele carrying that name on any record is a symbolic structural variant or uses breakpoint notation. Breakpoint-notation variants must have the same PSL and PSO on both records.
- **PSQ:** Number=P and described as a list of phase-set qualities, one for each phase set in PSL. Its MISSING rule follows a missing PSL value or unknown phasing quality.

The existing implementation checks per-record Number=P cardinality, PSL's unphased-position MISSING rule, PSO/PSQ dependency on populated PSL, and MISSING alignment. The conformance fixtures cover the tandem-duplication example, repeated PSL names, and missing-position cases.

**Adjudication for this implementation:** PSQ is interpreted positionally, with one entry for each GT allele position / PSL list position, not one entry per distinct phase-set identifier. This follows the explicit FORMAT Number=P definition (“one value for each allele value defined in GT”), the reserved PSQ Number=P declaration, and the immediately following requirement that a missing PSQ value correspond to the corresponding missing PSL value. Repeated PSL identifiers therefore remain repeated positions and may carry different PSQ values. A distinct-identifier cardinality would contradict Number=P and make positional MISSING alignment ill-defined. The implementation validates positional cardinality and alignment; tests now exercise repeated identifiers with distinct values and multiple distinct identifiers.

This resolves the implementation interpretation from the pinned specification's internal rules. It is not an upstream standards-maintainer ruling: upstream issue [#868](https://github.com/samtools/hts-specs/issues/868) asks for examples using Number=P/PSL/PSO/PSQ and remains open. The issue does not itself adjudicate repeated-identifier semantics.

**Cross-record implementation now present on the research branch:** the validator records PSL/PSO occurrences by sample and phase-set identifier across the complete file. If any allele in a sample/phase-set is a recognized symbolic SV allele (DEL, INS, DUP, INV, CNV and their subtypes) or a breakend, every occurrence of that phase-set must carry a non-MISSING PSO. The SV trigger deliberately excludes the non-variant placeholders `<*>` and `<NON_REF>`. For reciprocal breakend records, the validator compares the complete per-sample PSL and PSO vectors and rejects mismatches. Regression tests cover a phase-set-wide missing PSO, fully defined PSO, and matched/mismatched reciprocal breakend vectors.

**Remaining boundaries:** this implementation is sample-aware and file-wide, but does not yet model derivative chromosome reconstruction or prove that PSO ordinals are globally unique/monotonic within a phase set; the cited source defines ordering but does not supply a complete algorithm for such a check. It also compares the full PSL/PSO vectors for reciprocal BND mates, an intentionally strict operational interpretation that still needs standards-owner adjudication.

## 4. Unstranded Number=M placement — explicit cross-record policy required

The source says unstranded modification information is stored at the lowest POS, with the corresponding other value MISSING or omitted. Its CpG example places the unstranded 5mC measurement at the C-containing record and leaves the subsequent G's M5mC value missing. For N modifications, the positive-strand value is stored and the negative-strand value is MISSING.

**Explicit policy and cross-record implementation now present on the research branch:** `validate_vcf_strict` accepts `base_modification_strandedness=None|"stranded"|"unstranded"`. The default `None` preserves existing validation and does not infer assay strandedness. `"stranded"` does not apply the unstranded omission rule. Only explicit `"unstranded"` enables the additional placement checks.

For unstranded mode, populated Number=M vectors are projected to per-sample observations carrying contig, genomic coordinate, modification field, GT copy index, phase-set identity, base, strand and value. The validator then:
- checks complementary base pairs within one record and across adjacent records;
- requires the value at the higher POS of a complementary pair to be MISSING, regardless of which strand has the lower POS;
- requires negative-strand values for Number=M fields ending in N to be MISSING;
- joins records only when sample, contig, field, phased GT copy and phase-set context agree;
- uses record-local allele context for unphased alleles rather than joining unphased calls across records;
- reports `VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT` for a populated higher-POS value and `VCF_BASE_MODIFICATION_UNSTRANDED_UNSUPPORTED` when a length-changing allele prevents safe coordinate projection.

The regression suite now covers same-record and adjacent-record CpG pairs, reverse orientation, multiple samples, distinct phase sets, called multiallelic alleles, missing values, explicit stranded/default behavior and the unsupported length-changing-allele boundary.

**Remaining limitations:** cross-record matching is intentionally restricted to equal-length allele/reference representations so that `POS + sequence offset` remains a defensible coordinate map. Unphased calls are validated within their own record/allele context but are not joined across records. Complex indels, overlapping allele representations that cannot be mapped one-to-one, and cases requiring haplotype reconstruction beyond the encoded phase-set/copy context remain unsupported in unstranded mode; the validator rejects length-changing alleles rather than guessing. The current tests do not establish laboratory qualification or assay-level truth of modification fractions.

## 5. Number=M production validation and biological slot mapping

The production `validate_vcf_strict` path now derives an ordered slot map for every populated Number=M FORMAT value, rather than calculating only a count:

- Each slot is keyed to the global GT allele index, zero-based offset in that allele sequence, observed sequence base, and strand.
- A specific base ID maps the matching base to the positive strand and its complement to the negative strand; slots retain sequence order.
- U is treated as T. N emits positive then negative slots at every sequence position.
- GT allele order is retained; repeated identical unphased allele indexes are aggregated once at first occurrence, while phased copies remain distinct. Missing and symbolic alleles contribute no slots.
- The validator applies numeric type/range validation to each value and binds each comma-separated vector element to its derived slot in order.

The validator always reports `base_modification_slot_assignment_count`. Call `validate_vcf_strict(..., include_base_modification_slot_assignments=True)` to obtain the detailed per-value mapping, including record/sample provenance, allele index, sequence offset/base, strand, vector index and value. This makes the positional interpretation inspectable and auditable in production validation output.

Tests exercise the normative CGA/M5mC example, reverse sequence orientation, A/T complements, U/T equivalence, N's positive-then-negative order, genotype allele order, phased/unphased duplicate behavior, missing values and the actual production validator mapping.

**Evidence boundary:** the validator now enforces and exposes the documentation-defined value-to-slot assignment. It cannot independently establish whether a caller's reported fraction/depth is experimentally true; that requires the underlying read-level or assay evidence. This is a limit of the evidence carried by VCF, not a gap in applying the VCF positional semantics.

## 6. Independent review status and acceptance criteria

No independent standards review has been obtained by this change. PR #293 remains the review vehicle; no reviewer identity was supplied or assigned. This document must not be represented as independent approval.

Required external decisions:

1. Confirm canonical xanthosine alias spelling or publish an erratum.
2. Confirm the local-row GT=2/2 correction identified in upstream issue #871.
3. Resolve PSQ's per-PSL-phase-set wording against Number=P when phase-set names repeat; upstream issue #868 requests clearer examples.
4. Define and review the cross-record PSO requirements for SV/breakpoint phase sets and reciprocal breakend consistency.
5. Review Number=M strand/base slot derivation and ambiguous sequence handling, including the explicit unstranded cross-record policy above.

Until those decisions are recorded with reviewer identity, date, source citations and disposition, VCFv4.5 remains unqualified.

## 7. Pinned-source locators

The adjudication above is grounded in the archived source and can be checked against the immutable upstream source revision:

- [VCFv4.5 Number=M and base/strand ordering, lines 192–218](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L192-L218)
- [VCFv4.5 global GT allele numbering, lines 613–627](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L613-L627)
- [VCFv4.5 LAA and local-allele example, lines 686–718](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L686-L718)
- [VCFv4.5 reserved FORMAT table, lines 534–596](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L534-L596)
- [VCFv4.5 base-modification alias narrative, lines 720–744](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L720-L744)
- [VCFv4.5 PSL, PSO and PSQ definitions and examples, lines 755–810](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L755-L810)

The current upstream source is also accessible at [samtools/hts-specs VCFv4.5.tex](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex). The current upstream table/narrative spelling discrepancy is visible in the reserved table and base-modification narrative; it has not been silently resolved by this branch.
