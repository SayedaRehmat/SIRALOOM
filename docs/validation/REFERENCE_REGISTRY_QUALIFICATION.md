# Reference registry and package qualification

## Purpose

SIRALOOM uses the existing governed `Resource` registry for reference releases. A
reference package is a single biological sequence collection for an assembly
release; caller-specific indexes are derived execution assets, not separate
biological references.

This contract applies to the GRCh38 germline SNV/small-indel intake foundation.
It does not itself qualify variant callers, alignments, assay performance, or
clinical interpretation.

## Identity model

Keep these identities separate:

1. **Assembly identity** — the assembly name and exact accession, for example
   RefSeq GRCh38.p14 `GCF_000001405.40`. The string `GRCh38` alone is not
   sufficient to identify the actual sequence set.
2. **Sequence collection identity** — the exact ordered contig set and sequence
   content supplied by the publisher, including the declared scope (for example
   primary-only, full analysis set, or decoy-augmented).
3. **Package release identity** — SIRALOOM's immutable version, package checksum,
   schema, artifact checksums, and qualification evidence.

A package must not silently substitute a different assembly accession, source
collection, decoy set, or contig scope under the same release identity.

## Reference package schemas and identity

- Schema `1.0`: legacy plain FASTA + FAI.
- Schema `1.1`: legacy BGZF FASTA + FAI + GZI.
- Schema `1.2`: qualified plain FASTA + FAI + SAM/GATK `.dict`, per-contig
  GA4GH Refget sequence identifiers, and a GA4GH Refget Sequence Collection
  v1.0 digest.
- Schema `1.3`: the same qualified identity contract as 1.2, with BGZF FASTA
  and the additional GZI index.

Schemas 1.0/1.1 remain readable for legacy resources but are not accepted by
the new reference registration contract. New registry releases must use 1.2 or
1.3. The SAM sequence dictionary is validated against exact contig order,
`SN`, `LN`, and `M5` values derived from the FASTA sequence content. A file
named `.dict` is not sufficient evidence by itself.

Per-contig Refget sequence identifiers use GA4GH Refget Sequences v2's
`SQ.` SHA-512/24-byte/base64url digest over normalized sequence characters.
The Seqcol attribute and top-level digests use the same truncated SHA-512 and
base64url encoding without the `SQ.` sequence prefix. The collection identifier
follows the GA4GH Refget Sequence Collections v1.0
minimal schema: collated `names`, `lengths`, and `sequences` arrays, with
`names` and `sequences` inherent in the top-level digest. The implementation
is checked against the GA4GH published ACGT sequence and sequence-collection
examples. The sequence collection digest identifies content and ordering; the
NCBI accession and SIRALOOM release remain separate provenance identities.

The package validator checks the complete FASTA sequence stream, IUPAC
alphabet, FAI identifier/order/length/offset/line geometry, dictionary M5
values, per-contig Refget identifiers, sequence-collection digest, artifact
checksums, and package identity checksum. For BGZF packages it additionally
checks BGZF block integrity, CRC, uncompressed lengths, and exact GZI block
boundaries.

## Registry lifecycle

Reference releases are registered as `CANDIDATE`, never directly as active.
The registry reuses the shared `resources`, `resource_stagings`, and
`resource_qualifications` models:

`CANDIDATE → QUALIFIED → ACTIVE → SUPERSEDED`

- Registration validates the manifest's structure and immutable identity.
- Staging binds the exact resource ID/version and FASTA artifact location.
  The lifecycle records independently observed SHA-256 and byte size; qualification
  re-reads the staged FASTA and compares actual, expected, and observed evidence.
- Qualification executes byte-level package validation and records a structured
  result with blockers and checks.
- Activation requires a persisted successful qualification for the exact
  qualification version.
- Failed qualification remains blocked; it does not activate or silently
  replace an existing active release.
- Superseded releases remain addressable for reproducibility.

The resource-level `checksum` is the package identity checksum. The staging
checksum is the processed FASTA artifact SHA-256. The publisher checksum
(e.g. NCBI MD5) applies to the exact downloaded source artifact, which may be
the compressed source FASTA rather than the decompressed processing FASTA.
The downloaded checksum-manifest file is itself SHA-256 pinned. These are
separate digest domains and must not be compared as if they were interchangeable.

## Qualification evidence

The qualification engine verifies:

- resource type, build, package schema, and candidate lifecycle state;
- assembly accession, reference source, and declared sequence scope;
- exact contig policy and ordered contig manifest;
- FASTA, FAI, required SAM/GATK dictionary, and optional GZI checksums;
- per-contig Refget sequence digests and the Refget Seqcol collection digest;
- publisher checksum-manifest SHA-256, exact artifact filename/URL binding, and publisher digest verification against downloaded source bytes;
- FASTA/FAI sequence and byte-layout consistency;
- BGZF/GZI block structure and offsets when applicable;
- package identity checksum;
- staging resource/version/location binding, expected and observed FASTA
  SHA-256 values, and expected and observed byte sizes;
- source contract and pinned samtools/BCFtools runtime versions;
- actual BCFtools `norm` execution against the same qualified FASTA, including a
  valid SNV, a left-normalized small insertion, and rejection of an intentionally
  incorrect REF allele. The report retains executable versions, reference
  SHA-256, exact commands, return codes, output records, and error evidence.
  Missing executables, version mismatches, or failed checks block qualification.

The qualification report includes a stable outcome, package checksum,
assembly accession, sequence scope, contig count, and artifact digests. A
package is not qualified merely because a path exists or a version string is
declared.


## NCBI GRCh38 acquisition candidate

The reproducible builder `scripts/reference/build_ncbi_grch38_reference_package.py`
targets the NCBI Genomes FTP GRCh38 full-plus-hs38d1 analysis set:

- Assembly lineage: `GCA_000001405.15` (GRCh38)
- Sequence collection: `FULL_PLUS_HS38D1_ANALYSIS_SET`
- Source FASTA:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/GCA_000001405.15_GRCh38_full_plus_hs38d1_analysis_set.fna.gz`
- Publisher checksum manifest:
  `https://ftp.ncbi.nlm.nih.gov/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38/seqs_for_alignment_pipelines.ucsc_ids/md5checksums.txt`

The builder downloads the FASTA and checksum manifest, requires exactly one
publisher MD5 entry for the source filename, verifies the compressed source
bytes, decompresses the FASTA, generates FAI with samtools, creates the
sequence dictionary with Picard, computes Refget identity and records the
processed FASTA byte size, then emits `reference-package.json`. The generated
dictionary and FAI are derived artifacts and are validated against the actual
FASTA content. During registration/qualification, the existing staging state
machine independently measures the already-acquired FASTA and the qualification
engine rechecks the persisted evidence.

Example:

```bash
uv run python scripts/reference/build_ncbi_grch38_reference_package.py \
  --output-dir /var/lib/siraloom/reference-staging/GRCh38-full-plus-hs38d1 \
  --samtools samtools \
  --bcftools bcftools \
  --picard-jar /opt/picard/picard.jar
```

The builder deliberately reports `BUILT_NOT_REGISTERED`. The manual workflow
then calls `scripts/reference/register_and_qualify_reference_package.py` to
register the package as `CANDIDATE`, verify the already-acquired FASTA through
the governed staging lifecycle, execute reference-backed BCFtools normalization
checks against that exact FASTA, execute the package qualification engine, and
persist the resource, staging record, and qualification in a disposable SQLite
registry. The SQLite database and qualification report are retained as CI
artifacts. Activation is deliberately not requested by this workflow.

This disposable registry run proves the complete acquisition-to-persisted-
qualification path against the real NCBI bytes. It does not register or activate
the package in a SIRALOOM production/laboratory database. Production registration
must use the deployed application's governed database service, storage backend,
and migration state; production activation remains a separate governance
decision. The real NCBI acquisition workflow must be run before claiming that
the selected package has passed full-genome qualification. The NCBI source set is an
assembly-analysis collection based on GCA_000001405.15; it must not be
mislabelled as RefSeq `GCF_000001405.40` or as a DRAGEN multigenome bundle.

## Operational boundaries

- A registered resource is not necessarily staged, qualified, approved for an
  organization, or active.
- A qualified package is not proof that a particular VCF was produced against
  that package. Per-callset reference provenance and compatibility remain
  separate intake checks.
- Exact contig names are the default. Aliases require explicit, versioned,
  unambiguous policy and evidence; no automatic `chr` prefixing is allowed.
- External, alternate, decoy, HLA, EBV, and other auxiliary contigs are not
  automatically invalid. Their sequence identity and handling policy must be
  established; unresolved records remain visible and must not disappear through
  projection.
- GATK-compatible `.dict` is a required package asset. DeepVariant indexes,
  DRAGEN hash tables, and aligner indexes are tool-specific derived assets.
  They must be tied to the same approved sequence collection and pinned tool
  release, but they do not create different biological reference identities.
- A successful package qualification is a resource-integrity gate, not a
  complete laboratory validation or a guarantee of successful clinical
  interpretation.

## Tests

Run the focused package and registry tests:

```bash
uv run --locked pytest -q \
  tests/test_reference_identity.py \
  tests/test_reference_package.py \
  tests/test_reference_registry_qualification.py \
  tests/test_ncbi_reference_builder.py \
  tests/test_reference_resource_registry.py \
  tests/test_resource_qualification.py
```

The CI backend suite runs these tests with the repository's pinned Python and
HTSlib/BCFtools environment. Full-genome GRCh38 package qualification remains
an explicit release operation and is not performed by these small fixture
tests.
