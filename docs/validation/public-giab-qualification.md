# Reproducible public GIAB VCF qualification

## Purpose and boundary

The manual GitHub Actions workflow `.github/workflows/giab-public-qualification.yml` acquires NIST GIAB HG001 NISTv4.2.1 benchmark assets independently for GRCh37 and GRCh38, verifies the pinned official MD5 values, records locally calculated SHA-256 values, validates the matching compressed FASTA/FAI geometry, and executes the existing SIRALOOM VCF scale path.

The workflow deliberately uses the GIAB truth VCF as a public **input-processing benchmark**. It exercises SIRALOOM VCF validation, reference concordance, routing, reference-aware normalization, BGZF/CSI publication, indexed-query reconciliation and selected-sample iteration. It is not an independent caller comparison: the input itself is the truth set. It does not qualify a caller, WES assay, clinical interpretation, or deployed laboratory storage.

## Source pinning

The HG001 benchmark VCF/TBI/BED assets and reference source FASTAs are pinned by exact URL and official MD5 in `benchmarks/giab/public_assets.v1.json`. Benchmark assets use the GIAB S3 mirror; GRCh37 hs37d5 uses the 1000 Genomes EBI reference mirror; the exact GRCh38 GIAB-compatible reference bytes use the checksum-matched Zenodo mirror (MD5 `3a3347eae0893f96ecf495d1c39e2284`). The generic NCBI no-ALT FASTA has a different MD5 (`a08035b6a6e31780e96a34008ff21bd6`) and must not be substituted for this benchmark reference. The acquisition script has no fallback mirror and never refreshes checksums automatically. A changed upstream file fails closed. Each acquired file is retained with URL, byte size, official MD5, local SHA-256 and verification status.

NIST GIAB describes the HG001 v4.2.1 benchmark VCF and high-confidence BED for GRCh37 and GRCh38. The GRCh38 reference source is mirrored in the public Zenodo record [10.5281/zenodo.10557082](https://zenodo.org/records/10557082), whose published file checksum matches the pinned GIAB-compatible reference. Use the matching BED with the matching build for a future independent hap.py/vcfeval comparison. Do not compare across reference builds or substitute an arbitrary hg19/hg38 reference.

## Run

From GitHub Actions, select **Public GIAB VCF qualification** → **Run workflow** → choose `BOTH` to execute separate GRCh38 and GRCh37 jobs. The jobs do not share downloaded files or output directories. Each run preserves asset provenance and scale evidence as a 90-day workflow artifact.

## Evidence interpretation

- `ASSETS_ACQUIRED_AND_CHECKSUM_VERIFIED`: all pinned bytes matched official MD5; local SHA-256 was recorded.
- `RUN_COMPLETE_REVIEW_REQUIRED`: the existing SIRALOOM processing path completed its internal reconciliation checks.
- `FAILED`: the scale runner stopped at a recorded stage; inspect the failure JSON and workflow log.
- A workflow success is not a clinical or laboratory PASS. The report explicitly limits interpretation to public HG001 input processing.
- Reference FASTA/FAI geometry is checked by SIRALOOM. GZI is retained and hash-pinned as the matching BGZF random-access index; byte identity alone does not prove biological reference suitability.
- The workflow preserves reports and provenance, not the multi-gigabyte downloaded source datasets. The exact URLs and hashes permit deterministic reacquisition.

## Required follow-on

A separate query VCF produced by a declared caller is required for GIAB precision/recall/F1 benchmarking with `run_giab_concordance.py` or `run_giab_benchmark.py`. Caller, version, assay, sample identity, reference package and preapproved acceptance policy must be explicit. Public truth-set self-normalization is not a substitute for caller concordance.
