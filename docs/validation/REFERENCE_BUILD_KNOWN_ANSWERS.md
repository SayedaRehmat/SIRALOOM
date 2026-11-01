# GRCh37 / GRCh38 reference known-answer validation

## Canonical cross-assembly test case

The initial assembly-selection known-answer case is **BRAF NM_004333.4:c.1799T>A (p.Val600Glu)**, ClinVar Variation ID **33312922**.

| Assembly | Contig | 1-based position | REF | ALT |
|---|---:|---:|---:|---:|
| GRCh37 | 7 | 140453136 | A | T |
| GRCh38 | 7 | 140753336 | A | T |

The coordinates and alleles are recorded by NCBI ClinVar for the assembly-specific genomic accessions NC_000007.13 (GRCh37) and NC_000007.14 (GRCh38). The GRCh38 coordinate is also represented in the GA4GH VRS BRAF V600 example.

## Automated checks

`tests/test_reference_build_known_answers.py` provides two distinct levels of verification:

1. **Offline contract tests (normal CI):** assert that GRCh37 and GRCh38 select their respective Ensembl REST endpoints and assembly-specific BRAF coordinates, and that the expected reference allele is returned to the provider contract.
2. **Live reference integration test (opt-in):** query the authoritative Ensembl endpoint for each assembly and assert that the reference base at the known coordinate is A.

Run the live check in a network-enabled, controlled validation environment:

```bash
SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS=1 pytest -m integration tests/test_reference_build_known_answers.py
```

The offline test does not substitute for the live check. A passing live BRAF SNV check is an assembly-selection smoke test, not full GRCh37/GRCh38 qualification. Release qualification still requires independently sourced SNV and indel truth cases across relevant contigs, reference-package checksum and FAI/GZI validation, and normalization equivalence checks.

## Source records

- NCBI ClinVar Variation 33312922: https://www.ncbi.nlm.nih.gov/clinvar/33312922/
- GA4GH VRS BRAF V600 example (GRCh38): https://cat-vrs.ga4gh.org/en/1.1.1/examples/braf-v600.html
