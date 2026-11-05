# VCF source hash consistency audit

**Audit date:** 2026-11-05  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Scope:** Source-file SHA-256 consistency for the 142-record candidate ledger  
**Status:** RECONCILED FOR VCFv4.1–4.5; VCFv4.0 REMAINS BLOCKED

## Finding

The ledger contained multiple values in the `source_sha256` field for the same pinned source file and the same upstream Git blob/revision. A source-file digest must identify one exact byte stream. Different SHA-256 values cannot all identify the same pinned source bytes.

The source manifest records one SHA-256 per archived source file. The five source files fetched from the SIRALOOM branch were checked against the manifest's upstream Git blob SHA-1 values; all five archived blob IDs matched. The ledger's `source_sha256` references were then reconciled to the corresponding manifest SHA-256 values.

## Reconciliation

| Source | Canonical SHA-256 from source manifest | Ledger references reconciled |
|---|---|---:|
| VCFv4.1.tex | `3b6ed80608c11b9d14bb6bcc10273a62d09509e89daf7ca8261c675b2a509003` | 34 |
| VCFv4.2.tex | `a39124783365a22f66ce3c124779ffe2fe4655aea5a0efb5d17e75fb1d2c6f51` | 34 |
| VCFv4.3.tex | `09dd557b11916c8b93f025b1f756bddda0fbab0fc199bea751a8110189ab8d48` | 38 |
| VCFv4.4.tex | `0d6014ae1ffc6ab7929c00eba724c9dacf8d0064df27f987e30f7be3a3442eb1` | 85 |
| VCFv4.5.tex | `2c2f9e77a318112fde21ad8823fdcb8e12a6cf56069a7dfbe21aed891a04d1b2` | 129 |

- Ledger source references with archived VCF source files: 352.
- References already using the canonical source-file SHA-256: 32.
- References corrected: 320.
- Remaining source-file SHA-256 mismatches: 0.
- References without source SHA-256: 1 (the VCFv4.0 historical candidate).
- Unique requirement IDs: 142/142.

The 320 corrected references are source-file digest metadata corrections only. Their source locators, excerpt hashes, requirement statements, applicability decisions and review statuses were not changed.

## Verification boundary

For each VCFv4.1–4.5 archived source file, the Git blob SHA-1 returned by GitHub for the SIRALOOM archive matched the upstream source blob SHA-1 recorded in the source manifest at hts-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`.

The canonical SHA-256 values above were taken from the existing source manifest capture record. This audit did **not** independently recompute SHA-256 over downloaded raw byte streams. A future byte-level verification should recompute the digests from the exact archived bytes in a controlled environment and compare them with this manifest.

## VCFv4.0 remains unresolved

No VCFv4.0 source bytes or SHA-256 were introduced by this correction. The historical IGSR core page remains a corroborated discovery candidate, not an accepted immutable normative source. The separate 1000 Genomes structural-variation page remains a producer/project convention source and must not be merged into the core VCFv4.0 requirement set.

## What this audit does not establish

This correction does not complete whole-specification coverage, VCFv4.0 provenance, per-version applicability, independent standards review, implementation mappings, clause-specific test execution, parser/normalizer conformance or laboratory qualification. All 142 candidate requirements remain in review.

## Changed artifacts

- `atomic-requirements.v1.json`: 320 `source_sha256` values reconciled.
- `independent-standards-review-readiness.v1.json`: audit outcome and remaining limitation recorded.

