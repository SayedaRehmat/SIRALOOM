# VCFv4.0 historical core-source discovery audit

**Audit date:** 2026-11-06  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Scope:** Determine whether the historical VCFv4.0 core source can be pinned from the currently identified authoritative repositories and distinguish it from 1000 Genomes producer-specific structural-variation conventions.  
**Disposition:** `SOURCE_CANDIDATE_IDENTIFIED — IMMUTABLE_SOURCE_BYTES_NOT_CAPTURED — NOT_QUALIFIED`

## Executive finding

The current HTS-specs canonical repository documents VCFv4.1 through VCFv4.5 as its maintained VCF specification files; its current specification index does not list a VCFv4.0 source file. The International Genome Sample Resource (IGSR), successor resource for 1000 Genomes data, retains a page explicitly titled “VCF (Variant Call Format) version 4.0”. That page is useful historical evidence and a source candidate for the VCFv4.0 core format, but the discovery performed in this audit does not establish an immutable original publication artifact, original revision identifier, exact source-byte payload, or cryptographic digest.

Therefore this audit does **not** promote the VCFv4.0 candidate to a pinned normative source, does not calculate or invent a source SHA-256, and does not change any VCFv4.0 requirement or applicability disposition. The existing VCFv4.0 source blocker remains in force.

## Source discovery evidence

### A. Current HTS-specs inventory

- Repository: https://github.com/samtools/hts-specs
- Specification index: https://github.com/samtools/hts-specs/blob/master/index.md
- Repository overview: https://github.com/samtools/hts-specs

The published inventory lists VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4 and VCFv4.5. It identifies VCFv4.5 as the canonical current specification and the other listed files as predecessors. VCFv4.0 is absent from this maintained source inventory. This is evidence that the current canonical repository is not, by itself, a source for the historical VCFv4.0 document; it is not evidence that VCFv4.0 never had a specification.

### B. IGSR historical VCFv4.0 page

- Page title: “VCF (Variant Call Format) version 4.0”
- URL: https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- Alternate detailed page discovered: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/vcf-variant-call-format-version-40/

The IGSR page explicitly labels its subject VCF version 4.0 and describes core concepts including meta-information, fixed fields, INFO fields, FORMAT fields, genotype representation and missing values. It is the strongest historical core-format candidate found in this discovery pass.

However, the accessible web page is a rendered web resource. This audit did not retrieve and preserve an authoritative original source artifact with a verifiable publication revision and exact original bytes. A browser-rendered page, search index extract, reconstructed text, or copied excerpt must not be represented as the original normative source bytes.

### C. 1000 Genomes structural-variation conventions — separate source class

- Page title: “Encoding Structural Variants in VCF (Variant Call Format) version 4.0”
- URL: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/

The page expressly describes conventions and extensions adopted by the 1000 Genomes Project for encoding structural variations in VCF 4.0. Its stated scope is producer/project-specific SV conventions. It must remain a separate source class and must not be merged into universal VCFv4.0 core requirements.

### D. Historical release corroboration

The IGSR announcements archive records a July 20, 2010 pilot-project variant-call release in VCF 4.0 format. This corroborates historical use of the version by the project, but a release announcement is not a substitute for the complete normative specification artifact.

- URL: https://www.internationalgenome.org/announcements/

## Provenance and qualification decision

| Check | Finding | Status |
|---|---|---|
| Historical VCFv4.0 core candidate located | IGSR VCFv4.0 page | PASS — discovery only |
| Candidate explicitly identifies VCF 4.0 | Yes | PASS — page-level evidence |
| Current HTS-specs inventory contains VCFv4.0 | No; inventory begins at VCFv4.1 | CONFIRMED ABSENT FROM CURRENT INVENTORY |
| Original immutable publication artifact captured | No | BLOCKED |
| Original revision/version identifier captured | No | BLOCKED |
| Exact original source bytes preserved | No | BLOCKED |
| SHA-256 computed over original source bytes | No | BLOCKED — intentionally not fabricated |
| Core source distinguished from project SV conventions | Yes | PASS |
| Independent standards review | Not performed | NOT REVIEWED |
| VCFv4.0 requirement ledger promoted | No | NOT PROMOTED |

## Required next actions before source promotion

1. Locate the original VCFv4.0 publication artifact or a historically authoritative archived copy whose provenance can be defended. Prefer a dated/versioned source artifact over a modern rendered wiki page.
2. Record the artifact's publisher/maintainer, title, publication or revision date, stable retrieval URI, archive/repository identifier, media type, and retrieval timestamp.
3. Preserve the retrieved artifact byte-for-byte in the research source archive. Do not normalize line endings, reserialize markup, or hash extracted text as though it were the original source.
4. Independently recompute SHA-256 from the preserved bytes; record byte length and digest. If an upstream Git blob exists, verify its Git object identity separately.
5. Have a second reviewer verify that the artifact is the historical VCFv4.0 core specification rather than a producer guide, tutorial, release announcement, or SV extension.
6. Only after those checks pass, update the source manifest and source-reference ledger, propagate dependent hashes, and run a manifest-to-ledger consistency audit.
7. Decompose the source into atomic normative requirements and map each requirement to exact source locations. Keep the 1000 Genomes SV convention document in a separate producer-convention ledger.

## Non-claims

This discovery audit does not establish complete VCFv4.0 coverage, source-byte provenance, parser or validator conformance, implementation mapping, clause-specific test execution, independent standards approval, or laboratory qualification. The 226-record candidate ledger and all existing VCFv4.0 `SOURCE_NOT_PINNED` statuses remain unchanged.


## Follow-up inspection of the detailed IGSR page

A direct inspection of the detailed IGSR page at:

https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/vcf-variant-call-format-version-40/

returned a rendered HTML document with 245 extracted lines. The visible page includes:

- explicit VCFv4.0 designation and an example carrying `##fileformat=VCFv4.0`;
- meta-information syntax and allowed historical types;
- the eight fixed columns and optional FORMAT/sample columns;
- fixed-field semantics and the reserved INFO keywords;
- GT, DP, FT, GL, GQ and HQ descriptions plus missing-value and trailing-field text;
- the haplotype/allele representation discussion and worked SNP, insertion, deletion, multiallelic and mixed examples;
- an explicit cross-reference to the separate 1000 Genomes SV conventions page.

The visible footer identifies EMBL-EBI and a rolling site copyright range (2008–2026). The inspected page does not expose an original VCFv4.0 publication revision, a historical source commit, or a stable artifact digest. The current rendered HTML is therefore valuable for content review and source-location planning, but it cannot be silently substituted for the original immutable normative artifact.

This follow-up strengthens the candidate identification and confirms that the page contains substantial core-format content. It does not change the provenance decision above: exact original source bytes and a defensible original revision remain unavailable, so VCFv4.0 remains `SOURCE_NOT_PINNED`.
