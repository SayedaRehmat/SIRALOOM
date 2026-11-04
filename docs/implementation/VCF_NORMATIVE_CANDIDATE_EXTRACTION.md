# VCF normative candidate extraction

## Pinned source

- Repository: https://github.com/samtools/hts-specs
- Commit: `510c107ba89aa13113818c9e4fa3071283cb7f7b`
- Commit signature: verified by GitHub
- Source files: `VCFv4.1.tex` through `VCFv4.5.tex`
- Each source file is verified by its canonical Git blob SHA-1 before extraction.

## Machine-extracted candidate lines

The extractor records source line numbers, line SHA-256, enclosing section path,
and normative-language markers. It does not copy specification prose into the
repository. Its scope is limited to VCF-specific normative sections; the separate
BCF specification and historical change logs are excluded.

| Specification | Candidate lines |
|---|---:|
| VCFv4.1 | 38 |
| VCFv4.2 | 44 |
| VCFv4.3 | 82 |
| VCFv4.4 | 161 |
| VCFv4.5 | 185 |
| **Total** | **510** |

## Qualification status

**Status:** `EXTRACTED_UNREVIEWED`

These 510 entries are *candidate source lines*, not 510 proven atomic normative
clauses. Modal-language extraction can produce false positives, miss
requirements expressed without modal verbs, and place multiple requirements
on one line. The output is therefore explicitly marked:

- `review_status = UNREVIEWED`
- `traceability_status = UNMAPPED`
- `qualification_status = BLOCKED_PENDING_CLAUSE_REVIEW_AND_TRACEABILITY`

This inventory does not change the existing `PARTIAL` normative coverage
status and cannot authorize laboratory qualification.

## Required completion work

1. Human-review every candidate and split lines into atomic normative clauses.
2. Identify requirements not captured by modal-language extraction.
3. Assign stable clause IDs, version applicability, and normative strength.
4. Map every clause to production code and positive/negative tests.
5. Add independent parser differential tests and systematic fuzz/property tests.
6. Obtain independent scientific review and retain signed qualification evidence.

CI downloads the pinned official sources, verifies Git blob identities, runs the
extractor, and retains the generated JSON inventory as a qualification artifact.


## VCFv4.0 historical authority and atomic-decomposition boundary (2026-11-04)

VCFv4.0 is not present as a versioned source file in the pinned GA4GH
`samtools/hts-specs` source set used for VCFv4.1–4.5. The historical 1000
Genomes documentation is therefore a separate compatibility authority, not a
substitute for a GA4GH-maintained normative release:

- Core VCFv4.0 format description:
  https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- Historical VCFv4.0 structural-variation conventions:
  https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/
- Current format stewardship and maintained specifications:
  https://www.internationalgenome.org/wiki/Analysis/variant-call-format/
  and https://github.com/samtools/hts-specs

The historical pages are mutable web documents and do not expose a signed
source commit or immutable release artifact. Before VCFv4.0 can have a
reproducible clause inventory, the acquisition workflow must preserve the exact
retrieved bytes, retrieval timestamp, final URL, HTTP metadata where available,
and SHA-256; a later content change must create a new source revision rather
than silently replacing the old one. Until then, VCFv4.0 source traceability must be labelled
`HISTORICAL_SOURCE_UNPINNED`. This is an evidence/qualification status only:
VCFv4.0 remains a supported version target in the SIRALOOM registry, and the
missing archive must not be used to reject otherwise valid VCFv4.0 SNV or
small-INDEL files. Full conformance must not be claimed until source
preservation, atomic review, implementation/test mapping, and independent
interoperability evidence are complete.

## Atomic clause definition and review contract

A candidate is an atomic requirement only when it expresses one independently
verifiable obligation, prohibition, permission, or recommendation for one
actor and one observable condition. The decomposition must:

1. Preserve the source's modal force (MUST/SHALL, SHOULD, MAY, or descriptive
   non-normative text); do not promote recommendations or examples to MUST.
2. Split conjunctions when each side can independently pass or fail; retain
   shared qualifiers and exceptions on each resulting clause.
3. Preserve cross-references, table rows, footnotes, grammar productions,
   enumerated constraints, and definitions that carry normative meaning—even
   when they contain no modal verb.
4. Record exact source document, immutable revision/hash, page/section/anchor,
   source line range (where available), and a normalized source excerpt hash.
5. Record applicability separately for every version. A later-version rule
   must not be backported to earlier versions without source support.
6. Map each clause to an exact implementation symbol and executable test IDs.
   A family-level mapping is insufficient. Positive, negative, and boundary
   tests are required where the clause admits those cases; otherwise record a
   reasoned `NOT_APPLICABLE` disposition.
7. Distinguish format requirements from producer conventions, implementation
   recommendations, external index/compression specifications, and SIRALOOM
   operational policy. Those must not be falsely attributed to VCF normative
   text.
8. Require independent review. Automated sentence splitting may propose
   clauses but cannot set `REVIEWED` or `CONFORMANT`.

The existing 510 VCFv4.1–4.5 candidate lines remain unreviewed inputs to this
process. They are not the atomic clause count, and their extraction does not
prove completeness because normative constraints also occur in tables,
examples, grammar, definitions, and non-modal prose.
