# Human sex-chromosome PAR region policy for VCF Stage 1

## Purpose and implementation boundary

SIRALOOM's existing VCF validator derives FORMAT Number=G cardinality from each sample's GT ploidy. This change introduces an isolated, tested reference-data utility for classifying X/Y intervals against GRCh37 and GRCh38 pseudoautosomal regions (PARs).

**This PR does not yet wire the classifier into the production VCF workflow.** The production validator and workflow files are intentionally not modified because independent open pull requests are concurrently changing those shared files. The helper must be integrated into the production validation/reporting path after those changes are reconciled.

The classifier does not infer karyotype, biological sex, sample ploidy, or inheritance. It does not reject genotypes based on presumed chromosome ploidy.

## Authoritative coordinate source

The interval table follows the Genome Reference Consortium (GRC) human assembly overview and Ensembl's human PAR definitions:

- GRCh37 X PAR1: 60,001–2,699,520; X PAR2: 154,931,044–155,260,560.
- GRCh37 Y PAR1: 10,001–2,649,520; Y PAR2: 59,034,050–59,363,566.
- GRCh38 X PAR1: 10,001–2,781,479; X PAR2: 155,701,383–156,030,895.
- GRCh38 Y PAR1: 10,001–2,781,479; Y PAR2: 56,887,903–57,217,415.

Coordinates are 1-based and inclusive, matching VCF POS. Patch releases retain the coordinate system of their major assembly. The implementation accepts GRCh37/GRCh38 and patch labels, plus hg19/hg38 aliases. It does not accept arbitrary assemblies such as T2T-CHM13.

## Runtime behavior of the isolated helper

The classifier returns:

- PAR: the complete queried reference interval is within a defined PAR.
- NON_PAR: the queried X/Y interval does not overlap a defined PAR.
- PAR_BOUNDARY_CROSSING: the interval overlaps a PAR but extends outside it.
- NOT_SEX_CHROMOSOME: the contig is not recognized as X or Y.

It accepts a 1-based closed interval and checks the full supplied interval, not only its first base. Unknown builds and invalid coordinates fail closed.

## Deliberate limits and next qualification requirements

This helper is not a complete sex-chromosome ploidy policy. Before applying genotype expectations, SIRALOOM still needs:

1. Production workflow integration with the selected reference package's exact assembly identity.
2. A governed sample-ploidy/karyotype metadata model with provenance and permissioned access.
3. Caller- and version-specific documentation of how sex chromosomes and PARs are represented.
4. A policy for X/Y PAR duplicate representation, masking, and contig aliases in each approved reference package.
5. A separate mitochondrial ploidy/heteroplasmy policy; mitochondrial records are not classified here.
6. Representative GRCh37 and GRCh38 assay/caller fixtures and independently reviewed expected results.
7. Tests for missing metadata, discordant caller metadata, and variants whose REF span crosses a boundary.

No ploidy is inferred from GT, observed allele balance, or a sample's X/Y calls. Ambiguous or missing metadata must remain unresolved rather than being converted into a guessed haploid/diploid expectation.

## Sources

- Genome Reference Consortium — https://www.ncbi.nlm.nih.gov/grc/human
- Ensembl human PAR definitions — https://www.ensembl.org/info/genome/genebuild/human_PARS.html
- Ensembl GRCh37 assembly — https://grch37.ensembl.org/info/genome/genebuild/assembly.html
- GA4GH/HTS VCF specifications — https://samtools.github.io/hts-specs/
