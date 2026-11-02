# VCF conformance fixtures

This directory contains SIRALOOM-owned, versioned fixtures for the native strict
VCF validator. The normative source is the GA4GH Large Scale Genomics HTS
specifications repository:

- https://github.com/samtools/hts-specs
- VCFv4.1: https://samtools.github.io/hts-specs/VCFv4.1.pdf
- VCFv4.2: https://samtools.github.io/hts-specs/VCFv4.2.pdf
- VCFv4.3: https://samtools.github.io/hts-specs/VCFv4.3.pdf
- VCFv4.4: https://samtools.github.io/hts-specs/VCFv4.4.pdf
- VCFv4.5: https://samtools.github.io/hts-specs/VCFv4.5.pdf

## Scope

`conformance_cases.json` is the machine-readable test manifest. Every case
includes its version, case ID, category, expected validator result, specification
basis and VCF lines. The pytest harness writes each fixture to a temporary file
and executes the production `validate_vcf_strict` entry point.

For VCFv4.1-v4.5, the manifest tests:
- valid fixed-column records and headers;
- valid multiallelic genotypes and Number=G cardinality;
- valid symbolic deletion representation and missing-span rejection;
- duplicate structured-header identifier rejection;
- out-of-range genotype allele rejection;
- VCFv4.3 versus VCFv4.4 leading GT phase-separator behavior;
- VCFv4.4 rejection and VCFv4.5 acceptance of local-allele cardinality;
- VCFv4.5 base-modification FORMAT fraction acceptance and out-of-range rejection.

VCFv4.0 is deliberately classified as a legacy parser compatibility smoke
fixture only. The current HTS specifications index lists VCFv4.1 through
VCFv4.5 as normative VCF documents; SIRALOOM must not represent its VCFv4.0
smoke test as an equivalent official conformance qualification.

## Interpretation

A passing fixture means only that the tested behavior matches the expected
result for that fixture. It does not prove complete conformance to every
normative clause, every optional extension, or every producer's dialect.
Uncovered clauses remain unqualified until additional fixtures and independent
cross-implementation tests are added. Unknown VCF versions remain fail-closed.

These are SIRALOOM-authored fixtures derived from the cited normative clauses;
they are not copied wholesale from upstream test data and are not an upstream
certification suite.
