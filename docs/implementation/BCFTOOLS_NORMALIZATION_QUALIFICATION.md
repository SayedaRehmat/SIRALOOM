# BCFtools normalization release qualification

## Safety floor

SIRALOOM does not qualify every historical BCFtools release merely because its
version string can be resolved. The minimum eligible release is **1.23.1**.

The upstream BCFtools 1.23.1 release notes document a fix for silent output
truncation when input read errors occur in `norm` and several other commands.
A normalization pipeline must not treat a truncated output as a complete
scientific result. Releases before 1.23.1 are therefore blocked before the
normalization known-answer execution.

Source: https://github.com/samtools/bcftools/blob/develop/NEWS

## Executable compatibility qualification

The CI qualification workflow executes the actual NIST GIAB HG002 v4.2.1
benchmark callset on the complete chromosome 1 for both GRCh38 and GRCh37.
Each assembly uses its matching Ensembl chromosome-1 reference. The GRCh38
VCF/index and reference archives have immutable SHA-256 pins; Ensembl reference
archives are also checked against the publisher's official CHECKSUMS MD5
manifest. The GRCh37 VCF/index SHA-256 values are currently captured in
qualification evidence and must be promoted to immutable pins after the first
verified acquisition run.

| BCFtools release | Acquisition and qualification |
|---|---|
| 1.23.1 | Bioconda binary; pending full matrix CI |
| 1.23.2 | Built from matching upstream BCFtools/HTSlib tags; pending full matrix CI |
| 1.23.3 | Built from matching upstream BCFtools/HTSlib tags; pending full matrix CI |
| 1.24 | Bioconda binary; pending full matrix CI |
| 1.24.1 | Built from matching upstream BCFtools/HTSlib tags; pending full matrix CI |
| 1.25 | Bioconda binary; pending full matrix CI |

A release is not considered compatible until its actual CI run passes. The
matrix uses Bioconda binaries where published and builds exact matching upstream
BCFtools and HTSlib release tags where a binary package is unavailable. It
records source/package provenance, executable SHA-256, exact tool version,
normalized VCF, CSI index, source-child reconciliation, and reference identity
in the qualification artifact.

This matrix is a finite, explicit compatibility contract—not a claim that
every historical, prerelease, vendor-patched, or future BCFtools build is
interchangeable. Each newly discovered stable release remains a candidate
until the same execution qualification succeeds and the laboratory approves
its exact resource binding.

## VCF specification parser interoperability

For every release in the executable matrix, CI also runs the actual BCFtools
parser against the versioned VCF fixtures: VCFv4.0 legacy parser smoke and
VCFv4.1 through VCFv4.5. The VCFv4.5 set includes local-allele encoding,
base-modification FORMAT fields, and unspecified-allele reference-block
fixtures. This is parser interoperability evidence only; it does not replace
the native validator's normative clause conformance qualification.

## Immutable upstream source pins

The following source-built releases are pinned to the commit objects behind
their GitHub-verified release tags. CI checks both repositories' checked-out
commit SHA before compiling or executing the binary.

| Release | BCFtools commit | HTSlib commit |
|---|---|---|
| 1.23.2 | `db87bf9833f06a5cde792a5118a0a83d2860a179` | `3beae100a4c6b066e7f601f7e244bb371b9c1c16` |
| 1.23.3 | `ec74c62952f53c14459acb5283a7483b41c4ade3` | `02594b767d74e7992971d286a79dc2b60a7b9257` |
| 1.24.1 | `2fd5931cdf3a7ef27ab843dda27da844b4ea2a51` | `a6962b2d8d748d699258eb1def48d770544f73e2` |

A changed or moved tag fails the qualification job rather than silently
building different source bytes.

## Scope of the GIAB execution

The real-data qualification downloads the complete NIST GIAB HG002 v4.2.1
benchmark VCF and TBI for each assembly, extracts the complete chromosome-1
callset, and executes strict validation, reference-allele validation, record
routing, reference-aware normalization, source-to-child reconciliation,
BGZF output validation, and CSI index concordance.

- GRCh38: Ensembl release 115 chromosome 1 reference; the archive is pinned by
  SHA-256 and checked against the official Ensembl CHECKSUMS MD5 manifest.
- GRCh37: Ensembl release 75 chromosome 1 reference; the archive is checked
  against the official Ensembl CHECKSUMS MD5 manifest. The GIAB VCF and TBI
  SHA-256 values are captured in the generated report; immutable pins remain
  pending the first successful acquisition run.

This is real-data normalization and interoperability evidence, not a
full-genome caller-accuracy benchmark. It does not establish all VCF normative
clause conformance and does not replace laboratory qualification of exact
executable bytes and organization-approved resource binding. The current
matrix records an executable digest measured for the run and verifies that
the same bytes remain in use throughout execution; a lab-approved resource
still requires its independently qualified, immutable digest and approval.

## Reference documentation

- BCFtools manual: https://samtools.github.io/bcftools/bcftools
- BCFtools releases: https://github.com/samtools/bcftools/releases
- GA4GH HTS specifications: https://samtools.github.io/hts-specs/
- GIAB/NIST benchmarking guidance: https://www.nist.gov/programs-projects/faqs-genome-bottle
