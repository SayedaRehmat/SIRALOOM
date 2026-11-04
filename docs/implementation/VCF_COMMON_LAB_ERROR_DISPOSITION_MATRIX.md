# VCF intake common laboratory errors and disposition policy

**Purpose:** define deterministic SIRALOOM handling for frequent VCF submission
failures and interoperability problems. This is an engineering disposition
baseline; final laboratory SOPs and acceptance limits remain organization-controlled.

## Core handling principles

1. Preserve uploaded bytes and source SHA-256 before parsing or transformation.
2. Never repair the original file in place.
3. Do not infer assembly from chromosome names or filename.
4. Do not silently strip chr, rename contigs, rewrite headers, fill missing genotypes,
   or change sample IDs.
5. Distinguish invalid input, reference incompatibility, unsupported scope,
   review-required conditions and transient infrastructure failures.
6. Every disposition records a stable error code, line/record context, stage,
   retryability, operator action and next permitted workflow stage.
7. Repeating unchanged deterministic-invalid input is not a recovery strategy.

## Disposition matrix

| Error family | Typical observation | SIRALOOM disposition | Automatic action | Laboratory/operator action | Next permitted step |
|---|---|---|---|---|---|
| Unsupported/malformed VCF version | Missing, duplicated, malformed or future fileformat | REJECTED_INVALID_FORMAT or BLOCKED_UNSUPPORTED_VERSION | No fallback parser | Export supported version or request controlled qualification | Re-intake after approval |
| Header syntax / missing definitions | Malformed INFO/FORMAT/FILTER declaration, duplicate IDs, invalid quoting | REJECTED_HEADER_INVALID | Do not synthesize definitions | Correct producer header or provide approved, traceable correction | Revalidate derivative |
| Undefined INFO/FORMAT tag | Record tag has no applicable declaration | Review or reject according to version/profile policy; never guess type/cardinality | None | Obtain authoritative producer header or approved declaration | Revalidate after traceability |
| Column/sample mismatch | Missing FORMAT, wrong sample count, duplicate sample names | REJECTED_RECORD_STRUCTURE | None | Re-export with consistent sample manifest/header | Re-intake |
| Sample identity mismatch | VCF IDs disagree with case/pedigree manifest | BLOCKED_SAMPLE_IDENTITY | No automatic renaming/reassignment | Resolve accession identity and audit correction | Resume after approval |
| Malformed GT / invalid allele index | GT references undeclared ALT or invalid separators/ploidy | REJECTED_GENOTYPE_INVALID | Never replace with 0/0 | Correct caller export | Revalidate |
| Number=A/R/G mismatch | Array length disagrees with ALT count or sample ploidy | REJECTED_FIELD_CARDINALITY | Do not pad/truncate arrays | Correct producer output | Revalidate |
| Missing values | Dot in GT/INFO/FORMAT | Preserve as missing; do not interpret as reference or zero | Preserve source missingness | Review only when downstream required field is missing | Continue only if field is not mandatory |
| Multiallelic representation | Multiple ALTs and genotype likelihood arrays | Validate allele indexes/cardinality; split only in controlled stage with source-child reconciliation | No lossy split | Review unresolved ploidy/cardinality | Proceed after reconciliation |
| REF mismatch | REF disagrees with selected FASTA | BLOCKED_REFERENCE_MISMATCH | No liftover, REF swap or reference substitution | Confirm assembly/reference package and regenerate from correct reference | Re-intake |
| Assembly ambiguity | Missing/conflicting assembly metadata | BLOCKED_ASSEMBLY_UNRESOLVED | No assembly inference | Confirm GRCh37/GRCh38 from assay/caller provenance | Resume after explicit selection |
| Contig naming mismatch | chr1 versus 1, alternate contigs or decoys | REVIEW unless exact approved alias map exists | No global string replacement | Use versioned assembly-specific alias map | Resume with recorded mapping |
| Contig length/MD5 mismatch | Header conflicts with reference | BLOCKED_REFERENCE_IDENTITY | None | Reconcile exact reference package | Re-intake |
| Unsorted records | Decreasing POS or noncontiguous contig blocks | Reject or controlled sort derivative with accounting | Never mutate source | Re-export sorted or invoke approved deterministic sort | Continue after validation |
| Duplicate IDs/records | Duplicate ID or repeated calls | Apply exact VCF ID rules; do not heuristically deduplicate | No silent record removal | Review producer behavior and approved policy | Continue only with traceable resolution |
| Invalid REF/ALT syntax | Empty allele, invalid base, malformed symbolic/BND | REJECTED_ALLELE_SYNTAX | None | Correct export or route supported specialized representation | Revalidate |
| Symbolic SV / breakend | DEL/DUP/BND, missing END/SVLEN or invalid MATEID | Validate syntax; classify outside SNV/INDEL trial scope | Preserve and route to specialized review; never feed small-variant normalizer | Use qualified SV workflow or exclude from trial sign-out | Other balanced SNV/INDEL records may proceed |
| gVCF reference blocks | NON_REF, <*> and END/LEN blocks | Identify explicit producer profile; block if unqualified | Never convert reference block to variant or infer 0/0 | Supply qualified caller profile or variant-only VCF | Resume under qualified policy |
| CNV / tandem repeat / MT / repeat expansion | VCFv4.4/4.5 class outside trial scope | REQUIRES_SPECIALIZED_REVIEW | Preserve; no small-variant normalization | Submit future qualified pipeline or exclude | Other balanced SNV/INDEL records may proceed |
| Compression mismatch | Extension disagrees with gzip/BGZF/plain content | REJECTED_COMPRESSION_MISMATCH or explicit sequential-only profile | No extension-only reinterpretation | Re-export supported format | Re-intake |
| Truncated/corrupt gzip/BGZF | CRC, block, EOF or transfer failure | REJECTED_COMPRESSED_STREAM_INVALID | Do not parse partial prefix | Re-transfer and verify source digest | Re-intake |
| Stale/corrupt TBI/CSI | Index/file mismatch or query differs from sequential scan | REJECTED_INDEX_INVALID | Preserve original index; rebuild only as approved derivative | Regenerate with pinned tool and record digest | Continue after query concordance |
| Empty/partial upload | Interrupted transfer or checksum mismatch | UPLOAD_INCOMPLETE | Retry transfer only; no partial parsing | Re-upload and verify digest | Start intake after immutable receipt |
| Unsupported VCFv4.5 feature | Local alleles, base modifications or sample-specific blocks | Explicit feature status; block affected processing | No silent downgrade or field dropping | Supply supported representation or wait for qualification | Proceed only for explicitly supported subset |
| Normalizer/tool mismatch | Wrong version/hash or unapproved resource | BLOCKED_RESOURCE_NOT_QUALIFIED | No latest-version fallback | Select exact approved resource | Resume after qualification |
| Worker/process failure | Timeout, killed worker, temporary queue/storage issue | Stable retryable operational code | Idempotent retry only where stage contract permits | Inspect logs and retry after recovery | Resume from verified checkpoint |
| Partial output/publication failure | VCF without paired index/provenance | Quarantine unpublished output | Atomic cleanup/recovery; no partial artifact exposure | Recover/replay with same immutable input and pinned resource | Continue after paired artifact validation |

## Retry policy

| Class | Examples | Retry policy |
|---|---|---|
| Deterministic input-invalid | malformed header, invalid GT, bad cardinality, REF mismatch | Do not retry unchanged input; require corrected input |
| Unsupported capability | unqualified version/feature, CNV/SV/MT/repeat | No fallback; block/route until qualified |
| Reference/resource mismatch | wrong assembly, stale index, unapproved normalizer | Correct explicit selection, rerun affected stage |
| Transient infrastructure | network timeout, temporary object-store/queue outage | Bounded retry with idempotency key and preserved provenance |
| Worker interruption | worker killed after durable checkpoint | Safe replay only after stage-specific recovery tests |
| Human review required | sample identity discrepancy, contig alias mapping | No automatic progression until authorized resolution |

## Required failure evidence

- Immutable source identity and SHA-256.
- Declared VCF version and detected compression.
- Assembly/reference selection and package digest.
- Stable error code, message, line/record context and failing stage.
- Deterministic, unsupported, review-required or retryable classification.
- Corrected derivative parent ID, transformation, tool/version and output digest.
- Record accounting for mixed supported/unsupported inputs.
- Operator/approver identity and decision where required.

This policy does not authorize silent header repair, sample renaming, contig
rewriting, liftover, genotype imputation, deduplication or variant-class conversion.
