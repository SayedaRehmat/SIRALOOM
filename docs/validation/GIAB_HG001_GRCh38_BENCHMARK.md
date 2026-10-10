# GIAB HG001 / GRCh38 small-variant benchmark protocol

**Status: harness prepared; benchmark not yet executed.** No benchmark result or concordance claim is made by this document.

## Purpose and boundary

This protocol compares a VCF produced by the SIRALOOM normalization path with the NIST/GIAB HG001 benchmark callset using the declared benchmark-confidence regions and the same declared reference build. It is a **VCF representation and small-variant concordance check**, not a test of SIRALOOM variant calling (FASTQ/calling is outside SIRALOOM's current scope).

NIST lists the HG001/NA12878 small-variant benchmark v4.2.1 for GRCh37 and GRCh38 and provides benchmark VCF/BED assets through its official release area. The precise files and hashes must be recorded from the selected release before execution.

## Required controlled inputs

Configure `benchmarks/giab/hg001_grch38.manifest.example.json` as a run manifest, rename/copy it for the run, and fill in:

- Exact HG001 NISTv4.2.1 GRCh38 truth VCF path and SHA-256.
- Exact matching benchmark-confidence BED path and SHA-256.
- Exact GRCh38 reference FASTA path and SHA-256. The chosen reference must match the SIRALOOM reference package and declared contig policy.
- The original input VCF and SIRALOOM-produced normalized VCF, each with SHA-256.
- Exact `bcftools` and `hap.py` environment/version pins.
- An approved, intended-use-specific acceptance policy with approver and criteria. Thresholds must be declared before seeing results; this repository does not invent them.

Do not use an HG001 v4.2.1 VCF with a different build, mismatched BED, alternate reference, or unknown hashes. Keep the upstream license/usage terms and README citation with the staged data.

## Run

Install a pinned `bcftools` and `hap.py`/vcfeval environment, then run:

```bash
python scripts/validation/run_giab_benchmark.py \
  --manifest benchmarks/giab/hg001_grch38.manifest.json \
  --output-dir artifacts/benchmarks/giab-hg001-grch38
```

The runner verifies declared input hashes, records tool output and the executed command, runs `hap.py` restricted to the benchmark BED, and captures the summary output plus a JSON provenance report. It fails closed if the manifest is unconfigured, required hashes are missing/wrong, tools are unavailable, or the declared benchmark identity is inconsistent.

The runner's status is always `RUN_COMPLETE_REVIEW_REQUIRED`; exit code zero means the comparison ran, **not** that the scientific acceptance criteria passed. A reviewer must evaluate raw metrics, discrepancies, exclusions, and the predeclared policy and record a separate signed acceptance decision.

## Required review and release packet

- Git commit, runtime/container image digest, and manifest hash.
- Dataset release, upstream README/license/usage terms, and hashes of truth VCF, BED, reference, input VCF, and SIRALOOM normalized VCF.
- SIRALOOM reference-package ID/build/checksum and exact normalization command/tool version.
- `hap.py`/vcfeval version and full raw summary/extended outputs.
- Predeclared acceptance-policy ID, thresholds, intended use, and approver.
- Discrepancy report with normalized representation/genotype semantics and exclusions explained.
- Reviewer, timestamp, decision, and limitations.

## What this does not establish

GIAB small-variant concordance does not validate annotation transcript selection, population frequencies, ClinVar/ClinGen interpretation, evidence extraction, ACMG criterion application, clinical sign-out, SV/GVCF behavior, or clinical sensitivity/specificity outside the evaluated region and callset. Those need separate versioned reference sets and adjudicated expected outputs. Do not claim clinical validation based on this benchmark alone.

## Official sources

- NIST Genome in a Bottle: https://www.nist.gov/programs-projects/genome-bottle
- NIST GIAB FAQs, including benchmark terminology and dataset use: https://www.nist.gov/programs-projects/faqs-genome-bottle
- Official benchmark data area: https://ftp-trace.ncbi.nlm.nih.gov/ReferenceSamples/giab/release/
