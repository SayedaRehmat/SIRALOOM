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

## 3. PSL, PSO and PSQ positional semantics

The source states that PSL contains one phase-set entry for each allele value in GT, with `.` at unphased allele positions. PSO is a list of phase-set ordinals; its tandem-duplication example gives three PSO values aligned with the three GT/PSL positions. PSQ is a list of phase-set qualities corresponding to the phase sets in PSL, and its missing-value rule explicitly follows the corresponding PSL value.

**Decision for executable conformance:** treat PSL, PSO and PSQ as parallel Number=P vectors aligned by GT allele position. A repeated phase-set name at two GT positions still occupies two positions in each vector. Require `.` in PSO/PSQ wherever the corresponding PSL position is missing. The validator already enforces Number=P cardinality and missing alignment; new tests now exercise the source PSO example, repeated PSL names with PSQ, and missing-position failures.

This interpretation follows the source examples and Number=P definition. It does not infer that PSO is a unique-name keyed map.

## 4. Number=M biological position oracle

A new pure helper enumerates the expected per-allele sequence slots:

- Specific base IDs: a matching sequence base maps to the positive strand; its complement maps to the negative strand; slots remain in sequence order.
- U is treated as T.
- N emits positive then negative slots for each sequence position.

Tests cover the normative CGA/M5mC example, reverse sequence orientation, A/T complements, U/T equivalence and the positive-then-negative ordering for N.

**Validation boundary:** this oracle tests expected biological slot order and strand assignment independently of the submitted values. It does not prove that an arbitrary unlabelled numeric vector has been populated with biologically correct values. The VCF record does not attach explicit base/strand labels to each numeric value; actual assignment requires trusted source observations or a higher-level data model. Ambiguous sequence symbols are rejected by the helper pending a separate specification interpretation.

## 5. Independent review status and acceptance criteria

No independent standards review has been obtained by this change. PR #293 remains the review vehicle; no reviewer identity was supplied or assigned. This document must not be represented as independent approval.

Required external decisions:

1. Confirm canonical xanthosine alias spelling or publish an erratum.
2. Confirm the local-row GT=2/2 correction identified in upstream issue #871.
3. Confirm per-position PSO/PSQ alignment, especially repeated phase-set names and missing positions; upstream issue #868 also requests examples for Number=P/PSL/PSO/PSQ.
4. Review Number=M strand/base slot derivation and ambiguous sequence handling.

Until those decisions are recorded with reviewer identity, date, source citations and disposition, VCFv4.5 remains unqualified.

## 6. Pinned-source locators

The adjudication above is grounded in the archived source and can be checked against the immutable upstream source revision:

- [VCFv4.5 Number=M and base/strand ordering, lines 192–218](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L192-L218)
- [VCFv4.5 global GT allele numbering, lines 613–627](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L613-L627)
- [VCFv4.5 LAA and local-allele example, lines 686–718](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L686-L718)
- [VCFv4.5 reserved FORMAT table, lines 534–596](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L534-L596)
- [VCFv4.5 base-modification alias narrative, lines 720–744](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L720-L744)
- [VCFv4.5 PSL, PSO and PSQ definitions and examples, lines 755–810](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7/VCFv4.5.tex#L755-L810)

The current upstream source is also accessible at [samtools/hts-specs VCFv4.5.tex](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex). The current upstream table/narrative spelling discrepancy is visible in the reserved table and base-modification narrative; it has not been silently resolved by this branch.
