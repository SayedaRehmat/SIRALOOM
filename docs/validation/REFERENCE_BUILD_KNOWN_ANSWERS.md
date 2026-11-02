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

## Pinned RefSeq sequence spot checks

On 2026-11-02, I independently retrieved the listed intervals using NCBI E-utilities `efetch` against versioned chromosome accessions. All eight matched the expected REF sequence: BRAF A (GRCh37 NC_000007.13:140453136; GRCh38 NC_000007.14:140753336), HBB T (GRCh37 NC_000011.9:5248232; GRCh38 NC_000011.10:5227002), EGFR T (GRCh37 NC_000007.13:55259515; GRCh38 NC_000007.14:55191822), and CFTR CTT (GRCh37 NC_000007.13:117199646-117199648; GRCh38 NC_000007.14:117559592-117559594). Retrieval used `db=nuccore`, the exact versioned accession and 1-based `seq_start`/`seq_stop`; expected alleles were independently recorded in the table above. These spot checks verify specific primary-assembly sequence intervals, not a complete assembly package, its full contig set, or full-genome checksum. NCBI's assembly report lists GRCh38.p14 RefSeq as GCF_000001405.40 and GenBank as GCA_000001405.29, and explicitly notes those assemblies are not identical; GRCh37.p13 is GCF_000001405.25 / GCA_000001405.14. The chromosome RefSeq accessions above are therefore attributed to their RefSeq assembly identity.

## Automated checks

`tests/test_reference_build_known_answers.py` provides two distinct levels of verification:

1. **Offline contract tests (normal CI):** assert that GRCh37 and GRCh38 select the correct Ensembl REST endpoint for BRAF, HBB, EGFR and CFTR known-answer regions. The provider response is stubbed with the independently sourced expected reference sequence.
2. **Live reference integration tests (opt-in):** query Ensembl's assembly-specific endpoint for each SNV base and the three-base CFTR deletion reference sequence.

Run the live check in a network-enabled, controlled validation environment:

```bash
SIRALOOM_ENABLE_LIVE_REFERENCE_TESTS=1 pytest -m integration tests/test_reference_build_known_answers.py
```

The offline tests verify request construction and assembly selection; they do not query live sequence. The opt-in tests verify these exact reference segments against Ensembl, but do not qualify a complete FASTA package or the full contig set. Release qualification still requires independently sourced SNV and indel truth cases across relevant contigs, reference-package checksum and FAI/GZI validation, normalization equivalence checks, and a qualified truth-set benchmark.

## Reference package reader boundary

Reference packages support plain FASTA/FAI under schema 1.0 and BGZF FASTA/FAI/GZI under schema 1.1. For BGZF, the package validator checks gzip/BGZF block structure, CRC and uncompressed sizes, exact GZI block boundaries, FAI geometry against decompressed sequence, and checksums for FASTA, FAI and GZI. The random-access reader translates FAI uncompressed byte offsets through the validated GZI and reads the selected BGZF blocks. A fixture exercises reads spanning package block boundaries and checks the package checksum. An interoperability test additionally consumes a `.gzi` generated by HTSlib `bgzip`; CI requires this test tool from the pinned HTSlib 1.25 environment. A local independent run against Samtools/HTSlib 1.19 also passed. These are algorithm and tool-interoperability checks only. A full GRCh38.p14 RefSeq package validation was subsequently completed; see the full-package section below. Full GRCh37 identity remains unverified. The contract follows the HTSlib [FASTA index documentation](https://www.htslib.org/doc/faidx.html), [samtools faidx documentation](https://www.htslib.org/doc/1.21/samtools-faidx.html), and [bgzip/GZI documentation](https://www.htslib.org/doc/1.19/bgzip.html).

## Source records

- NCBI ClinVar BRAF Variation 33312922: https://www.ncbi.nlm.nih.gov/clinvar/33312922/
- NCBI ClinVar HBB RCV000576548: https://www.ncbi.nlm.nih.gov/clinvar/RCV000576548/
- NCBI ClinVar EGFR Variation 16609: https://www.ncbi.nlm.nih.gov/clinvar/variation/16609/
- NCBI ClinVar CFTR Variation 7105: https://www.ncbi.nlm.nih.gov/clinvar/variation/7105/
- NCBI Genome Reference Consortium human assembly overview (GRCh38.p14 / GRCh37.p13 accessions): https://www.ncbi.nlm.nih.gov/grc/human
- NCBI RefSeq chromosome 7, GRCh38.p14: https://www.ncbi.nlm.nih.gov/nuccore/NC_000007.14/
- NCBI E-utilities EFetch documentation: https://www.ncbi.nlm.nih.gov/books/NBK25499/
- ClinGen allele representation examples for CFTR p.Phe508del: https://dataexchange.clinicalgenome.org/allele/implementation/integrated_examples/scenario_group_3.html
- GA4GH VRS BRAF V600 example (GRCh38): https://cat-vrs.ga4gh.org/en/1.1.1/examples/braf-v600.html


## Full GRCh38.p14 RefSeq package validation

On 2026-11-02, the official NCBI Datasets v2 download endpoint supplied the complete `GCF_000001405.40` genomic FASTA ZIP package (archive 972,902,348 bytes; FASTA member 3,339,739,109 bytes). The extracted FASTA's MD5, `689762f267eafe361b6ee4b21638eb51`, matched NCBI's `md5sum.txt`; SIRALOOM independently computed FASTA SHA-256 `df6e4918316e05a9cc1fd29c352841d3678b607d7a436819cd43371b52c814c0`. Samtools/HTSlib 1.19.2 generated the FAI (`0afdd6ac2a873585725622de2310a55a5f6065b623a093467e7e26c66ba61de7`, 705 indexed sequence records). The SIRALOOM package validator checked every FAI identifier, sequence length, uncompressed offset and line geometry against the entire extracted FASTA, and accepted the exact RefSeq assembly metadata (`GRCh38.p14`, `GCF_000001405.40`, `FULL_GENOMIC_FASTA`). Its resulting package identity checksum was `2ebc3fe70ef13d6ef133250010018bf72a338a028993fa60438a89e5c5fef4ec`.

The actual VCF REF validator accepted four independently sourced records against this full FASTA: BRAF `NC_000007.14:140753336 A`, HBB `NC_000011.10:5227002 T`, EGFR `NC_000007.14:55191822 T`, and CFTR `NC_000007.14:117559592 CTT`. Replacing BRAF's REF with `G` failed explicitly with `VCF_REFERENCE_MISMATCH`. This validates resource integrity and these known answers; it is not a truth-set benchmark, comprehensive assembly qualification, variant-calling validation, or clinical validation. Full GRCh37 was not acquired or checked.

The full-reference check also exposed a performance defect: Python-level iteration over every nucleotide made the 3.3 GB FASTA scan impractically slow. `validate_fasta_index_consistency` now uses `bytes.translate` for C-level IUPAC alphabet validation; regression tests cover accepted upper/lowercase IUPAC symbols and rejection of an invalid symbol. Full package validation completed in approximately one minute in this environment. NCBI API documentation: https://www.ncbi.nlm.nih.gov/datasets/docs/v2/how-tos/genomes/download-genome/ . The RefSeq/GenBank assembly distinction above remains applicable: this package is RefSeq `GCF_000001405.40`, not the non-identical GenBank `GCA_000001405.29` package.
