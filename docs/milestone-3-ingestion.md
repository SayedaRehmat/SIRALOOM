# SIRALOOM Variant — Milestone 3 Ingestion

Milestone 3 connects the secured SIRALOOM tenant/application foundation to the first real Variant intake path:

**Authenticated user → Organization → Case → Specimen → Variant Artifact → Validation → Ready for Analysis**

## Implemented

- Case intake wizard under `/app/cases` with five stages.
- Specimen registration tied to a Case.
- Explicit GRCh37/GRCh38 selection for primary VCF input.
- Primary inputs: `.vcf`, `.vcf.gz`, `.vcf.bgz`.
- Index inputs: `.tbi`, `.csi`; index files cannot be primary datasets.
- Matching index filename validation and basic format/magic validation.
- Actual VCF parsing/structural validation rather than extension-only checks.
- Server-derived SHA-256 and byte size.
- Immutable original artifact records with specimen and index-pair linkage.
- Validation state and diagnostic metadata.
- Tenant-derived Firebase Storage paths through the existing artifact abstraction.
- Case status moves to `READY_FOR_ANALYSIS` only after a valid primary VCF.
- Ingestion audit events.
- Cross-tenant access remains guarded by the Milestone 2 authorization layer.

## Validation policy

The ingestion validator requires `##fileformat` as the first VCF line and rejects UTF-8 BOMs, missing required columns, malformed records and malformed compressed input. Plain `.vcf` files are parsed as text. Compressed `.vcf.gz` and `.vcf.bgz` files must consist entirely of complete BGZF blocks; an ordinary gzip stream with a VCF filename is rejected. Intake verifies each BGZF block's declared size, deflate stream, CRC32 and uncompressed length and records the verified compression format, byte/block counts and terminal-empty-block observation in validation metadata. The BGZF verification is streaming and bounds decompressed output to the format's 64 KiB block limit. A stream with no terminal empty block remains readable but receives a truncation-risk warning; partial or corrupt blocks are rejected. A tabix/CSI index is optional for sequential intake; when an index is supplied for indexed operations, it must match the primary artifact and pass the existing BCFtools concordance check.

Recognized GRCh37/GRCh38 declarations in `##reference` and `##contig` `assembly` tags are recorded as detected context; contradictory recognized declarations invalidate the upload. These optional VCF header fields do not prove assembly identity, so SIRALOOM does not silently select the analysis build: the user must explicitly select GRCh37 or GRCh38, and a conflicting detected build invalidates the upload. The selected analysis reference package is checked separately against its declared identity, integrity hashes, contigs and every record's REF allele before normalization.

The compression contract follows the HTSlib [bgzip 1.25 manual](https://www.htslib.org/doc/bgzip.html) and its description of BGZF as a series of sub-64-KiB blocks that support indexed retrieval. The format definition is referenced by the [SAM/BAM specification (version 1.6, 2025-08-12)](https://samtools.github.io/hts-specs/SAMv1.pdf). Successful structural intake does not establish reference-allele compatibility or validate the upstream assay/callset.

## Storage architecture

The current production adapter writes objects under:

`organizations/{organizationId}/cases/{caseId}/artifacts/{artifactId}/{filename}`

The browser does not receive privileged Firebase credentials. Storage rules remain default-deny for direct browser object access; the authenticated FastAPI layer is the application authorization boundary.

## Intentionally not in Milestone 3

- FASTQ/BAM/CRAM processing
- alignment or variant calling
- large-scale asynchronous annotation execution
- clinical interpretation/sign-out changes

Those belong to later workflow milestones and reuse the existing scientific core.
