# GIAB / GA4GH small-variant concordance runner

## Purpose and boundary

`scripts/validation/run_giab_concordance.py` compares a laboratory query VCF with an independently curated truth VCF using Illumina hap.py. hap.py performs haplotype-level comparison rather than naïve row-by-row matching and quantifies calls within the supplied confident regions. This runner is separate from `run_vcf_scale_benchmark.py`: the latter measures SIRALOOM processing behavior, while this runner measures small-variant call concordance.

The runner is an evidence-generation tool. It always emits `CONCORDANCE_RUN_COMPLETE_REVIEW_REQUIRED`, never QUALIFIED or clinically validated.

## Inputs

Required:
- one-sample truth VCF;
- one-sample query VCF (no implicit sample selection from multisample inputs);
- matching GIAB confident-region BED;
- exact reference FASTA and adjacent `.fai`;
- explicit GRCh37/GRCh38 build;
- assay (WES, WGS or PANEL);
- exact caller name and caller version;
- truth-set identifier and release (for example, GIAB HG002 GRCh38 v4.2.1);
- preapproved laboratory acceptance-policy identifier.

WES and PANEL additionally require the exact assay target BED. The target BED is passed with hap.py `-T`; the GIAB confident BED is separately passed with `-f`. Optional GA4GH stratification TSVs are passed with `--stratification`, and the resulting extended CSV is retained. Symbolic alleles, spanning-deletion alleles, and breakends are rejected because this runner is scoped to small variants. All input files are SHA-256 recorded and rechecked after execution.

Truth and query sample identifiers are not written to the JSON report. The restricted output directory contains hap.py's own outputs/log; protect it as controlled laboratory evidence because upstream tools may include source metadata in their files. The output directory must not already exist and is created with mode 0700; the log and failure record use mode 0600.

## Tool behavior

- Runtime hap.py version is obtained from the executable's `--version` output; the runner does not trust a user-supplied version string. The tool-generated `.runinfo.json` is required and hashed to retain execution-argument provenance.
- Default engine is `xcmp`, hap.py's haplotype-level engine. `vcfeval` is permitted only where the laboratory has installed and qualified the compatible RTG-Tools build.
- ALL and PASS summaries are retained; `--pass-only` is an explicit option and is not enabled by default.
- The runner requires SNP and INDEL rows for both ALL and PASS in hap.py's `summary.csv`.
- Precision, recall and F1 are recomputed from raw TP/FN/FP counts. Descriptive 95% Wilson intervals are retained for precision and recall. A zero denominator is `null`.
- For optional stratification, the source `.extended.csv` is retained and SHA-256 recorded.
- Tool stdout/stderr is redirected to a restricted log. Failure JSON stores only the exception class, not exception text or paths.

## Example

GRCh38 WES:

```bash
python scripts/validation/run_giab_concordance.py \
  --truth-vcf /secure/giab/HG002_GRCh38.vcf.gz \
  --query-vcf /secure/query/HG002_sample_only.vcf.gz \
  --confident-bed /secure/giab/HG002_GRCh38_confident.bed.gz \
  --reference-fasta /secure/reference/GRCh38.fa \
  --reference-build GRCh38 \
  --assay WES \
  --target-regions /secure/assay/capture_v3.bed \
  --stratification-tsv /secure/ga4gh/stratification.tsv \
  --caller approved-caller \
  --caller-version 4.2.1 \
  --truth-set-id GIAB-HG002-GRCh38 \
  --truth-set-version 4.2.1 \
  --acceptance-policy-id LAB-APPROVED-SNV-INDEL-001 \
  --engine xcmp \
  --threads 8 \
  --output-dir /secure/evidence/giab-wes-grch38-001
```

For WGS, omit `--target-regions` unless the approved WGS validation plan specifies a region restriction. Do not use a target BED to silently redefine the WGS intended use.

## Required laboratory review

Review each assay × caller/version × build cell separately. Confirm:
1. GIAB sample, release, assembly, truth VCF and confident BED are a matched set;
2. reference FASTA/FAI and query VCF correspond to the declared assembly;
3. target BED matches the validated capture design (WES/PANEL);
4. hap.py version and comparison engine are approved and fixed for comparisons;
5. SNP/INDEL and ALL/PASS counts, precision, recall, F1 and intervals meet preapproved criteria;
6. stratified performance and difficult-region limitations are reviewed;
7. low truth counts and wide intervals are not hidden by aggregate metrics;
8. exclusions, unsupported variant classes and all deviations are documented;
9. an authorized reviewer signs and dates the acceptance decision.

The Wilson intervals are simple binomial intervals and do not account for correlation among variants or genomic clustering. The laboratory must predefine whether additional confidence-interval, replicate, orthogonal-confirmation, or reproducibility analyses are required. GIAB confident regions are not a guarantee of performance outside those regions; WES/PANEL subsets can contain relatively few difficult variants.

## Research references

- NIST GIAB benchmarks and release information: https://www.nist.gov/programs-projects/genome-bottle
- NIST GIAB FAQ (targeted/exome limitations and confidence intervals): https://www.nist.gov/programs-projects/faqs-genome-bottle
- GA4GH Benchmarking Team reference methods: https://github.com/ga4gh/benchmarking-tools
- Zook et al. (2019), *Nature Biotechnology*, doi:10.1038/s41587-019-0054-x
- Illumina hap.py user manual: https://github.com/Illumina/hap.py/blob/master/doc/happy.md
- CLSI MM09, 3rd edition (2023): https://clsi.org/shop/standards/mm09/

This documentation does not reproduce licensed CLSI text. The laboratory must work from its controlled copy of applicable standards and its own approved quality-management procedures.
