# Reproducible public GIAB HG001 input-processing benchmark

## Scope and scientific boundary

This workflow acquires the public NIST GIAB HG001 / NA12878 NISTv4.2.1 benchmark VCF, TBI, high-confidence BED, and a pinned matching reference source independently for GRCh37 and GRCh38. It verifies upstream MD5 values, calculates SHA-256 for acquired and derived assets, creates a BGZF reference with paired FAI/GZI, and runs SIRALOOM's existing validation, reference-concordance, routing, reference-aware normalization, BGZF/CSI publication, indexed-query reconciliation, and selected-sample iteration.

The original GIAB VCF is the truth set and is **not** a caller-produced query VCF. This workflow is therefore an input-processing and reproducibility exercise, not GIAB precision/recall/F1 concordance, caller qualification, clinical validation, or laboratory qualification.

## Orphan spanning-deletion records

The unmodified GIAB VCF is validated first. Its exact result is retained as `raw-validation.json`; a rejection is not relabelled as acceptance. To exercise independent supported SNV/INDEL records without changing allele semantics, the benchmark derivative excludes the **entire source record** whenever any ALT allele is `*`. The original line, record ordinal, line number, allele strings, FORMAT values, genotype, and source-record SHA-256 are preserved in a JSONL quarantine sidecar. No ALT allele is stripped and no genotype is remapped. The derivative is explicitly not the complete GIAB truth set and must not be used for caller concordance.

## Pinned assets

Exact source URLs and official MD5 values are stored in `benchmarks/giab/public_assets.v1.json`. The workflow does not use moving `latest` URLs, does not silently substitute reference assemblies, and does not refresh checksums automatically. Any upstream byte change fails closed. Local SHA-256 values and sizes are captured in the per-build provenance.

## Execute

Open GitHub Actions → **GIAB HG001 reproducible input-processing benchmark**. On a pull request touching the workflow or benchmark code, both assemblies run independently. Manual dispatch currently runs both GRCh37 and GRCh38 as separate matrix jobs; it does not expose a single-build selector. Each job has isolated input/output paths and uploads a 90-day artifact.

## Evidence

- `asset-provenance.json`: source URLs, MD5 verification, SHA-256, sizes, reference FASTA/FAI/GZI hashes and contig count.
- `raw-validation.json`: validation outcome for the unchanged truth VCF.
- `derivative-provenance.json`: source/derivative hashes, counts and whole-record exclusion policy.
- `quarantined-spanning-deletion-records.jsonl`: exact source records excluded from the processing derivative.
- `scale/vcf-scale-benchmark.json`: completed production processing path and stage metrics.
- `scale/vcf-scale-benchmark.failure.json`: failed stage and bounded diagnostics if execution does not complete.
- `run-provenance.json`: repository commit, workflow run/attempt and evidence index.

A `RUN_COMPLETE_REVIEW_REQUIRED` status is an execution result, not a laboratory PASS. Acceptance thresholds must be predefined by the laboratory and assessed against an independently generated query callset for a true GIAB concordance benchmark.
