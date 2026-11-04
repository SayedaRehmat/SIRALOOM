# VCFv4.0 historical source and atomic clause catalog

Status: PARTIAL — targeted vectors are not full conformance.

## Source authority

1. Core format: https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
2. Historical 1000 Genomes SV conventions: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/
3. Stewardship notice: https://www.internationalgenome.org/wiki/Analysis/variant-call-format/

The source pages were retrieved and inspected as rendered web documents on 2026-11-04. The web retrieval interface exposed line-addressable rendered text, not the original HTTP response bytes. Consequently, this document does not claim to be a byte-for-byte source archive and does not invent source SHA-256 values. Raw response capture, exact-byte hashing, and immutable archival remain open. Source line locators below refer to the rendered core page (245 lines) and SV page (130 lines).

## Atomic clause catalog — core VCFv4.0

The source uses mixed modal force. "MUST" below is used only where the source explicitly says "always", "must", or "required". "SHOULD" and "RECOMMENDED" are not upgraded to MUST. Descriptive statements are classified separately.

| Clause ID | Source locator | Atomic requirement / rule | Force | Implementation target | Regression evidence |
|---|---|---|---|---|---|
| V40-CORE-001 | Core L40-L41 | The fileformat metadata declaration identifies VCFv4.0. | MUST | read_vcf_fileformat; validate_vcf_strict | Existing legacy parser smoke |
| V40-CORE-002 | Core L43-L50 | INFO declarations, when present, contain ID, Number, Type, and quoted Description. | MUST when declaration present | _parse_field_definition | Existing header-definition tests; VCFv4.0-specific vector pending |
| V40-CORE-003 | Core L48-L50 | INFO Type values include Integer, Float, Flag, Character, String. | DEFINITION | _parse_field_definition; _validate_declared_value | VCFv4.0-specific vector pending |
| V40-CORE-004 | Core L49-L50 | INFO Flag has Number=0 and carries no value. | MUST | _parse_field_definition; _validate_info | VCFv4.0-specific vector pending |
| V40-CORE-005 | Core L51-L58 | FILTER and FORMAT declarations use the documented structured declaration forms. | MUST when present | _parse_field_definition | Existing header-definition tests |
| V40-CORE-006 | Core L61-L72 | Header has the eight fixed columns; genotype columns, when present, follow with FORMAT then sample identifiers. | MUST | validate_vcf_strict | Existing header tests |
| V40-CORE-007 | Core L72 | Header fields are tab-delimited. | MUST | validate_vcf_strict | Existing header tests |
| V40-CORE-008 | Core L77-L78 | Data records contain eight fixed fields and are tab-delimited. | MUST | validate_vcf_strict; _validate_record | Existing malformed-record tests |
| V40-CORE-009 | Core L77 | Missing fixed-field values use a dot. | MUST | _validate_record | Existing missing-value tests |
| V40-CORE-010 | Core L78 | CHROM is a required reference-sequence identifier. | MUST | _validate_record | Existing contig tests |
| V40-CORE-011 | Core L78 | Records for a CHROM form one contiguous block. | MUST | validate_vcf_strict | Existing contig-order tests |
| V40-CORE-012 | Core L79 | POS is a required, one-based coordinate and records are numerically increasing within a CHROM. | MUST | _validate_record; validate_vcf_strict | Existing position/order tests |
| V40-CORE-013 | Core L80 | Non-missing record IDs are unique across data records. | MUST | _validate_record; validate_vcf_strict | Existing duplicate-ID tests |
| V40-CORE-014 | Core L81 | REF contains only A,C,G,T,N and is uppercase. | MUST | _validate_record | Existing REF tests |
| V40-CORE-015 | Core L81 | REF may contain multiple bases; POS identifies its first base. | DEFINITION | _validate_record | Existing multibase REF tests |
| V40-CORE-016 | Core L81 | Indel REF representation includes the preceding reference base and POS points to it. | SHOULD in source wording | _validate_simple_indel_padding | Boundary qualification required |
| V40-CORE-017 | Core L82 | ALT is a comma-separated list of called non-reference alleles; absent alternatives use dot. | MUST | _validate_record | Existing ALT tests |
| V40-CORE-018 | Core L82 | Sequence ALT uses uppercase A,C,G,T,N. | MUST | _validate_record | Existing ALT tests |
| V40-CORE-019 | Core L82 | Symbolic ALT uses an angle-bracketed identifier. | DEFINITION | _validate_structural_alt | Existing symbolic ALT tests |
| V40-CORE-020 | Core L83 | QUAL is numeric and may be floating point. | MUST / DEFINITION | _validate_record | Existing QUAL tests |
| V40-CORE-021 | Core L84-L85 | FILTER is PASS, dot when filters were not applied, or a semicolon-separated list of failing filter IDs; literal 0 is reserved. | MUST | _validate_record | Existing FILTER tests |
| V40-CORE-022 | Core L86-L105 | INFO consists of semicolon-separated keys with optional values; key-only flags are permitted. | DEFINITION | _validate_info | Existing INFO tests |
| V40-CORE-023 | Core L86-L103 | INFO keys are extensible; reserved keys are conventional and their exact field definitions belong in metadata. | DEFINITION / RECOMMENDATION | _validate_info; _validate_declared_value | Custom-field compatibility tests required |
| V40-CORE-024 | Core L108 | When genotypes exist, FORMAT defines field order and GT is first. | MUST | _validate_record | Existing FORMAT ordering tests |
| V40-CORE-025 | Core L111-L114 | GT allele indexes map 0 to REF and positive indexes to ALT order; slash is unphased and pipe is phased. | DEFINITION | _gt_allele_tokens; _validate_record | Existing genotype tests |
| V40-CORE-026 | Core L111-L112 | Haploid calls may contain one allele; missing allele calls use dot for each missing allele. | DEFINITION / MUST | _gt_allele_tokens; _validate_record | Haploid and missing GT tests required |
| V40-CORE-027 | Core L115-L119 | DP, FT, GL, GQ, HQ have the described conventional meanings and types. | DEFINITION | _validate_declared_value; _expected_cardinality | Field-specific VCFv4.0 vectors required |
| V40-CORE-028 | Core L120 | Missing genotype subfields use dot; trailing fields may be omitted except GT. | MUST / MAY | _validate_record | Missing/trailing FORMAT tests required |
| V40-CORE-029 | Core L122 | Additional genotype fields may be declared; software support is not guaranteed by the source. | MAY / NON-NORMATIVE SUPPORT NOTE | _parse_field_definition | Custom FORMAT interoperability test required |
| V40-CORE-030 | Core L125-L130 | A record represents alleles and, where present, sample genotypes as haplotypes over a locus. | DEFINITION | _validate_record; route_vcf_records | Multiallelic representation test required |
| V40-CORE-031 | Core L130-L181 | ALT haplotypes replace the REF haplotype over the record interval; multiple segregating alleles may be represented in one multiallelic record. | DEFINITION | _validate_record; route_vcf_records | Multiallelic fixture required |
| V40-CORE-032 | Core L142-L154 | SNP, insertion, and deletion examples illustrate the allele representation and padding convention. | EXAMPLE, NOT INDEPENDENT NORMATIVE CLAUSE | _validate_record | Examples must not be counted as extra MUST clauses |
| V40-CORE-033 | Core L181-L237 | Record class (SNP, indel, mixed, reference) is determined by allele properties; examples illustrate classification. | DESCRIPTIVE / EXAMPLE | classify_records | Classification tests required |

## Historical 1000 Genomes structural-variation conventions

These clauses are recorded separately because the source explicitly describes them as conventions and extensions adopted by the 1000 Genomes Project for VCFv4.0. They are not silently represented as universally normative base-format requirements.

| Clause ID | Source locator | Atomic rule | Force / authority | SIRALOOM disposition |
|---|---|---|---|---|
| V40-SV-001 | SV L7-L10 | Precisely known SV alleles use full REF/ALT sequences; imprecise events may use a single REF base and descriptive symbolic ALT. | 1000 Genomes convention | Parse/recognize; route unsupported SV to reportability block |
| V40-SV-002 | SV L9 | Imprecise variants carry the IMPRECISE INFO flag. | 1000 Genomes convention | Validate metadata when present; unsupported SV blocked |
| V40-SV-003 | SV L10 | POS is the one-based base before the event or best estimate; ambiguous placement uses leftmost possible position. | 1000 Genomes convention | Preserve coordinates; do not normalize as SNV/INDEL |
| V40-SV-004 | SV L63-L65 | assembly URL identifies the FASTA containing breakpoint assemblies referenced by BKPTID. | 1000 Genomes convention | Preserve provenance; external assembly resolution not in trial |
| V40-SV-005 | SV L68-L81 | ALT symbolic type is one of DEL, INS, DUP, INV, CNV; listed subtypes include DUP:TANDEM, DEL:ME, INS:ME. | 1000 Genomes convention | Recognize and route to unsupported-SV reportability block |
| V40-SV-006 | SV L84-L108 | SVLEN is per ALT allele; END describes event end; CIPOS/CIEND represent confidence intervals; HOMLEN/HOMSEQ and BKPTID carry breakpoint evidence. | 1000 Genomes convention | Preserve raw fields; full SV interpretation not in trial |
| V40-SV-007 | SV L110-L117 | MEINFO/METRANS and DGVID/DBVARID/DBRIPID identify mobile-element/transduction/database annotations. | 1000 Genomes convention | Preserve raw fields; no SV sign-out |
| V40-SV-008 | SV L120-L122 | CN and CNQ encode copy-number genotype and its quality for imprecise events. | 1000 Genomes convention | Parse only where safe; reportability-block SV/CNV |

## Source preservation and hash status

The two URLs above were inspected through the web retrieval interface on 2026-11-04. The retrieval interface returned rendered, line-addressable content, not the original HTTP response body. The repository must not label a hash of this Markdown transcription as the source-page SHA-256. The following remain required:

- Capture the raw HTTP response bytes for both URLs from a controlled acquisition environment.
- Record final URL, retrieval timestamp, status code, content type, ETag/Last-Modified where supplied, and byte length.
- Calculate SHA-256 over the exact response bytes.
- Commit immutable source snapshots and an acquisition manifest.
- Keep a new snapshot when the upstream page changes; never overwrite historical evidence.

## Traceability and qualification status

This catalog is a reviewed first-pass decomposition, not closure. Implementation symbols are candidate targets based on source inspection; they must be verified clause-by-clause against exact behavior and test nodes. Existing VCFv4.0 automated conformance was previously only one minimal parser smoke vector. The expanded executable vectors must be added to the versioned conformance manifest and run on this branch before any implementation/test status is promoted.

The 1000 Genomes SV extension is not part of SIRALOOM's supported trial variant classes. It must not cause otherwise valid VCFv4.0 SNV/small-INDEL records to be rejected. Recognized unsupported SV records must follow the existing unsupported-feature/reportability disposition path.

## Added executable regression vectors (2026-11-04)

The versioned runner manifest now contains nine VCFv4.0 cases: minimal fixed-field record, multiallelic genotype, indel representation, phased genotype, missing genotype, nonpositive POS rejection, invalid REF rejection, duplicate record-ID rejection, and out-of-range GT allele rejection. They are executed by the existing `execute_vcf_conformance_suite("VCFv4.0")` path and the parametrized pytest node:

`tests/test_vcf_conformance.py::test_packaged_vcf_conformance_executes_for_each_builtin_version[VCFv4.0]`

Candidate implementation mapping is `validate_vcf_strict`, `_validate_record`, `_validate_info`, `_parse_field_definition`, and `_gt_allele_tokens`. These mappings are not yet clause-by-clause proof: the current pytest harness reports aggregate suite execution, not individual clause IDs. The vectors have been committed but this session has not obtained a successful CI execution for the latest commit. Therefore their status is `ADDED_NOT_YET_EXECUTION_VERIFIED`, not `IMPLEMENTED_TESTED`.

The source capture gap remains: raw HTTP response bytes and source SHA-256 values have not been obtained. Do not treat the Git commit SHA of this catalog or its Markdown contents as a source-document hash.


## Clause-to-fixture traceability ledger

The executable pytest node is:

`tests/test_vcf_conformance.py::test_packaged_vcf_conformance_executes_for_each_builtin_version[VCFv4.0]`

The runner records each individual fixture ID and its `clause_ids` in the resulting JSON report. The focused integrity test additionally checks unique fixture IDs, non-empty clause links, and exact tab-delimited record/header column counts. The mappings below establish traceability links, not successful execution evidence.

| Clause ID | Fixture ID(s) | Status |
|---|---|---|
| V40-CORE-001 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-002 | — | NOT YET MAPPED |
| V40-CORE-003 | — | NOT YET MAPPED |
| V40-CORE-004 | — | NOT YET MAPPED |
| V40-CORE-005 | — | NOT YET MAPPED |
| V40-CORE-006 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_multiallelic_genotype_valid, legacy_missing_gt_valid, legacy_phased_gt_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-007 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_multiallelic_genotype_valid, legacy_missing_gt_valid, legacy_phased_gt_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-008 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_multiallelic_genotype_valid, legacy_indel_valid, legacy_missing_gt_valid, legacy_phased_gt_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-009 | — | NOT YET MAPPED |
| V40-CORE-010 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-011 | — | NOT YET MAPPED |
| V40-CORE-012 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_invalid_pos_rejected | FIXTURE_LINKED — execution pending |
| V40-CORE-013 | legacy_duplicate_id_rejected | FIXTURE_LINKED — execution pending |
| V40-CORE-014 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_indel_valid, legacy_invalid_ref_rejected | FIXTURE_LINKED — execution pending |
| V40-CORE-015 | legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-016 | legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-017 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid, legacy_multiallelic_genotype_valid, legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-018 | legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-019 | — | NOT YET MAPPED |
| V40-CORE-020 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-021 | legacy_minimal_snp_parser_smoke, legacy_minimal_snp_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-022 | — | NOT YET MAPPED |
| V40-CORE-023 | — | NOT YET MAPPED |
| V40-CORE-024 | legacy_missing_gt_valid, legacy_phased_gt_valid, legacy_out_of_range_gt_rejected | FIXTURE_LINKED — execution pending |
| V40-CORE-025 | legacy_multiallelic_genotype_valid, legacy_missing_gt_valid, legacy_phased_gt_valid, legacy_out_of_range_gt_rejected | FIXTURE_LINKED — execution pending |
| V40-CORE-026 | legacy_missing_gt_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-027 | — | NOT YET MAPPED |
| V40-CORE-028 | legacy_missing_gt_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-029 | — | NOT YET MAPPED |
| V40-CORE-030 | legacy_multiallelic_genotype_valid, legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-031 | legacy_multiallelic_genotype_valid, legacy_indel_valid | FIXTURE_LINKED — execution pending |
| V40-CORE-032 | — | NOT YET MAPPED |
| V40-CORE-033 | — | NOT YET MAPPED |

Mapped clauses: 20 / 33. The remaining clauses require dedicated fixtures or a documented, independently reviewed NOT_APPLICABLE disposition. All mapped fixtures remain execution-pending until the branch CI job produces a passing report.


## Independently produced historical VCFv4.0 cohort-file target

A real historical 1000 Genomes pilot cohort file has been identified for independent interoperability testing:

- Candidate file: `CEU.exon.2010_03.genotypes.vcf.gz`
- Historical location: `https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/pilot_data/release/2010_07/exon/snps/CEU.exon.2010_03.genotypes.vcf.gz`
- Producer/source: 1000 Genomes pilot project call set
- Assembly context: NCBI36 / GRCh36-era pilot data
- Published secondary-methods record describes this exact file and reports 55 chromosome-22 SNVs.
- The 1000 Genomes July 2010 release announcement states that pilot variant-call files were distributed as VCF 4.0.

This is a genuine historical cohort dataset, unlike the smaller PyVCF test fixture already pinned in `vcf_public_version_corpus.json`. It is a small exon/SNV file, so it supplements rather than replaces a larger pilot VCF containing short indels. The URL has been identified but the file has not yet been downloaded in this execution environment; byte length, SHA-256, exact header version, and parser/BCFtools outcomes remain pending. It must not be marked as tested until CI acquires the bytes, calculates hashes, checks the declared `##fileformat`, validates the complete file, and preserves the report and downloaded input as artifacts.

The download environment used for this session could not resolve external hosts, so no local copy or hash was fabricated. The branch CI runner has outbound acquisition steps for other public corpora; this historical file should be added there only with a captured and subsequently pinned byte size and digest.
