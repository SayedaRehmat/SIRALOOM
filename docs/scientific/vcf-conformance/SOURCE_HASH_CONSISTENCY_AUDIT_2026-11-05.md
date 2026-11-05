# VCF source hash consistency audit

**Audit date:** 2026-11-05  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Scope:** Exact-byte SHA-256 verification for archived VCFv4.1–4.5 source files and dependent ledger references  
**Status:** BYTE-LEVEL VERIFIED AND RECONCILED FOR VCFv4.1–4.5; VCFv4.0 REMAINS BLOCKED

## Finding

The source manifest and dependent ledger references previously used SHA-256 values that did not match the exact committed source-file bytes. The earlier audit reconciled ledger references to the then-current manifest values but explicitly had not recomputed SHA-256 from downloaded byte streams. That reconciliation was insufficient to establish byte-level digest correctness.

## Verification method

- Retrieved each committed VCFv4.1–4.5 source file through GitHub's Base64 file-content response.
- Decoded Base64 directly to bytes; did not decode to text, normalize line endings, trim whitespace, or reserialize.
- Independently computed SHA-256 over each exact byte array.
- Checked the SHA-256 implementation against the standard `abc` known-answer vector.
- Confirmed the archived Git blob SHA-1 values match the pinned upstream hts-specs source blob IDs at commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`.

## Verified source digests

| Source | Exact byte length | Git blob SHA-1 | Independently recomputed SHA-256 |
|---|---:|---|---|
| VCFv4.1.tex | 95857 | 420cee83a66259600a70de36721763cc374df1e3 | `7d29ef8f93745f246202da3e32107ea13b036bbefcb31f7971a3ce31f1045baa` |
| VCFv4.2.tex | 96701 | 70e595cdad351b3fb12e121850d7e6c8c5f67c88 | `66dbd167e8fb309708e0956ffbb12808bd338a703fbf034d80d1ead56ae480cc` |
| VCFv4.3.tex | 119335 | 01671b89e21fc1bca414b639a4ea483194f127a9 | `332d8b910ac9952bfba04374118f8c4f318ea996d5017599e68f80379fd61cde` |
| VCFv4.4.tex | 149282 | 31cb66283ea40c3df51e488c5fffe826fd8dedaf | `4c88884cf6b016efcec691d5186432a2e0b679396204d14770e89839ef536e1a` |
| VCFv4.5.tex | 164356 | 307950e7eeafc33d524969ff906343f756adb7d7 | `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5` |

## Ledger reconciliation

- Total source references: 437.
- References to archived VCFv4.1–4.5 files: 436.
- Source-file SHA-256 values changed to exact-byte verified values: 436.
- Remaining mismatched source-file SHA-256 values among archived VCF sources: 0.
- VCFv4.0 historical candidate references without a pinned source-file digest: 1.
- Excerpt hashes, source locators, requirement statements, applicability decisions and review statuses were not changed.

The manifest's five `raw_source_sha256` values and every dependent VCFv4.1–4.5 ledger `source_sha256` reference now use the exact-byte verified values above.

## VCFv4.0 remains unresolved

No original VCFv4.0 core source bytes or SHA-256 were captured. The historical IGSR page remains a discovery candidate, not an accepted immutable normative source. The separate 1000 Genomes structural-variation page remains a project/producer convention source and must not be merged into core VCFv4.0 requirements.

## Verification boundary

This audit verifies exact bytes of the archived source blobs and their Git blob identity against the pinned upstream source blob IDs. It does not establish full specification coverage, independent standards approval, implementation conformance, clause-specific test execution or laboratory qualification. Upstream commit signature verification was not repeated in this capture.
