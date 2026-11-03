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
repository.

| Specification | Candidate lines |
|---|---:|
| VCFv4.1 | 60 |
| VCFv4.2 | 66 |
| VCFv4.3 | 119 |
| VCFv4.4 | 205 |
| VCFv4.5 | 230 |
| **Total** | **680** |

## Qualification status

**Status:** `EXTRACTED_UNREVIEWED`

These 680 entries are *candidate source lines*, not 680 proven atomic normative
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
