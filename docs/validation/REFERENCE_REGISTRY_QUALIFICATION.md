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

## Existing package schemas

- Schema `1.0`: plain FASTA + matching FAI.
- Schema `1.1`: BGZF FASTA + matching FAI and GZI.
- Both schemas require exact contig policy, assembly name/accession, source,
  sequence scope, ordered contig names/lengths, FASTA/FAI checksums, contig
  manifest digest, and package identity checksum.

The package validator checks the complete FASTA sequence stream, IUPAC alphabet,
FAI identifier/order/length/offset/line geometry, and (for BGZF) block integrity,
CRC, uncompressed lengths, and exact GZI block boundaries. The package identity
checksum binds the assembly metadata and artifact/contig digests.

The current schemas do not yet require a SAM sequence dictionary or per-contig
GA4GH Refget identifiers. Those are explicitly tracked as follow-on package
schema work; their absence must not be misrepresented as already qualified.

## Registry lifecycle

Reference releases are registered as `CANDIDATE`, never directly as active.
The registry reuses the shared `resources`, `resource_stagings`, and
`resource_qualifications` models:

`CANDIDATE → QUALIFIED → ACTIVE → SUPERSEDED`

- Registration validates the manifest's structure and immutable identity.
- Staging binds the exact resource ID/version and FASTA artifact location.
- Qualification executes byte-level package validation and records a structured
  result with blockers and checks.
- Activation requires a persisted successful qualification for the exact
  qualification version.
- Failed qualification remains blocked; it does not activate or silently
  replace an existing active release.
- Superseded releases remain addressable for reproducibility.

The resource-level `checksum` is the package identity checksum. The staging
checksum is the FASTA artifact SHA-256. These are different digest domains and
must not be compared as if they were the same value.

## Qualification evidence

The qualification engine verifies:

- resource type, build, package schema, and candidate lifecycle state;
- assembly accession, reference source, and declared sequence scope;
- exact contig policy and ordered contig manifest;
- FASTA, FAI, and optional GZI checksums;
- FASTA/FAI sequence and byte-layout consistency;
- BGZF/GZI block structure and offsets when applicable;
- package identity checksum;
- staging resource/version/location binding and staged FASTA digest;
- source contract and declared runtime toolchain.

The qualification report includes a stable outcome, package checksum,
assembly accession, sequence scope, contig count, and artifact digests. A
package is not qualified merely because a path exists or a version string is
declared.

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
- GATK `.dict`, DeepVariant indexes, DRAGEN hash tables, and aligner indexes
  are tool-specific derived assets. They must be tied to the same approved
  sequence collection and pinned tool release, but they do not create different
  biological reference identities.
- A successful package qualification is a resource-integrity gate, not a
  complete laboratory validation or a guarantee of successful clinical
  interpretation.

## Tests

Run the focused package and registry tests:

```bash
uv run --locked pytest -q \
  tests/test_reference_package.py \
  tests/test_reference_registry_qualification.py \
  tests/test_reference_resource_registry.py \
  tests/test_resource_qualification.py
```

The CI backend suite runs these tests with the repository's pinned Python and
HTSlib/BCFtools environment. Full-genome GRCh38 package qualification remains
an explicit release operation and is not performed by these small fixture
tests.
