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

The CI qualification workflow executes the same downloaded, checksum-pinned
NIST GIAB HG002 GRCh38 VCF slice and the same pinned Ensembl GRCh38 reference
against each stable release below:

| BCFtools release | Qualification |
|---|---|
| 1.23.1 | Executed in CI |
| 1.23.2 | Executed in CI |
| 1.23.3 | Executed in CI |
| 1.24 | Executed in CI |
| 1.24.1 | Executed in CI |
| 1.25 | Executed in CI |

A release is not considered compatible until its actual CI run passes. The
matrix records the executable SHA-256, exact tool version, normalized VCF,
CSI index, source-child reconciliation, and reference identity in the
qualification artifact.

This matrix is a finite, explicit compatibility contract—not a claim that
every historical, prerelease, vendor-patched, or future BCFtools build is
interchangeable. Each newly discovered stable release remains a candidate
until the same execution qualification succeeds and the laboratory approves
its exact resource binding.

## Scope of the GIAB execution

The real-data qualification uses the NIST GIAB HG002 v4.2.1 GRCh38 benchmark
VCF, restricted to chromosome 1 positions 1–5,000,000, and Ensembl release 115
chromosome 1 reference. It validates real input parsing, reference alleles,
routing, reference-aware normalization, source-to-child lineage, BGZF output,
and CSI index concordance.

This bounded slice is an interoperability and normalization regression test.
It is not a full-genome caller-accuracy benchmark, does not establish all VCF
normative clause conformance, and does not replace laboratory qualification
of the exact executable bytes and organization-approved resource binding.

## Reference documentation

- BCFtools manual: https://samtools.github.io/bcftools/bcftools
- BCFtools releases: https://github.com/samtools/bcftools/releases
- GA4GH HTS specifications: https://samtools.github.io/hts-specs/
- GIAB/NIST benchmarking guidance: https://www.nist.gov/programs-projects/faqs-genome-bottle
