# SIRALOOM VCF Intake Contract and Laboratory Verification Matrix

## Purpose and boundary

SIRALOOM consumes variant call data produced by an upstream assay/caller. It does not perform FASTQ quality control, alignment, variant calling, joint genotyping, or assay validation. A syntactically valid VCF is not proof that the upstream assay or caller is analytically valid. Laboratories must qualify the complete intended process, including upstream assay, calling pipeline, reference build, file transfer, SIRALOOM normalization, annotation, interpretation, review, and report generation.

The immutable uploaded artifact and its SHA-256 remain the source record. Derived normalized artifacts must retain the source-record/allele mapping and tool/resource provenance.

## Version policy

The validator recognizes VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, and VCFv4.5. VCFv4.5 is the current version in the upstream HTS specifications. There is no VCFv5.0 specification in the supported HTS specifications set; unknown/future major versions are rejected rather than guessed.

The parser applies version-specific rules where implemented:
- VCFv4.4 and VCFv4.5 leading genotype phasing separators are parsed without inflating ploidy.
- VCFv4.5 FORMAT cardinalities LA, LR, LG, P, and M are recognized. Local-allele fields require LAA in the prescribed position and validate distinct, in-range 1-based ALT indices.
- VCFv4.5 reserved base-modification FORMAT fields (M, DPM, and ADM ChEBI-ID forms and the specification aliases) are recognized even when explicit FORMAT metadata declarations are absent. Their Number=M cardinality is validated from sample GT and concrete REF/ALT allele sequences, including strand complements, U/T equivalence, N modifications, unphased-allele aggregation, missing alleles, and symbolic alleles. Fraction values are constrained to [0, 1] and depth values to non-negative integers. Raw values are retained; they are not interpreted as rare-disease pathogenicity evidence or used by the clinical prioritization engine.
- Arbitrary declared FORMAT values are retained in sample-call provenance instead of being reduced to a small fixed whitelist.
- The pinned BCFtools/HTSlib version is 1.24 so the independent parser and transformation toolchain can handle VCFv4.4/v4.5 cardinality fields.

Recognition of a version is not a claim that every optional extension or every caller-specific tag has clinical semantics in SIRALOOM. Unknown INFO/FORMAT tags are preserved as source data; a downstream stage must not infer unsupported semantics from them.

## Input types and routing

| Input | Intake outcome | Clinical interpretation behavior |
|---|---|---|
| Single-sample VCF with explicit specimen-to-sample mapping | Validated sample-level artifact | Eligible for the configured workflow after reference and record checks |
| Multisample VCF | Validated if structurally conformant and the selected sample is explicitly mapped to the specimen | The workflow selects only the mapped sample; parsing a multisample VCF without a sample selection raises an error |
| Sites-only VCF (eight fixed columns, no sample columns) | Accepted as VALID_SITE_ONLY | Site-level artifact only; cannot create a patient-specific genotype interpretation or clinical report |
| VCF with FORMAT but no sample columns | Rejected as malformed | Correct the header; sites-only files must use only the eight fixed columns |
| Multiallelic small-variant records | Preserved and routed through configured splitting/normalization | Source ALT index mapping must remain traceable through splitting |
| Symbolic structural variants/breakends | Preserved and routed to the structural/review route | Not silently treated as SNV/INDEL |
| GVCF reference blocks or unresolved wildcard alleles | Preserved and routed to a dedicated/review artifact | Not treated as ordinary small-variant calls; reference confidence/joint genotyping is a separate workflow |
| Reference-only rows (ALT=.) and telomere sentinels | Preserved and counted | Not turned into candidate variants or a negative clinical result |
| Unsupported major version, malformed header/record, or conflicting build declarations | Rejected with an explicit validation error | No downstream analysis dispatch |

## Multiallelic genotype and source-lineage contract

The normalization contract preserves two distinct genotype views:

- `SIRALOOM_SOURCE_GT` stores the sample GT on the routed sequence input immediately before per-ALT normalization. This is after the router's explicit removal of fully unobserved wildcard alleles; it is not a replacement for the immutable uploaded VCF.
- `SIRALOOM_SOURCE_ALT_COUNT` stores the ALT count on that same routed input.
- `SIRALOOM_ORIG` maps each normalized child to its routed source record and routed ALT index.
- `SIRALOOM_SOURCE` retains the router's mapping from routed ALT indexes back to the raw uploaded record, including the raw record index, SHA-256, raw ALT count, and original ALT-index list.

The parser exposes the routed source GT as the authoritative sample genotype and retains the normalized biallelic GT separately. For each normalized ALT it records reference dosage, selected-ALT dosage, other-ALT dosage, missing-allele count, source/routed ALT indexes, original raw ALT index, source-record identity, and a projection status.

**Non-selected ALT alleles are never rewritten as reference alleles.** BCFtools normalization uses the missing-other-ALT policy. A per-ALT candidate is excluded as a known non-carrier only when selected-ALT dosage is zero and no allele is missing. Partial calls, no-calls, invalid mappings, and source/normalized ploidy mismatches remain unresolved; they are not converted into reference-negative evidence.

The normalization artifact contract is versioned independently from the uploaded source artifact. The current source-genotype provenance implementation uses normalization version `5.0`, normalized-artifact identity `v5`, and partition metadata schema `4`. Historical artifacts are not silently upgraded or interpreted as if they contained this provenance contract.

This contract improves genotype and source-record traceability; it does not itself qualify every caller-specific FORMAT field, every VCF 4.0–4.5 optional feature, or downstream inheritance/segregation logic. Those remain separate feature-level and end-to-end laboratory qualification requirements.

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
- BGZF validity and index concordance against the exact uploaded VCF (a valid index signature alone is not proof that the index belongs to the file).
- Corrupt/truncated streams, decompression and parser timeouts, large WES/WGS files, storage pressure, worker crash/replay, and immutable provenance.
- Caller/reference/resource versions, acceptance thresholds, test corpus, intended use, and lab authorization recorded in the resource/assay qualification process.

## Scientific safety rule

Never convert “valid VCF syntax” into “analytically valid assay,” “variant absent,” “negative result,” or “clinically reportable.” Those are separate decisions requiring reference validation, genotype/call quality, assay QC, evidence assessment, human review, and lab-controlled sign-out.
