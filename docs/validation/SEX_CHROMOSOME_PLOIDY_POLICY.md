# Human sex-chromosome PAR region policy for VCF Stage 1

## Purpose

SIRALOOM's strict VCF validator derives FORMAT Number=G cardinality from each sample's GT ploidy. This policy adds reference-build-aware classification of X/Y reference intervals so that downstream validation can distinguish pseudoautosomal (PAR) from non-PAR records.

**This implementation classifies genomic intervals only. It does not infer karyotype, biological sex, sample ploidy, or inheritance. It does not reject a genotype merely because it differs from a presumed chromosome ploidy.**

## Authoritative coordinate source

The interval table follows the Genome Reference Consortium (GRC) human assembly overview and Ensembl's human PAR definitions:

- GRCh37 X PAR1: 60,001–2,699,520; X PAR2: 154,931,044–155,260,560.
- GRCh37 Y PAR1: 10,001–2,649,520; Y PAR2: 59,034,050–59,363,566.
- GRCh38 X PAR1: 10,001–2,781,479; X PAR2: 155,701,383–156,030,895.
- GRCh38 Y PAR1: 10,001–2,781,479; Y PAR2: 56,887,903–57,217,415.

Coordinates are 1-based and inclusive, matching VCF POS. Patch releases retain the coordinate system of their major assembly. The implementation accepts GRCh37/GRCh38 and patch labels, plus hg19/hg38 aliases. It does not accept arbitrary assemblies such as T2T-CHM13.

## Runtime behavior

The classifier returns:

- PAR: the complete queried reference interval is within a defined PAR.
- NON_PAR: the queried X/Y interval does not overlap a defined PAR.
- PAR_BOUNDARY_CROSSING: the interval overlaps a PAR but extends outside it.
- NOT_SEX_CHROMOSOME: the contig is not recognized as X or Y.

The strict validator accepts an optional reference_build. When supplied, it records X/Y region counts in sex_chromosome_region_assessment. The report explicitly states NOT_APPLIED_SAMPLE_PLOIDY_AND_CALLER_POLICY_REQUIRED. When the build is omitted, no PAR classification is attempted. An unsupported explicitly supplied build fails closed.

## Deliberate limits and next qualification requirements

This does not establish a complete sex-chromosome ploidy policy. Before applying genotype expectations, SIRALOOM still needs:

1. A governed sample-ploidy/karyotype metadata model with provenance and permissioned access.
2. Caller- and version-specific documentation of how sex chromosomes and PARs are represented.
3. A policy for X/Y PAR duplicate representation, masking, and contig aliases in each approved reference package.
4. A separate mitochondrial ploidy/heteroplasmy policy; mitochondrial records are not classified here.
5. Representative GRCh37 and GRCh38 assay/caller fixtures and independently reviewed expected results.
6. Tests for all PAR boundary transitions, missing metadata, discordant caller metadata, and variants whose REF span crosses a boundary.

No ploidy is inferred from GT, observed allele balance, or a sample's X/Y calls. Ambiguous or missing metadata must remain unresolved rather than being converted into a guessed haploid/diploid expectation.

## Sources

- Genome Reference Consortium — https://www.ncbi.nlm.nih.gov/grc/human
- Ensembl human PAR definitions — https://www.ensembl.org/info/genome/genebuild/human_PARS.html
- Ensembl GRCh37 assembly — https://grch37.ensembl.org/info/genome/genebuild/assembly.html
- GA4GH/HTS VCF specifications — https://samtools.github.io/hts-specs/
