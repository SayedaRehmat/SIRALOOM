# SIRALOOM VCF Intake Contract and Laboratory Verification Matrix

## Purpose and boundary

SIRALOOM consumes variant call data produced by an upstream assay/caller. It does not perform FASTQ quality control, alignment, variant calling, joint genotyping, or assay validation. A syntactically valid VCF is not proof that the upstream assay or caller is analytically valid. Laboratories must qualify the complete intended process, including upstream assay, calling pipeline, reference build, file transfer, SIRALOOM normalization, annotation, interpretation, review, and report generation.

The immutable uploaded artifact and its SHA-256 remain the source record. Derived normalized artifacts must retain the source-record/allele mapping and tool/resource provenance.

## Version policy

The validator recognizes VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, and VCFv4.5. VCFv4.5 is the current version in the upstream HTS specifications. There is no VCFv5.0 specification in the supported HTS specifications set; unknown/future major versions are rejected rather than guessed.

The parser applies version-specific rules where implemented:
- VCFv4.4 and VCFv4.5 leading genotype phasing separators are parsed without inflating ploidy.
- VCFv4.5 FORMAT cardinalities LA, LR, LG, P, and M are recognized. Local-allele fields require LAA in the prescribed position and validate distinct, in-range 1-based ALT indices.
- VCFv4.5 reserved FORMAT/LEN (Number=1, Integer) is recognized with or without an explicit header declaration. It defines a sample-specific <*> reference block from POS through POS+LEN-1; legacy INFO/END is the documented fallback when that sample has no LEN. <NON_REF> is treated as the <*> alias.
- VCFv4.5 INFO/END is checked against the maximum computed reference end from REF, symbolic SVLEN, and sample-specific LEN. Positions covered by a preceding sample block must have GT='.' and no populated FORMAT fields other than LAA. If LAA is present when a block starts, it must include the <*> allele.
- VCFv4.5 reserved base-modification FORMAT fields (M, DPM, and ADM ChEBI-ID forms and the specification aliases) are recognized even when explicit FORMAT metadata declarations are absent. Their Number=M cardinality is validated from sample GT and concrete REF/ALT allele sequences, including strand complements, U/T equivalence, N modifications, unphased-allele aggregation, missing alleles, and symbolic alleles. Fraction values are constrained to [0, 1] and depth values to non-negative integers.
- Base-modification values remain intact in the immutable uploaded source VCF. Because the pinned BCFtools 1.24 multiallelic splitter does not project Number=M values to each emitted ALT child, SIRALOOM removes Number=M fields from the derived normalized SNV/INDEL artifact and records their names and source-only policy in normalization provenance. This prevents downstream consumers from interpreting source-genotype values against a different per-ALT GT. These fields are not used as rare-disease pathogenicity evidence.
- Arbitrary declared FORMAT values are retained in sample-call provenance instead of being reduced to a small fixed whitelist.
- The pinned BCFtools version is 1.24 and HTSlib version is 1.24 so the independent parser and transformation toolchain can handle VCFv4.4/v4.5 cardinality fields. VCF intake attests both installed versions before parsing; either mismatch is an operational/retryable failure, never an input-invalid result.
- Validation metadata distinguishes source VCF data rows (`source_record_count`), ALT entries (`alternate_allele_count`), and parsed per-ALT records (`record_count` / `parsed_variant_record_count`). The existing `record_count` API meaning is preserved: reference-only and telomere-only rows are not counted as parsed variant records.

Recognition of a version is not a claim that every optional extension or every caller-specific tag has clinical semantics in SIRALOOM. Unknown INFO/FORMAT tags are preserved as source data; a downstream stage must not infer unsupported semantics from them.

## Automated software conformance coverage

The GitHub CI suite exercises the supported version range against the upload validator, record router, and pinned BCFtools normalization toolchain:

| Automated check | Version coverage | Verification boundary |
|---|---|---|
| Strict parser and upload-intake acceptance | VCFv4.0–VCFv4.5 | Minimal conformant records, version identity, HTSlib parsing, and build detection |
| Multisample sequence routing | VCFv4.0–VCFv4.5 | Sample-column order and per-sample GT values remain unchanged during routing |
| gVCF routing | VCFv4.0–VCFv4.5 | Reference blocks, provably unobserved wildcard alleles, unresolved wildcard calls, and exclusive record reconciliation |
| Reference-aware normalization | VCFv4.0–VCFv4.5 | Pinned BCFtools 1.24 normalization, normalized record content, and CSI index creation |
| Uploaded index concordance | VCFv4.3 fixture | Both TBI and CSI; per-contig counts and indexed-query record-line SHA-256 match the sequential BGZF stream |
| Version-specific genotype syntax | VCFv4.3–VCFv4.5 | VCFv4.4/4.5 leading GT phasing separators are accepted; VCFv4.3 rejects that syntax |
| VCFv4.5 local-allele fields | VCFv4.5 | LA/LR/LG/P cardinality and LAA constraints |
| VCFv4.5 reference blocks | VCFv4.5 | Implicit/declared FORMAT/LEN, sample-specific intervals, legacy END fallback, END/SVLEN span consistency, overlap semantics, and CSI boundary query |
| VCFv4.5 base modifications | VCFv4.5 | Reserved implicit fields, Number=M cardinality, field types, fraction/depth ranges, and source-only normalization policy |

These are deterministic software conformance fixtures, not a claim that every optional feature emitted by every caller has been qualified. Laboratory release still requires the caller-specific positive/negative corpus, representative WES/WGS data, known-answer reference and indel checks, and the operational/reproducibility checks listed below.


## Input types and routing

| Input | Intake outcome | Clinical interpretation behavior |
|---|---|---|
| Single-sample VCF with explicit specimen-to-sample mapping | Validated sample-level artifact | Eligible for the configured workflow after reference and record checks |
| Multisample VCF | Validated if structurally conformant and the selected sample is explicitly mapped to the specimen | The workflow selects only the mapped sample; parsing a multisample VCF without a sample selection raises an error |
| Sites-only VCF (eight fixed columns, no sample columns) | Accepted as VALID_SITE_ONLY | Site-level artifact only; cannot create a patient-specific genotype interpretation or clinical report |
| VCF with FORMAT but no sample columns | Rejected as malformed | Correct the header; sites-only files must use only the eight fixed columns |
| Multiallelic small-variant records | Preserved and routed through configured splitting/normalization | Source ALT index mapping must remain traceable through splitting |
| Mitochondrial-contig variants (`M`, `MT`, `chrM`, `chrMT`, human `NC_012920.*`) | Preserved and routed to a mitochondrial artifact | Excluded from nuclear SNV/INDEL normalization; the dedicated mitochondrial pipeline remains pending |
| Explicit CNV records (`SVTYPE=CNV`, `<CNV>`, or copy-number genotype fields on symbolic DEL/DUP records) | Preserved and routed to a CNV artifact | Not silently treated as ordinary structural SVs or SNV/INDELs; the dedicated CNV pipeline remains pending |
| Repeat-expansion records (ExpansionHunter `SVTYPE=STR`/`<STRn>`/RU+REPID; TRGT `TRID`+`MOTIFS`) | Preserved and routed to a repeat-expansion artifact | Not silently treated as ordinary sequence variants or generic SVs; the dedicated repeat-expansion pipeline remains pending |
| Other symbolic structural variants/breakends | Preserved and routed to the structural/SV review artifact | Not silently treated as SNV/INDEL; the dedicated SV pipeline remains pending |
| GVCF reference blocks or unresolved wildcard alleles | Preserved and routed to a dedicated/review artifact | Not treated as ordinary small-variant calls; reference confidence/joint genotyping is a separate workflow |
| Reference-only rows (ALT=.) and telomere sentinels | Preserved and counted | Not turned into candidate variants or a negative clinical result |
| Unsupported major version, malformed header/record, or conflicting build declarations | Rejected with an explicit validation error | No downstream analysis dispatch |

Repeat-expansion routing is intentionally signature-based rather than inferred from long alleles alone. The implementation recognizes ExpansionHunter-style `SVTYPE=STR`, `<STRn>`, `RU`/`REPID` and repeat-copy fields, and TRGT-style `TRID`+`MOTIFS`. CNV routing uses explicit `SVTYPE=CNV`, `<CNV>`, or copy-number fields accompanying symbolic DEL/DUP alleles. Other symbolic SVs and breakends remain in the SV route. These are routing rules only: they do not constitute repeat/CNV/SV/mitochondrial clinical interpretation. In the first SIRALOOM product, the CNV, SV, mitochondrial, and repeat-expansion artifact types are unconditional reportability blockers based on their artifact type, even if review metadata is absent or altered. The existing `REQUIRES_SPECIALIZED_REVIEW` metadata remains an additional traceability signal, not the source of the hard block. A reviewer cannot clear this blocker by manually classifying the artifact, overriding the review status, or signing out the nuclear SNV/INDEL subset. The blocker is released only by the separately developed second product after its specialized pipeline, resource governance, validation evidence, and reportability contract have been qualified and explicitly integrated. Until then, SIRALOOM may preserve and route these records for traceability, but the analysis is not clinically reportable. This prevents a partial nuclear SNV/INDEL result from being signed out as though all submitted variant classes had been analyzed.

Reference formats used to define these routing signatures:
- [VCF v4.5 specification](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex)
- [ExpansionHunter](https://github.com/Illumina/ExpansionHunter)
- [TRGT](https://github.com/PacificBiosciences/trgt)

## Product boundary: specialized variant classes

SIRALOOM is being delivered as two distinct products with a controlled integration boundary.

**First product — SIRALOOM rare-disease SNV/INDEL interpretation:** the current product accepts and validates supported VCF inputs, preserves the original source, identifies specialized record classes, and routes those records into immutable, traceable specialized artifacts. It does not perform clinical interpretation for CNV, structural SV, mitochondrial variants, or repeat expansions.

**Second product — specialized variant analysis:** CNV, SV, mitochondrial, and repeat-expansion interpretation will be developed as a separate product with its own qualified pipelines, approved resources, analytical validation, workflow controls, review experience, and reportability contract. These pipelines are not part of the current product scope and must not be implied to exist.

Until that second product is qualified and integrated, any analysis containing one or more of these specialized artifact classes is **reportability blocked**. The block is independent of whether the nuclear SNV/INDEL subset completed successfully and cannot be cleared through manual reportability disposition or by ignoring the specialized artifacts. The source and routed artifacts remain accessible for traceability and future second-product processing.

## Multiallelic genotype and source-lineage contract

The normalization contract preserves two distinct genotype views:

- `SIRALOOM_SOURCE_GT` stores the sample GT on the routed sequence input immediately before per-ALT normalization. This is after the router's explicit removal of fully unobserved wildcard alleles; it is not a replacement for the immutable uploaded VCF.
- `SIRALOOM_SOURCE_ALT_COUNT` stores the ALT count on that same routed input.
- `SIRALOOM_ORIG` maps each normalized child to its routed source record and routed ALT index.
- `SIRALOOM_SOURCE` retains the router's mapping from routed ALT indexes back to the raw uploaded record, including the raw record index, SHA-256, raw ALT count, and original ALT-index list.

The parser exposes the routed source GT as the authoritative sample genotype and retains the normalized biallelic GT separately. For each normalized ALT it records reference dosage, selected-ALT dosage, other-ALT dosage, missing-allele count, source/routed ALT indexes, original raw ALT index, source-record identity, and a projection status.

**Non-selected ALT alleles are never rewritten as reference alleles.** BCFtools normalization uses the missing-other-ALT policy. A per-ALT candidate is excluded as a known non-carrier only when selected-ALT dosage is zero and no allele is missing. Partial calls, no-calls, invalid mappings, and source/normalized ploidy mismatches remain unresolved; they are not converted into reference-negative evidence.

The normalization artifact contract is versioned independently from the uploaded source artifact. The current source-genotype provenance implementation, including the VCFv4.5 Number=M source-only policy, uses normalization version `6.0`, normalized-artifact identity `v6`, and partition metadata schema `4`. Historical artifacts are not silently upgraded or interpreted as if they contained this provenance contract.

This contract improves genotype and source-record traceability; it does not itself qualify every caller-specific FORMAT field, every VCF 4.0–4.5 optional feature, or downstream inheritance/segregation logic. Those remain separate feature-level and end-to-end laboratory qualification requirements.

## Interrupted upload recovery and idempotency

The artifact upload endpoint accepts an optional `Idempotency-Key` header. Clients performing uploads that must survive transport or API-process interruption should generate one high-entropy key per logical upload and reuse that exact key for every retry. The key is scoped to the authenticated organization and case; the raw key is never persisted.

Before artifact bytes are published, SIRALOOM commits an upload-intent reservation containing the key digest, a fingerprint of the complete upload request, and one stable artifact UUID. The fingerprint binds the file SHA-256 and byte count to filename, artifact type, media type, genome build, specimen, and paired-index identity. Reusing a key with different content or metadata returns HTTP 409. A matching retry reuses the reserved artifact identity and can safely adopt byte-identical local or cloud objects left by a process interruption. After the artifact row, case-state transition, audit event, and intent state commit together, a retry returns the original artifact with HTTP 200 and does not create a duplicate audit or artifact row.

The intent is tenant- and case-scoped and is committed before storage writes. An interrupted reservation remains recoverable by retrying the same request and key. A reservation marked `RECOVERY_REQUIRED`, or a committed reservation whose artifact row is missing, is not silently recreated; it requires administrator reconciliation. Uploads without the header retain the legacy non-idempotent request behavior. The idempotency intent is a transport/durability mechanism, not a substitute for VCF validation, reference verification, assay qualification, or clinical review.

### Browser upload retry identity

The workspace browser client persists one opaque idempotency key per logical upload in tab-scoped `sessionStorage`. The storage key is a SHA-256 digest of the file's browser metadata and upload scope; the stored value is the random idempotency key. Raw filenames, case identifiers, specimen identifiers, and file contents are not written to browser storage. This survives a page reload in the same tab and allows the user to reselect the same file and safely retry with the original key. A successful HTTP response removes the completed attempt. A failed or interrupted request leaves the key available for retry.

The browser metadata digest is only a client-side lookup key, not proof of file identity. The server recomputes SHA-256 over the actual uploaded bytes and binds it to the full request fingerprint. If two different files happen to share the same browser metadata, the server returns HTTP 409 rather than accepting different bytes under the existing key. The client fails closed if secure browser cryptography or session storage is unavailable; it does not silently fall back to a fresh key. Tab-scoped storage is intentionally cleared when the browser tab session ends; cross-device or post-tab-close recovery requires a future server-side upload-session discovery workflow and is not claimed here.

## Validation layers

1. **Accession and transport:** filename/type, non-empty upload, configured byte limit, storage-capacity preflight, SHA-256, original artifact preservation.
2. **VCF syntax:** required fileformat first, header/column shape, header definitions, INFO/FORMAT cardinality/type where declared, record fields, genotype allele indices, ordering, duplicate IDs, symbolic/breakend/GVCF structures, compressed-stream readability.
3. **Independent parser check:** pinned BCFtools/HTSlib must parse the input; tool unavailability is retryable and must not be represented as a malformed-file finding.
4. **Identity and build:** explicit GRCh37/GRCh38 selection; conflicting header declarations are rejected. Sample-bearing files require a specimen mapping to an exact sample name in the header. A multisample input is not interpreted as a single individual.
5. **Reference-aware worker validation:** before normalization, the selected reference package is resolved and REF alleles/contig compatibility are checked. Header declarations alone do not prove that the file was produced against the selected reference.
6. **Record routing and normalization:** supported sequence alleles proceed through reference-aware normalization; multiallelic records are split with provenance; unsupported record classes are retained and routed with explicit reason codes.
7. **Downstream evidence:** normalized variant/sample-call data feed annotation and interpretation. The source VCF remains the original evidence and must not be overwritten by normalized output.

## Laboratory release checks still required

The code-level changes above do not by themselves qualify SIRALOOM for a clinical laboratory. Before a lab enables a version/caller/build combination, validate and retain evidence for at least:

- Positive and negative conformance fixtures for every VCF version used by the lab, including version-specific fields actually emitted by its caller; VCFv4.5 Number=M fixtures must include methylation/base-modification cardinality and preservation checks.
- Multisample proband selection across normalization, genotype interpretation, inheritance/segregation, candidate generation, and report rendering; prove no other sample's genotype is used.
- Sites-only artifact behavior and explicit rejection from patient-level analysis.
- REF allele concordance against the exact pinned reference package, contig aliases/lengths, GRCh37/GRCh38 mismatch, and boundary/telomere records.
- Multiallelic split correctness, source ALT-index mapping, left-normalization/idempotence, and known-answer indel fixtures.
- Symbolic SV, breakend, spanning-deletion, and GVCF routing with record counts and review reasons reconciled to the original source.
- Representative caller-produced BGZF/TBI/CSI fixtures and large-file performance. The upload path now verifies the paired TBI/CSI index against the exact primary BGZF record stream using per-contig index statistics plus indexed-query record-line SHA-256 comparison with a sequential scan; lab qualification still requires representative caller-produced artifacts.
- Corrupt/truncated streams, decompression and parser timeouts, large WES/WGS files, storage pressure, worker crash/replay, and immutable provenance.
- Caller/reference/resource versions, acceptance thresholds, test corpus, intended use, and lab authorization recorded in the resource/assay qualification process.

### Automated normalization worker-loss regression

The PostgreSQL integration suite includes a real Celery prefork-process failure test for the normalization boundary. It runs the pinned BCFtools 1.24 normalization command against a left-normalizable indel, commits the resulting NORMALIZED_VCF artifact and a normalize workflow checkpoint, then terminates the executing prefork child with an abrupt process exit. The broker must redeliver the late-acknowledged task to a replacement child. The production analysis-task wrapper must reacquire its PostgreSQL execution fence and recover the interrupted workflow step before the test workflow resumes normalization.

The replay runs BCFtools again, verifies byte-identical normalized output, and calls the production deterministic-artifact persistence path. The test asserts one artifact identity/row, matching SHA-256 and stored bytes, a recovered-and-completed normalization step, and one worker-recovery audit event. This is process-level fault-injection evidence for the normalization artifact boundary; it does not replace full assay/caller qualification, GIAB benchmarking, distributed object-store fault testing, or laboratory validation.


## Scientific safety rule

Never convert “valid VCF syntax” into “analytically valid assay,” “variant absent,” “negative result,” or “clinically reportable.” Those are separate decisions requiring reference validation, genotype/call quality, assay QC, evidence assessment, human review, and lab-controlled sign-out.

