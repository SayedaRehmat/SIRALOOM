# Pinned regional reference fixture

- **Source:** NCBI RefSeq primary-assembly chromosome `NC_000007.14`, GRCh38.p14.
- **Assembly:** GRCh38.p14 RefSeq, assembly accession `GCF_000001405.40` (`NC_000007.14`). The NCBI assembly report states the RefSeq and GenBank assemblies are not identical; this fixture records the RefSeq source identity, not the GenBank accession.
- **Interval:** 1-based `140253336-141253335` (1,000,000 bases).
- **Retrieval:** NCBI E-utilities EFetch on 2026-11-02 with `db=nuccore`, `id=NC_000007.14`, `seq_start=140253336`, `seq_stop=141253335`, `rettype=fasta`, `retmode=text`.
- **Index generation:** `bgzip (htslib) 1.19` generated the BGZF stream and GZI; `samtools 1.19.2` generated the FAI. The checked-in hashes pin all three bytes.
- **Known answer:** GRCh38 BRAF V600E genomic position `7:140753336` (local interval position 500001) has REF `A`; the test also verifies a substituted `G` REF is rejected.
- **Scope:** this is a 1 Mb regional fixture for package/index and REF-validation execution. It is not a whole chromosome or genome reference package and does not qualify assembly-wide completeness or laboratory use.

SHA-256:

- `reference.fa.bgz`: `9a9eaab99264754b6afe617d3817db84f2256cce2b59b913d385a4b5e82804cc`
- `reference.fa.bgz.fai`: `bf544e276d397b4bc6f6e0e83bd9b8637439ebe2990a8580a9ea12d9f8ede283`
- `reference.fa.bgz.gzi`: `067cbc024a24e2254ca591ea5022001639bb7ca11e089e70633db66b7c3b9dd9`
