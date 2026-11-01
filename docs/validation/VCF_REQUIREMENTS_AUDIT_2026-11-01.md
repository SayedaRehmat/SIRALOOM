# SIRALOOM VCF Stage — Requirements-to-Code Audit

**Audit date:** 2026-11-01  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Audited branch:** `main`  
**Audited commit:** `8d0c09115c0867a2189b89ba2bbb42c24f763939`  
**Scope:** VCF artifact intake through validation, specimen/sample binding, reference verification, variant routing, SNV/INDEL normalization, indexing, provenance, and recovery.  
**Product boundary:** Current executable analysis scope is SNV/INDEL. CNV, SV, mitochondrial, repeat-expansion and gVCF/reference-confidence analysis are not silently treated as small variants. BCF is not an advertised upload format.

## 1. Executive decision

**Software implementation: SUBSTANTIAL; not yet fully verified across the intended-use matrix.**  
**Laboratory qualification: NOT QUALIFIED.**  
**Clinical release: NOT AUTHORIZED by this audit.**

The repository contains substantial production-oriented controls: strict parsing, explicit sample mapping, reference-bound normalization, routing of out-of-scope classes, genotype/source lineage, index concordance, pinned toolchain attestation, durable artifact handling, and a bounded worker-loss recovery test. Parser acceptance and green CI do not prove every optional VCF feature, caller profile, WES/WGS assay, reference package, or clinical intended-use cell.

Status meanings:
- **VERIFIED:** implementation is directly exercised by automated tests or successful CI for the bounded behavior stated.
- **IMPLEMENTED:** code exists, but relevant end-to-end or adversarial evidence is incomplete.
- **PARTIAL:** some subrequirements are implemented/verified while meaningful edge cases, caller profiles or operational evidence remain open.
- **MISSING:** no sufficient implementation or evidence was located.
- **OUT OF SCOPE:** deliberately excluded from current SNV/INDEL execution; preserve and disclose the disposition.

A VERIFIED software row is not a laboratory QUALIFIED row.

## 2. Requirements-to-code status matrix

| Requirement | Status | Repository evidence | Remaining work / boundary |
|---|---|---|---|
| Upload accepted file types and reject unsupported suffixes | VERIFIED (software) | `backend/app/api/v1/artifacts.py`; `backend/app/domain/ingestion.py`; `tests/test_ingestion.py` | Execute deployed storage-provider and real large-file qualification. |
| Upload checksum, integrity and safe staging | VERIFIED (bounded software) | `backend/app/domain/artifact_integrity.py`; upload staging/idempotency; upload-intent and compensation tests | Qualify object-store corruption, interrupted transfer and restore on each lab storage backend. |
| VCFv4.0–VCFv4.5 version recognition | IMPLEMENTED | `SUPPORTED_VCF_VERSIONS` in `backend/app/domain/vcf_validation.py` | Recognition is not full conformance. VCFv4.0 is legacy; version/caller feature corpus incomplete. |
| Strict header, fixed columns, record syntax, encoding and ordering | VERIFIED (software fixtures) | `validate_vcf_strict()`; `tests/test_vcf_validation.py` | Expand malformed/compressed-stream corpus and caller-produced files. |
| Structured metadata and INFO/FORMAT Number/Type validation | PARTIAL | `_parse_field_definition()`, `_validate_declared_value()`, `_expected_cardinality()`; VCFv4.5 reserved/local-field validation | Not every metadata family or extension has full semantics. INFO Number=G without explicit ploidy context remains unresolved; caller corpus required. |
| VCFv4.4/4.5 leading GT phasing syntax | VERIFIED (software fixtures) | Version-aware GT parser; `tests/test_vcf_validation.py` | Cross-record phase-set and caller semantics not fully qualified. |
| Multisample sample identity | VERIFIED (bounded software) | `validate_specimen_sample_identity()`; `validate_analysis_input_artifact()`; analysis input tests | Prove selected identity invariant through annotation, evidence, inheritance, review and report consumers. |
| Sites-only VCF handling | VERIFIED (bounded software) | Upload metadata marks `SITE_LEVEL_ONLY`; analysis input validation requires sample-level genotype data | Sites-only data cannot be patient-specific genotype evidence. |
| GRCh37/GRCh38 selection and exact reference binding | IMPLEMENTED / PARTIAL | `reference_package.py`, `reference.py`, build checks and known-answer tests | Actual lab-approved reference packages, assembly accession provenance and full caller/build matrix need qualification. |
| FASTA/FAI package integrity | IMPLEMENTED / PARTIAL | `validate_fasta_index_consistency()`, package and contig-manifest digests | Hashes prove byte identity, not biological assembly correctness; complete FAI/GZI consistency and package qualification remain open. |
| REF concordance; no silent repair | VERIFIED (software contract) | `validate_vcf_reference_alleles()`; BCFtools `norm -f ... -c e`; no `-c s`; negative fixtures | Execute representative GRCh37/GRCh38 caller and lab negative controls. |
| Contig names, ordering, aliases and bounds | PARTIAL | Versioned contig grammar, contiguous blocks, exact reference matching, explicit `NC_012920.1` mitochondrial alias provenance | External assembly IDs/aliases are not generally mapped; qualify approved caller naming conventions. |
| SNV and short indel routing | VERIFIED (software fixtures) | `route_vcf_records()`; VCF tooling and unsupported-routing tests | Full caller-specific and truth-set concordance still required. |
| MNV representation policy | IMPLEMENTED | Sequence-allele path preserves MNV representation; no implicit atomization | Confirm intended-use golden cases and downstream interpretation contract. |
| Multiallelic splitting and genotype/source-ALT mapping | VERIFIED (bounded software) | `bcftools norm -m -any --multi-overlaps .`; `SIRALOOM_SOURCE_GT`, `SIRALOOM_ORIG`, `SIRALOOM_SOURCE`; source-child tests | Duplicate ALT, mixed wildcard/concrete ALT, repeated alleles, coordinate-shift and full caller corpus remain incomplete. |
| INFO Number=A/R and FORMAT AD/PL/GL/GP cardinality | PARTIAL | Parser cardinality tests and PRs #266–268; multiallelic normalization fixtures | Syntax/cardinality does not establish likelihood/probability calibration or all caller projection semantics. |
| VCFv4.5 local alleles (LAA/LA/LR/LG/P) | VERIFIED (software fixtures) | Local-field validation/equivalence in `vcf_validation.py`; PR #263 | Remaining caller-specific local-field combinations need representative fixtures. |
| VCFv4.5 base modification Number=M | VERIFIED (software fixture scope) | Reserved-field recognition, GT/allele-aware cardinality; source-only retention policy | Deliberately excluded from normalized SNV/INDEL child evidence; real modified-base caller corpus pending. |
| VCFv4.5 gVCF reference blocks and per-sample LEN/END | VERIFIED (software fixture scope) | `compute_vcf45_record_span()`; sample-specific block coverage; PRs #234/#252 | Validates/reroutes syntax and missingness; does not perform reference-confidence genotyping or joint calling. |
| gVCF as direct SNV/INDEL analysis | OUT OF SCOPE | Durable routing/review artifacts; unresolved records not converted to reference calls | Separate reference-confidence workflow requires explicit product/clinical governance. |
| Symbolic SV, BND, CNV, repeat expansion, mitochondrial routing | VERIFIED (bounded routing tests); OUT OF SCOPE for current analysis | `route_vcf_records()`; separate output artifacts; PR #236; VCF tool tests | Classifier corpus is not exhaustive; these records are preserved/disclosed, not analysed by current SNV/INDEL pipeline. |
| Star allele and spanning deletion handling | IMPLEMENTED / PARTIAL | Explicit routing/rejection and exclusion manifest | Complete caller-specific edge-case and reporting evidence. |
| TBI/CSI upload validation and index concordance | PARTIAL | `validate_vcf_index_concordance()`; indexed-query SHA-256 vs sequential BGZF scan; `tests/test_csi_index_integrity.py` | Expand real malformed, stale, missing, empty, truncated, partial-write, boundary and large-WGS index fixtures. |
| Deterministic normalized BGZF VCF + CSI publication | VERIFIED (software fixtures) | `normalize_vcf_with_bcftools()`; staged outputs, index validation and publication compensation | Exercise target object storage, disk-full and crash points around each publication boundary. |
| Immutable source and normalized lineage/provenance | VERIFIED (software contract) | Source SHA-256, source record/ALT mappings, tool/version/command, reference identity and normalized artifact lineage | Verify lineage across deployed downstream consumers and retained lab records. |
| Pinned BCFtools/HTSlib security baseline | VERIFIED (PR CI) | PR #274 merged as `8d0c09115c0867a2189b89ba2bbb42c24f763939`; 1.25 pins, runtime attestation and tests | Post-merge main CI run #41328160303 passed backend, PostgreSQL integration and frontend jobs. |
| Upload idempotency and duplicate retry | VERIFIED (bounded software) | Upload intent/idempotency implementation; API and PostgreSQL tests | Concurrent retries against each production storage provider and interrupted uploads need deployment testing. |
| Normalization worker-loss recovery | VERIFIED (bounded integration test) | PR #255; real PostgreSQL/Redis Celery prefork worker loss after paired normalized VCF/CSI persistence; byte/hash and lineage replay assertions | Only one stage boundary and synthetic fixture covered. |
| Whole-stage crash/replay and operational recovery | PARTIAL | Durable checkpoints, outbox, idempotency and worker-loss tests at selected boundaries | Add fault injection at every stage, DB/Redis restart, disk-full, timeout, object-store outage and concurrent retry. |
| Sex-chromosome PAR/non-PAR classification | IMPLEMENTED / PARTIAL | `sex_chromosome_regions.py`; PR #269 | Region classification is not sample karyotype/ploidy evidence. |
| Evidence-backed sample ploidy and caller policy | IMPLEMENTED / PARTIAL | `sample_ploidy_policy.py`; PRs #270–272; immutable specimen evidence and qualified caller policy registry | Populate and validate approved caller/version/assay/build policies with real lab evidence; no generic diploid inference for unresolved cases. |
| WES/WGS and caller/version/build qualification | MISSING (laboratory evidence) | Executable qualification matrix runner and manifest contract exist | No representative lab cell results/sign-offs are present in repository evidence. |
| VCF processing scale and capacity qualification | IMPLEMENTED (harness); NOT TESTED (lab workloads) | `run_vcf_scale_benchmark.py`; stage wall/CPU/RSS/throughput and hashes | Execute representative and upper-percentile WES/WGS on target worker/storage profiles against preapproved limits. |
| Independent GIAB/GA4GH small-variant concordance | IMPLEMENTED (harness); NOT TESTED (real benchmark) | `run_giab_concordance.py`; hap.py xcmp, truth/confident BED, target BED, hash provenance and TP/FN/FP metrics | Execute matched truth VCF/confident BED/reference/assay target set; inspect discrepancies and obtain laboratory review. |
| Release approval and intended-use governance | MISSING (evidence) | Qualification and release-gate documentation exists | Need approved caller matrix, acceptance criteria, executed evidence, deviations/CAPA, reviewer approval and controlled deployment record. |

## 3. Supported inputs and explicit boundaries

| Input or class | Current product behavior |
|---|---|
| Plain VCF text, VCFv4.0–4.5 | Accepted only when strict validation succeeds; version recognition does not guarantee every extension/caller feature. |
| BGZF VCF (`.vcf.gz`, `.vcf.bgz`) | Supported upload/validation path; index pairing and concordance are separate checks. |
| TBI / CSI | Paired index artifacts are validated against the primary VCF; generated normalization output uses CSI. |
| Multisample VCF | Accepted only with explicit specimen-to-sample mapping for patient-level analysis; no arbitrary first-sample selection. |
| Sites-only VCF | Preserved as site-level input; not eligible as patient genotype evidence. |
| BCF | Not advertised/accepted as a VCF-text upload. Deliberate boundary; do not parse as VCF. |
| CNV/SV/BND, mitochondrial, repeat-expansion | Preserved/routed/disclosed as outside current SNV/INDEL analysis scope. |
| gVCF/reference-confidence blocks | Validated/routed; not treated as reference genotypes and not jointly genotyped by this stage. |
| FASTQ/BAM alignment or variant calling | Outside SIRALOOM's current product responsibility; upstream caller produces the VCF. |

## 4. PR #274 security review and merge evidence

PR #274 changed BCFtools/HTSlib version references and corresponding tests/documentation. It pins BCFtools 1.25 and HTSlib 1.25 in the Conda environment, application defaults, CI runtime attestation and container checks. It does not change normalization flags or variant semantics.

- HTSlib disclosed high- and moderate-severity vulnerabilities affecting versions through 1.24 on 2026-10-27; patched releases include 1.25 and backports including 1.24.1.
- Bioconda's BCFtools 1.25 package requires HTSlib >=1.25,<1.26; explicit 1.25/1.25 pins are compatible.
- PR #274 CI run #41326887267 passed backend, PostgreSQL integration and frontend jobs.
- PR #274 merged on 2026-11-01 as `8d0c09115c0867a2189b89ba2bbb42c24f763939`.
- Post-merge main CI run #41328160303 completed successfully for backend, PostgreSQL integration and frontend jobs.

## 5. Priority-ordered remaining work

1. **Complete parser conformance corpus:** positive and negative VCFv4.0–4.5 fixtures for fixed fields, metadata, escaping, Number/Type cardinality, missing values, genotype syntax, symbolic/breakend syntax, local alleles, compression and malformed streams. Preserve version-specific rules.
2. **Complete sample/genotype semantics:** duplicate ALT and mixed wildcard/concrete ALT cases; phase/ploidy edge cases; source-to-child one-to-one reconciliation; caller-specific FORMAT behavior; selected-sample invariance through downstream consumers.
3. **Complete reference package qualification:** verify FASTA/FAI/GZI content consistency, assembly accession/build provenance, contig dictionary and known-answer REF checks for both GRCh37 and GRCh38.
4. **Complete index qualification:** real TBI/CSI fixtures for stale/corrupt/missing/empty/partial indexes, duplicate positions, contig boundaries, VCFv4.5 LEN/END spans and large WGS-scale indexes.
5. **Complete operational resilience:** fault injection at upload, validation, routing, normalization, index, publication and downstream handoff; DB/Redis restart, disk-full, timeouts, object-store failure and concurrent retries.
6. **Execute qualification matrix:** populate approved WES/WGS × caller/version × build × variant-class cells with representative lab artifacts and preapproved criteria.
7. **Execute GIAB concordance:** use matched truth VCF/confident BED/reference/assay target; retain discrepancy evidence, strata and reviewer decisions.
8. **Execute scale/capacity benchmark:** representative and upper-percentile WES/WGS on target lab infrastructure; set thresholds before run; retain hashes, memory, CPU, scratch, throughput and concurrency evidence.
9. **Complete release governance:** controlled intended use, caller policy qualification, deviations/CAPA, reviewer authorization, change control/revalidation triggers and verified deployed commit.

## 6. Release decision

The VCF stage is **substantially implemented and suitable for continued controlled engineering/qualification**, but it is **not laboratory-qualified**. No WES/WGS caller/version/build cell should be represented as clinically qualified without executed, reviewed laboratory evidence. Do not weaken the explicit SNV/INDEL product boundary by treating unsupported classes as analysed. Qualification runner statuses such as `REVIEW_REQUIRED` and `NOT_AUTOMATICALLY_QUALIFIED` are not approvals.

## 7. Evidence sources

- Code: `backend/app/domain/vcf_validation.py`, `ingestion.py`, `vcf_tools.py`, `reference_package.py`, `artifact_integrity.py`, `sample_ploidy_policy.py`, `sex_chromosome_regions.py`, `backend/app/api/v1/artifacts.py`, `backend/app/application/analysis.py`.
- Tests: `tests/test_vcf_validation.py`, `tests/test_vcf_tools.py`, `tests/test_ingestion.py`, `tests/test_csi_index_integrity.py`, `tests/test_vcf_qualification_matrix.py`, `tests/test_giab_concordance_runner.py`, `tests/integration/test_vcf_normalization_prefork_worker_loss.py`, plus upload/specimen/ploidy integration suites.
- Qualification harnesses: `scripts/validation/run_vcf_qualification_matrix.py`, `run_vcf_scale_benchmark.py`, `run_giab_concordance.py`.
- Existing ledger: `docs/VCF_STAGE1_LAB_QUALIFICATION_MATRIX.md`.
- Standards traceability: `docs/validation/VCF_STANDARDS_TRACEABILITY_2026-11-01.md`.
- Upstream advisory: https://openwall.com/lists/oss-security/2026/10/27/6
- Upstream release: https://sourceforge.net/p/samtools/mailman/samtools-announce/
- Bioconda package metadata: https://bioconda.github.io/recipes/bcftools/README.html and https://bioconda.github.io/recipes/htslib/README.html
