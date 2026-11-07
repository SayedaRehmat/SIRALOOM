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

**Decision:** keep both spellings recognized as compatibility aliases; do not rewrite, normalize, or designate either as canonical. Record the issue for upstream standards-owner adjudication. A standards maintainer must clarify whether one spelling is canonical, both are valid aliases, or the table/narrative needs correction.

## 2. Local GT example — source inconsistency with a defensible normative interpretation

VCFv4.5 defines GT allele values globally: 0 is REF and 1..N are ALT positions. The local-allele section defines LAA as 1-based indices into ALT and says LAA controls the local allele subset and order used to interpret local-allele fields.

For the source example:

- REF=G; ALT=A,C,T,<*>.
- LAA=2,4 selects local alleles [G,C,<*>] for LAD/LPL.
- GT allele values remain global ALT indexes; LAA changes only the local A/R/G vector interpretation.
- For three local alleles and diploid ploidy, LPL colexicographic order is 00, 01, 11, 02, 12, 22. The supplied LPL vector `90,80,0,100,110,120` has its minimum at local genotype 1/1, which maps to global allele 2/2 (C/C).
- The expanded PL vector likewise has its minimum at global genotype 2/2. The expanded row's GT=2/2 is therefore consistent; the local row's GT=2/4 instead calls C/<*> and is inconsistent with the paired likelihood representation.

An independent comment by `ecrum19` on upstream [samtools/hts-specs issue #871](https://github.com/samtools/hts-specs/issues/871#issuecomment-5637479778) makes this same local-row correction and explains the LPL-to-global mapping. The issue remains open; this is independent supporting review, not a standards-maintainer resolution.

**Decision:** do not reinterpret GT as local-vector indexes. Preserve global ALT allele indexes in GT; apply LAA only to the local A/R/G FORMAT vectors. Treat the source's local-row GT=2/4 as the apparent example typo; the consistent value is GT=2/2. A regression fixture now uses GT=2/2 with LAA=2,4 and checks local/global LAD/AD and LPL/PL projection equivalence.

## 3. PSL, PSO and PSQ — separate positional and cross-record obligations

The pinned source establishes these distinct rules:

- **PSL:** one phase-set entry for each GT allele value; unphased allele positions use `. `. Phase-set names are global across CHROM. A given sample-genotype cannot populate both PS and PSL. A PS identifier cannot be referenced by PSL in another record.
- **PSO:** one ordinal per GT allele position (Number=P). The ordinal describes the order in which variants are encountered on a derivative chromosome for a given phase-set name. PSO should be defined for a phase-set name if any allele carrying that name on any record is a symbolic structural variant or uses breakpoint notation. Breakpoint-notation variants must have the same PSL and PSO on both records.
- **PSQ:** Number=P and described as a list of phase-set qualities, one for each phase set in PSL. Its MISSING rule follows a missing PSL value or unknown phasing quality.

The existing implementation checks per-record Number=P cardinality, PSL's unphased-position MISSING rule, PSO/PSQ dependency on populated PSL, and MISSING alignment. The conformance fixtures cover the tandem-duplication example, repeated PSL names, and missing-position cases.

**Outstanding interpretation:** the source combines a Number=P positional definition with PSQ prose phrased as “one for each phase set in PSL.” Repeated phase-set names make it important to establish whether “each phase set” means each PSL position/occurrence or each distinct phase-set identifier. The current tests exercise positional values, but that fixture is not standards-owner adjudication. Do not promote the positional interpretation to a settled normative decision.

**Outstanding implementation gap:** current checks are record-local. They do not yet enforce the cross-record PSO obligation for a phase set that contains an SV/breakpoint allele elsewhere, nor the requirement that the two breakend records carry identical PSL and PSO. Those require a sample-aware, phase-set-aware cross-record index and explicit tests for missing/mismatched mate data. They must not be described as implemented.

## 4. Unstranded Number=M placement — explicit cross-record policy required

The source says unstranded modification information is stored at the lowest POS, with the corresponding other value MISSING or omitted. Its CpG example places the unstranded 5mC measurement at the C-containing record and leaves the subsequent G's M5mC value missing. For N modifications, the positive-strand value is stored and the negative-strand value is MISSING.

The current production implementation maps Number=M values to per-record allele-sequence offsets and strands. That is necessary but not sufficient to enforce the unstranded storage convention across records.

**Critical input distinction:** VCF Number=M does not itself declare whether a measurement is strand-specific or unstranded. The validator must not infer an unstranded assay from a missing value, a complementary base, or a neighbouring record. A future cross-record validator must be explicitly enabled by a caller-supplied unstranded representation policy (or equivalent validated assay metadata), retain the default behavior for strand-specific files, and scope comparisons by sample, contig, modification field/ChEBI identity and compatible allele/haplotype context. It must also distinguish a true MISSING value from an omitted trailing field and must not compare unrelated alleles merely because they are adjacent.

Acceptance tests must include: same-record CpG positions; CpG positions split across adjacent records; reverse-complement orientation; multiple samples; multiallelic and phased genotypes; missing and symbolic alleles; record-order/coordinate boundary cases; and explicit proof that strand-specific mode does not apply the unstranded omission rule. Until this policy and its cross-record evidence model are implemented, unstranded placement remains unsupported by strict validation and must be reported as such rather than inferred.

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
