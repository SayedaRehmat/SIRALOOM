# GIAB HG001 independent caller benchmark — DeepVariant 30x / GRCh37

## Purpose

This is the next stage after the HG001 input-processing benchmark. It generates a **caller query VCF from public aligned Illumina sequencing reads** and compares that query against the original NIST GIAB HG001 NISTv4.2.1 truth VCF. The query is not copied from, derived from, or substituted with the truth VCF or the earlier spanning-deletion processing derivative.

## Dataset and provenance

- Sample: HG001 / NA12878
- Assay: Illumina HiSeq paired-end whole-genome sequencing
- Coverage: nominal 30x downsampled alignment
- Alignment/reference: GRCh37 hs37d5
- BAM: `RMNISTHS_30xdownsample.bam`
- BAI: matching `RMNISTHS_30xdownsample.bam.bai`
- Official MD5 values and source URLs: `benchmarks/giab/hg001_illumina30x_grch37.v1.json`
- The BAM/BAI checksums are transcribed from the versioned NIST GIAB data-index record linked in that manifest.
- Truth VCF, TBI, confident BED and hs37d5 reference are separately acquired using the already pinned `benchmarks/giab/public_assets.v1.json` manifest and verified against upstream MD5 values.

## Caller and comparison

- Caller: Google DeepVariant 1.10.0, Docker image `google/deepvariant:1.10.0`
- Model: `WGS`
- Comparison: Illumina hap.py 0.3.15, haplotype-aware diploid comparison
- Metrics: SNP and INDEL TP/FP/FN, precision, recall, F1, ALL and PASS filter rows, and confidence intervals from the existing concordance runner.
- The sample-column mapping is generated from the actual truth/query VCF headers in a mode-0600 sidecar and is not written to the public run summary.
- The caller query is required to be a distinct byte stream; the concordance runner rejects identical truth/query SHA-256.

## Execution requirements

This workflow is intentionally `workflow_dispatch` only and requires a Linux x86-64 self-hosted GitHub Actions runner with label `giab-highmem`, Docker, at least 32 CPU cores, 256 GiB RAM and 500 GB free scratch. It does **not** run on the ordinary GitHub-hosted CI runner. A 30x WGS caller job is a large compute workload; the workflow fails preflight rather than silently downscaling the data or changing the assay.

Register the runner in the repository, then open Actions → **GIAB HG001 DeepVariant 30x caller concordance** → Run workflow. The source BAM is downloaded only to runner scratch and is deliberately excluded from uploaded artifacts. The caller VCF, index, gVCF, checksums, asset provenance, and concordance evidence are retained for 90 days.

## Interpretation boundary

A completed report is `CONCORDANCE_RUN_COMPLETE_REVIEW_REQUIRED`, not PASS. No laboratory acceptance threshold has been supplied or approved. Review SNP and INDEL results separately, inspect hap.py logs and runinfo, confirm reference/sample provenance, and define intended-use-specific acceptance criteria before qualification. This benchmark covers small variants in GIAB confident regions; it does not validate structural variants, clinical interpretation, reportability, or all genomic contexts.

## Reproducibility references

- NIST GIAB data-index record: [30x HG001 Illumina GRCh37 alignment index](https://github.com/genome-in-a-bottle/giab_data_indexes/blob/fe5327b1deffe6ccdde8912fdf98ec26863594e3/NA12878/alignment.index.NA12878_HiSeq_downsampled30X_GRCh37_10262015)
- DeepVariant official documentation: [Google DeepVariant](https://github.com/google/deepvariant)
- hap.py: [Illumina hap.py](https://github.com/Illumina/hap.py)
- GIAB truth set and confidence regions: [NIST GIAB release](https://github.com/genome-in-a-bottle/giab_latest_release)
