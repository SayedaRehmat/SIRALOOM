# SIRALOOM 20K GeneBe Experiment Status

Date: 2026-09-08

## Verified in this environment

- GeneBe current API documentation confirms the batch endpoint `POST /api-public/v1/variants` and a maximum batch size of 1,000 variants.
- 20,000 variants are deterministically planned as 20 batches × 1,000.
- Non-multiple batch sizes are covered by regression tests.
- A synthetic 20,000-record GRCh38 VCF was generated for local pipeline testing.
- Reference-aware normalization processed all 20,000 records successfully.
- No normalization changes occurred in the synthetic SNV fixture.
- No large database was downloaded.

## Current live status

A live GeneBe 20,000-variant run was **not executed** in this environment because no GeneBe account credentials/API key are available to the runtime. Do not record a live-run success until it is actually executed with the user's authorized credentials.

## Live-run command

```bash
export GENEBE_ENABLED=true
export GENEBE_EMAIL='YOUR_GENE_BE_ACCOUNT_EMAIL'
export GENEBE_API_KEY='YOUR_GENE_BE_API_KEY'

python scripts/run_20k_gene_be_experiment.py \
  --variants 20000 \
  --live \
  --output artifacts/20k-genebe-experiment/live
```

The command will execute the configured batch limit (currently 1,000), persist per-batch results, and stop with a non-zero exit code if a batch fails.

## Provider constraint

GeneBe currently documents that batch annotation is available through `POST /api-public/v1/variants` in batches of up to 1,000 variants. GeneBe also states that daily query limits are enforced and that users needing hundreds of thousands of variants per day should contact GeneBe.

Source: https://docs.genebe.net/docs/api/overview/
