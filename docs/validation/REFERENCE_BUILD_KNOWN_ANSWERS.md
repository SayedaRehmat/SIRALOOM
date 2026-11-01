# GRCh37 / GRCh38 reference known-answer validation

## Independent cross-assembly cases

The reference-provider contract now has four independently sourced variant examples spanning SNVs and a short in-frame deletion. Genomic coordinates below are 1-based and use the forward strand of the specified assembly.

| Case | Assembly | Contig | Position | REF | ALT | Source |
|---|---|---:|---:|---|---|---|
| BRAF p.Val600Glu (ClinVar Variation 33312922) | GRCh37 | 7 | 140453136 | A | T | [ClinVar 33312922](https://www.ncbi.nlm.nih.gov/clinvar/33312922/) |
| BRAF p.Val600Glu (ClinVar Variation 33312922) | GRCh38 | 7 | 140753336 | A | T | [ClinVar 33312922](https://www.ncbi.nlm.nih.gov/clinvar/33312922/) |
| HBB c.20A>T / p.Glu7Val (Variation 15333) | GRCh37 | 11 | 5248232 | T | A | [ClinVar RCV000576548](https://www.ncbi.nlm.nih.gov/clinvar/RCV000576548/) |
| HBB c.20A>T / p.Glu7Val (Variation 15333) | GRCh38 | 11 | 5227002 | T | A | [ClinVar RCV000576548](https://www.ncbi.nlm.nih.gov/clinvar/RCV000576548/) |
| EGFR c.2573T>G / p.Leu858Arg (Variation 16609) | GRCh37 | 7 | 55259515 | T | G | [ClinVar VCV000016609](https://www.ncbi.nlm.nih.gov/clinvar/variation/16609/) |
| EGFR c.2573T>G / p.Leu858Arg (Variation 16609) | GRCh38 | 7 | 55191822 | T | G | [ClinVar VCV000016609](https://www.ncbi.nlm.nih.gov/clinvar/variation/16609/) |
| CFTR c.1521_1523delCTT / p.Phe508del (Variation 7105) | GRCh37 | 7 | 117199646–117199648 | CTT | — | [ClinVar VCV000007105](https://www.ncbi.nlm.nih.gov/clinvar/variation/7105/) |
| CFTR c.1521_1523delCTT / p.Phe508del (Variation 7105) | GRCh38 | 7 | 117559592–117559594 | CTT | — | [ClinVar VCV000007105](https://www.ncbi.nlm.nih.gov/clinvar/variation/7105/) |

The CFTR deletion has equivalent representations in a local repeat context; ClinGen documents alternate genomic expressions of the same canonical allele. These listed CTT coordinates are the ClinVar assembly-specific expressions, not a claim that all equivalent representations are identical before normalization.

## Automated checks

`tests/test_reference_build_known_answers.py` provides two distinct levels of verification:

1. **Offline contract tests (normal CI):** assert that GRCh37 and GRCh38 select the correct Ensembl REST endpoint for BRAF, HBB, EGFR and CFTR known-answer regions. The provider response is stubbed with the independently sourced expected reference sequence.
2. **Live reference integration tests (opt-in):** query Ensembl's assembly-specific endpoint for each SNV base and the three-base CFTR deletion reference sequence.

Run the live check in a network-enabled, controlled validation environment:

```bash
SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS=1 pytest -m integration tests/test_reference_build_known_answers.py
```

The offline tests verify request construction and assembly selection; they do not query live sequence. The opt-in tests verify these exact reference segments against Ensembl, but do not qualify a complete FASTA package or the full contig set. Release qualification still requires independently sourced SNV and indel truth cases across relevant contigs, reference-package checksum and FAI/GZI validation, normalization equivalence checks, and a qualified truth-set benchmark.

## Source records

- NCBI ClinVar BRAF Variation 33312922: https://www.ncbi.nlm.nih.gov/clinvar/33312922/
- NCBI ClinVar HBB RCV000576548: https://www.ncbi.nlm.nih.gov/clinvar/RCV000576548/
- NCBI ClinVar EGFR Variation 16609: https://www.ncbi.nlm.nih.gov/clinvar/variation/16609/
- NCBI ClinVar CFTR Variation 7105: https://www.ncbi.nlm.nih.gov/clinvar/variation/7105/
- ClinGen allele representation examples for CFTR p.Phe508del: https://dataexchange.clinicalgenome.org/allele/implementation/integrated_examples/scenario_group_3.html
- GA4GH VRS BRAF V600 example (GRCh38): https://cat-vrs.ga4gh.org/en/1.1.1/examples/braf-v600.html
