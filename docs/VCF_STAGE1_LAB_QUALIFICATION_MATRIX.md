# SIRALOOM Stage 1 — VCF/BCF/gVCF Laboratory Qualification Matrix

**Scope:** Genomic artifact intake → strict VCF/BCF validation → reference verification → variant routing → reference-aware normalization → sorting/indexing → source/child reconciliation.

**Initial assessment baseline:** `main` at `dea24dbe15cfcf050df129776ade3034b577e934` (2026-11-01), including the merged VCFv4.5 sample-specific reference-block routing fix and laboratory scale-benchmark implementation. This branch's final review also accounts for subsequent `main` commits through `2f22d98c5b73d4fd3f8fd569ed9766d79da2d9c8`, including PR #255's production-normalizer/paired-CSI worker-loss recovery integration test, PR #256's audit refresh, and PR #257's benchmark output-directory contract clarification.

**Important:** this document is a qualification ledger, not a declaration of clinical validation. A repository implementation/test result is not equivalent to an analytical validation result on representative laboratory material. ISO 15189:2022 establishes requirements for quality and competence in medical laboratories; CLSI MM09 (3rd ed., 2023) provides lifecycle guidance for designing, validating, and implementing sequencing-based clinical tests. Those standards require laboratory-specific evidence and do not permit software unit tests alone to establish clinical intended-use performance.

## 1. Qualification status vocabulary

| Status | Meaning |
|---|---|
| IMPLEMENTED | Current `main` contains an explicit implementation for the requirement. |
| AUTOMATED | A focused automated test/benchmark exercises the requirement. |
| QUALIFICATION-READY | The repository contains the controls/runbook needed to execute the laboratory qualification, but the required laboratory evidence has not been produced. |
| QUALIFIED | Representative laboratory evidence has been executed, reviewed, accepted against pre-approved criteria, and retained with provenance. |
| PARTIAL | Some dimensions are implemented/tested but important dimensions remain unverified. |
| UNSUPPORTED | The input is intentionally outside the current Phase-1 analysis scope and must fail visibly. |
| NOT-EVIDENCED | The repository cannot support a qualification claim yet. |

A cell is **not QUALIFIED** merely because it is IMPLEMENTED or AUTOMATED.

## 2. Current release conclusion

### Stage-1 implementation

**Strong / substantially implemented.** The current code contains strict VCF validation, VCFv4.5-aware semantics, reference/index controls, explicit routing, BCFtools-backed normalization, source/child reconciliation, durable failure/recovery controls, and a privacy-conscious scale benchmark.

### Stage-1 laboratory qualification

**NOT COMPLETE.** No repository evidence currently establishes the complete WES/WGS × caller/version × build × variant-class analytical qualification matrix. The current benchmark commit deliberately records results as review-required and explicitly does not claim clinical validation or WES/WGS qualification.

### Clinical release

**BLOCKED.** The existing release evidence correctly distinguishes engineering evidence from live laboratory and clinical validation. The live runbook itself states that it validates deployed software, not a clinical assay.

## 3. Format and artifact matrix

| Domain | Input / condition | Current implementation evidence | Current qualification status | Required laboratory evidence |
|---|---|---|---|---|
| VCF | VCFv4.0 | Validator allowlist includes v4.0 | IMPLEMENTED / NOT-EVIDENCED | Representative fixture + laboratory acceptance test if v4.0 is within intended use |
| VCF | VCFv4.1 | Validator allowlist includes v4.1 | IMPLEMENTED / NOT-EVIDENCED | Representative fixture + laboratory acceptance test if within intended use |
| VCF | VCFv4.2 | Validator allowlist includes v4.2 | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | Representative production caller output and concordance/round-trip evidence |
| VCF | VCFv4.3 | Validator allowlist includes v4.3 | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | Representative production caller output and concordance/round-trip evidence |
| VCF | VCFv4.4 | Current validator supports the version | IMPLEMENTED / NOT-EVIDENCED | Version-specific conformance fixtures and representative caller output |
| VCF | VCFv4.5 | Current validator supports v4.5-specific semantics | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | VCFv4.5 production fixtures including mixed/sample-specific reference blocks |
| BCF | BCF2 produced/consumed by pinned HTSlib/BCFtools | Pipeline uses pinned BCFtools/HTSlib execution path | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | Representative BCF from each approved caller/version and exact output reconciliation |
| Compression | bgzip-compressed VCF | Intake/streaming path supports compressed VCF | IMPLEMENTED / NOT-EVIDENCED | Compressed production artifacts + integrity/index validation |
| Index | CSI | Current workflow creates/validates CSI and reconciles it with the VCF | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | Production index integrity and random-access qualification |
| Index | TBI | Index validation distinguishes index type/compatibility | IMPLEMENTED / NOT-EVIDENCED | Production artifacts using approved index policy |
| Integrity | Input SHA-256 | Artifact integrity is persisted | IMPLEMENTED / AUTOMATED | Independent laboratory record linking input artifact to run |
| Reference | GRCh37 | Reference package controls exist | IMPLEMENTED / NOT-EVIDENCED | Approved GRCh37 FASTA/FAI package + representative run |
| Reference | GRCh38 | Reference package controls exist | IMPLEMENTED / AUTOMATED / NOT-EVIDENCED | Approved GRCh38 FASTA/FAI package + representative run |
| Reference | REF allele mismatch | Fail-closed reference-aware checks | IMPLEMENTED / AUTOMATED | Negative-control samples/fixtures demonstrating no silent repair |
| Reference | Contig mismatch | Exact contig/resource governance exists | IMPLEMENTED / AUTOMATED | Production build/contig mismatch negative controls |

## 4. Variant routing matrix

| Variant/input class | Intended Phase-1 behavior | Current evidence | Status |
|---|---|---|---|
| SNV | Validate → normalize → sort/index → annotation boundary | Current VCF tooling + tests | AUTOMATED / NOT-EVIDENCED |
| Short insertion | Validate → reference-aware normalization | Current BCFtools normalization path | AUTOMATED / NOT-EVIDENCED |
| Short deletion | Validate → reference-aware normalization | Current BCFtools normalization path | AUTOMATED / NOT-EVIDENCED |
| Multiallelic SNV/indel | Validate → `bcftools norm -m -any` with cardinality remapping | Existing genotype-bearing fixtures and BCFtools path | AUTOMATED / NOT-EVIDENCED |
| MNV | Preserve MNV representation unless approved policy requires decomposition | Current classifier/normalizer policy | IMPLEMENTED / NOT-EVIDENCED |
| Phased GT | Preserve phase separators and relevant PS context through normalization | Existing bounded fixture | AUTOMATED / PARTIAL |
| Multi-sample VCF | Preserve sample order and per-sample calls | Existing fixtures/routing | AUTOMATED / NOT-EVIDENCED |
| Missing genotype | Preserve missingness; never synthesize 0/0 | Current router and VCFv4.5 block-aware logic | AUTOMATED / NOT-EVIDENCED |
| VCFv4.5 sample-specific reference block | Missing GT permitted only when covered by validated preceding block | PR #252 merged to `main` with dedicated regression fixture | AUTOMATED / NOT-EVIDENCED |
| Unexplained missing genotype | Route to unresolved review artifact | Current router | AUTOMATED / NOT-EVIDENCED |
| `<NON_REF>` / gVCF reference block | Preserve/reroute; do not treat as ordinary variant analysis | Current worker/router boundary | AUTOMATED / UNSUPPORTED FOR ORDINARY PHASE-1 ANALYSIS |
| Symbolic `<DEL>` | Explicit structural routing / rejection | Current structural classifier | AUTOMATED / UNSUPPORTED |
| Symbolic `<DUP>` | Explicit structural routing / rejection | Current structural classifier | IMPLEMENTED / UNSUPPORTED |
| Symbolic `<INS>` | Explicit structural routing / rejection | Current structural classifier | IMPLEMENTED / UNSUPPORTED |
| Breakend `BND` | Explicit structural routing / rejection | Current structural classifier | IMPLEMENTED / UNSUPPORTED |
| Star allele `*` | Explicit rejection rather than silent downstream analysis | Current structural classifier | AUTOMATED / UNSUPPORTED |
| CNV/SV | Do not claim Phase-1 small-variant normalization | Current routing boundary | UNSUPPORTED |
| gVCF as direct analysis input | Must not silently become ordinary VCF | Current durable blocked/review path | UNSUPPORTED |

## 5. Genotype / FORMAT qualification matrix

| Feature | Required behavior | Current evidence | Qualification |
|---|---|---|---|
| GT `0/0` | Preserve reference genotype semantics | Unit/routing coverage | AUTOMATED / NOT-EVIDENCED |
| GT `0/1` | Preserve heterozygous call | Unit/routing coverage | AUTOMATED / NOT-EVIDENCED |
| GT `1/1` | Preserve homozygous-alt call | Unit/routing coverage | AUTOMATED / NOT-EVIDENCED |
| GT `1/2` | Correct multiallelic splitting/remapping | BCFtools fixture | AUTOMATED / NOT-EVIDENCED |
| Phased `1\|2` | Preserve phase separator | Existing fixture | AUTOMATED / NOT-EVIDENCED |
| Phased `2\|0` | Preserve phase information | Existing fixture | AUTOMATED / NOT-EVIDENCED |
| `./.` | Preserve explicit missingness | Router tests | AUTOMATED / NOT-EVIDENCED |
| `.` in VCFv4.5 block context | Preserve missingness, do not synthesize 0/0 | PR #252 regression | AUTOMATED / NOT-EVIDENCED |
| INFO Number=A | Correct ALT-specific remapping | Existing multiallelic fixture | AUTOMATED / PARTIAL |
| FORMAT AD Number=R | Correct allele cardinality after splitting | Existing fixture | AUTOMATED / PARTIAL |
| FORMAT PL Number=G | Validate genotype-likelihood cardinality from each sample GT ploidy (haploid, diploid, triploid, tetraploid) | `tests/test_vcf_validation.py::test_format_number_g_cardinality_uses_sample_ploidy`; automated cardinality only | AUTOMATED / PARTIAL |
| FORMAT GL Number=G | Validate genotype-likelihood cardinality from each sample GT ploidy | Same parameterized regression; values are syntax/cardinality fixtures, not likelihood calibration | AUTOMATED / PARTIAL |
| FORMAT GP Number=G | Validate genotype-probability cardinality from each sample GT ploidy | Same parameterized regression; does not establish normalization or probability semantics | AUTOMATED / PARTIAL |
| PS | Preserve phase-set identifier | Existing fixture | AUTOMATED / PARTIAL |
| Haploid calls | Validate generic Number=G cardinality; additionally qualify chromosome/caller-specific haploid semantics | Synthetic haploid GT cardinality regression; no representative assay/caller evidence | AUTOMATED / NOT-EVIDENCED |
| Sex-chromosome ploidy | Must be explicitly qualified for PAR/non-PAR, karyotype, build and caller context | No complete qualification evidence identified | NOT-EVIDENCED |
| Polyploid calls | Validate generic Number=G cardinality; additionally qualify caller and biological use if supported | Synthetic triploid/tetraploid GT cardinality regression; no representative assay/caller evidence | AUTOMATED / NOT-EVIDENCED |

## 6. WES / WGS / caller matrix

The following matrix is the critical laboratory boundary. The repository must not mark a cell QUALIFIED without a real representative artifact, known provenance, executed run, expected-result definition, observed metrics, reviewer sign-off, and retained evidence.

| Assay | Caller | Caller version | Build | Required status now |
|---|---|---|---|---|
| WES | Laboratory-approved caller | Exact installed version | GRCh37 | NOT-EVIDENCED until laboratory run |
| WES | Laboratory-approved caller | Exact installed version | GRCh38 | NOT-EVIDENCED until laboratory run |
| WGS | Laboratory-approved caller | Exact installed version | GRCh37 | NOT-EVIDENCED until laboratory run |
| WGS | Laboratory-approved caller | Exact installed version | GRCh38 | NOT-EVIDENCED until laboratory run |
| WES | Every additional supported caller | Exact version | Each supported build | NOT-EVIDENCED |
| WGS | Every additional supported caller | Exact version | Each supported build | NOT-EVIDENCED |

**Reason:** a VCF parser/normalizer can be format-correct while still encountering caller-specific conventions, allele representations, genotype tags, contigs, symbolic records, phase semantics, and filtering policies that have not been qualified for the laboratory's intended use.

## 7. Reference-aware normalization qualification

| Control | Expected acceptance criterion | Current repository evidence | Laboratory qualification |
|---|---|---|---|
| Reference FASTA exists | Required resource exists and is consumable | Reference package domain + workflow controls | NOT-EVIDENCED |
| FAI exists | Index present and bound to exact FASTA | Reference package controls | NOT-EVIDENCED |
| FASTA SHA-256 | Persisted and reproducible | Resource provenance | NOT-EVIDENCED |
| Contig manifest | Exact build/contig policy | Reference package controls | NOT-EVIDENCED |
| REF validation | Mismatch fails closed | Automated tests | NOT-EVIDENCED |
| Left normalization | `bcftools norm -f <reference> -c e` behavior | Current production normalization path | NOT-EVIDENCED |
| Multiallelic split | `-m -any` output reconciliation | Automated fixture | NOT-EVIDENCED |
| Sorting | Deterministic sorted output | Current tool path | NOT-EVIDENCED |
| CSI indexing | Deterministic index creation and validation | Current tool path | NOT-EVIDENCED |
| No silent REF correction | No `-c s` repair policy | Current scientific policy | NOT-EVIDENCED |
| Output provenance | Tool/version/command/reference/output hashes retained | Current provenance architecture | NOT-EVIDENCED |

## 8. Failure and recovery qualification

| Failure | Current engineering evidence | Laboratory qualification requirement | Status |
|---|---|---|---|
| Malformed VCF | Strict validator tests | Production negative-control run | AUTOMATED / NOT-EVIDENCED |
| Unsupported VCF feature | Typed visible failure/review route | Confirm user-facing and report-facing behavior in deployment | AUTOMATED / NOT-EVIDENCED |
| REF mismatch | Fail closed | Production negative control | AUTOMATED / NOT-EVIDENCED |
| Missing reference | Resource gate | Production deployment test | AUTOMATED / NOT-EVIDENCED |
| Invalid index | Index validation | Production negative control | AUTOMATED / NOT-EVIDENCED |
| Worker interruption during normalization | Durable workflow/recovery architecture | PR #255: PostgreSQL/Redis Celery prefork worker-loss integration test executes the production normalizer, persists paired normalized VCF/CSI, redelivers/replays, and verifies deterministic bytes, index queries, artifact identity, and source-child reconciliation on a small synthetic fixture | AUTOMATED / PARTIAL |
| Scratch-volume exhaustion | Capacity controls exist | Measured failure/recovery test on target host | NOT-EVIDENCED |
| Object-storage failure | Durable artifact architecture | Controlled target-storage failure test | NOT-EVIDENCED |
| Database restart | CI integration coverage | Deployment recovery test | PARTIAL |
| Redis/queue restart | CI/recovery coverage | Deployment recovery test | PARTIAL |
| Duplicate retry | Idempotency controls | Repeated production-like retry test | PARTIAL |
| Cross-tenant artifact access | Authorization tests | Two-lab deployed isolation test | NOT-EVIDENCED |

## 9. Scale / performance qualification

The merged benchmark records stage wall time, CPU, throughput, process/child memory, input/reference hashes and counts. The executable Stage-1 matrix runner added in this branch orchestrates that benchmark across predeclared WES/WGS × caller/version × build cells and evaluates preapproved criteria. This is useful evidence-generation infrastructure, but it is not by itself an acceptance result.

Required workload classes:

1. small VCF — parser/routing correctness;
2. representative WES VCF — ordinary production workload;
3. upper-percentile WES VCF — capacity boundary;
4. representative WGS VCF — ordinary production workload;
5. upper-percentile WGS VCF — capacity boundary;
6. multiallelic/indel-rich workload;
7. compressed VCF + index;
8. BCF workload where BCF is in intended use;
9. gVCF workload only for explicitly supported upstream/routing behavior;
10. failure/retry workload.

For each workload retain:

- exact input SHA-256;
- exact reference FASTA/FAI identity and SHA-256;
- exact BCFtools/HTSlib version;
- exact command/arguments;
- host/container identity;
- CPU and memory allocation;
- stage start/end timestamps;
- CPU time;
- peak process and child memory;
- record/ALT counts;
- normalized output SHA-256;
- CSI SHA-256;
- source/child reconciliation counts;
- failure/retry state if applicable;
- reviewer and acceptance decision.

**Current status:** QUALIFICATION-READY, not QUALIFIED.

## 10. Analytical concordance / truth-set qualification

A laboratory qualification package must include independent truth/reference material appropriate to the intended assay and variant class. NIST GIAB provides benchmark VCF/BED resources for GRCh37 and GRCh38 and describes their use for benchmarking/validation; it also notes that targeted/exome applications should subset benchmarks to the regions of interest and calculate appropriate confidence intervals because difficult variants are unevenly represented. citeturn135092search1turn135092search4

### Minimum small-variant benchmark design

| Dimension | Required evidence |
|---|---|
| SNV | Precision/recall or equivalent concordance against an appropriate benchmark region |
| Indel | Precision/recall against appropriate benchmark region |
| Difficult regions | Stratified performance where benchmark resources provide stratification |
| Exome | Truth benchmark restricted to captured/targeted regions |
| Genome | Whole-genome high-confidence regions plus stratification |
| Sex chromosomes | Explicit ploidy-aware benchmark if included in intended use |
| MNV/complex alleles | Golden fixtures and explicit representation policy |
| Multiallelic | Truth-aware comparison after normalization/splitting |
| Phasing | Separate phase-set semantics test if phasing is used downstream |
| Unsupported SV/CNV | Negative evidence showing visible rejection, not false small-variant analysis |

The repository currently does **not** contain sufficient executed independent concordance evidence to mark this gate QUALIFIED.

## 11. Laboratory quality-system mapping

ISO 15189:2022 is the current published edition and specifies requirements for quality and competence in medical laboratories. citeturn135092search0 CLSI MM09, 3rd edition, provides step-by-step recommendations for design, validation, implementation, reporting, and continual quality management of sequencing-based tests. citeturn135092search3

For SIRALOOM, Stage 1 therefore needs retained controlled evidence for:

- intended use and scope;
- supported input/artifact classes;
- software/tool versions;
- reference resources and identity;
- validation protocol;
- acceptance criteria defined before testing;
- representative positive/negative/challenging materials;
- analytical performance results;
- limitations and exclusions;
- deviations/failures and corrective actions;
- reviewer/approver identity and date;
- change control and revalidation triggers;
- audit trail and immutable result provenance.

## 12. Stage-1 sign-off rule

Stage 1 may be marked **LABORATORY QUALIFIED** only when all applicable intended-use cells satisfy all of the following:

```text
implementation present
        AND
automated regression evidence green
        AND
representative laboratory material executed
        AND
reference/tool identity recorded
        AND
expected result / acceptance criteria pre-defined
        AND
analytical concordance/performance demonstrated where applicable
        AND
negative/failure controls demonstrated
        AND
recovery/idempotency demonstrated for operational failures
        AND
limitations documented
        AND
independent laboratory review/approval recorded
```

A failed or unevaluated cell remains **NOT-EVIDENCED**, **PARTIAL**, or **UNSUPPORTED**; it must never be silently promoted to qualified.

## 13. Current decision

**Stage 1 software implementation:** PASS for continued research/development.

**Stage 1 laboratory qualification:** BLOCKED pending execution and review of the applicable WES/WGS/caller/version/build/variant-class evidence matrix and independent concordance evidence.

**Clinical use:** NOT QUALIFIED.

This conclusion is intentionally conservative and matches the current repository's own live-validation and release-gate policy: deployed-software validation is distinct from clinical-assay validation, and engineering/CI results do not establish clinical performance.

## 12. Independent GIAB / GA4GH concordance execution (added 2026-11-01)

The Stage-1 scale benchmark measures SIRALOOM's intake/normalization performance; it does **not** measure caller analytical concordance. These are separate evidence streams. The new `scripts/validation/run_giab_concordance.py` executes an independent truth-versus-query comparison with Illumina hap.py and retains TP/FN/FP counts for SNP and INDEL, separately for ALL and PASS filter strata.

### Benchmark design

- Use a GIAB truth VCF **and its matching confident-region BED** for the exact reference assembly. The truth VCF, BED, query VCF, FASTA, FAI, optional assay target BED, and optional stratification TSV are SHA-256 recorded and rechecked after execution.
- Use a sample-specific query VCF containing exactly one sample column. Do not let a multi-sample VCF silently select an arbitrary sample; create an authorized sample-specific derivative upstream and retain its derivation/provenance under the laboratory's controlled process.
- The FASTA and FAI must be the exact approved reference pair for the declared GRCh37/GRCh38 build. The runner does not perform reference conversion, contig renaming, or reference substitution.
- WES and PANEL runs require the assay target BED and use hap.py `-T`; the GIAB confident BED is separately supplied with `-f`. The target BED must represent the validated capture design/target definition for the exact assay version.
- WGS runs use the confident BED without an exome target restriction unless the predeclared intended-use design explicitly defines one.
- hap.py's `xcmp` engine is the default because it performs haplotype-level matching and supports genotype/allele mismatch accounting. `vcfeval` is selectable only when the laboratory has installed and qualified the compatible RTG-Tools integration. Do not compare results from different engines as if they were identical methods.
- Optional GA4GH stratification TSVs are passed to hap.py and the generated `.extended.csv` is retained and hashed. Stratification resources must be assembly-matched and versioned.
- ALL and PASS results are retained separately. Do not use `--pass-only` as a silent default or discard filtered-call performance.

### Metrics and interpretation

For each SNP/INDEL × ALL/PASS stratum the runner records:

- Truth TP = hap.py `TRUTH.TP`; query TP = hap.py `QUERY.TP`;
- FN = hap.py `TRUTH.FN`; FP = hap.py `QUERY.FP`;
- recall = `TRUTH.TP / (TRUTH.TP + TRUTH.FN)`;
- precision = `QUERY.TP / (QUERY.TP + QUERY.FP)`;
- F1 = harmonic mean of precision and recall;
- descriptive 95% Wilson intervals for precision and recall.

Zero denominators remain `null`; they are not reported as 0% or 100%. The report includes raw counts so the laboratory can independently recalculate metrics. The Wilson intervals are descriptive binomial intervals; they do not correct for dependence between variants or replace a laboratory's preapproved statistical analysis plan. For exome/panel assays, confidence intervals and the limited representation of difficult variants in benchmark exons are especially important.

### GIAB version policy

Select a benchmark by **sample, release, assembly, and confident-region BED as a matched set**, not by filename alone. NIST currently lists v4.2.1 small-variant benchmarks for GRCh37 and GRCh38 across the GIAB samples, while noting that HG002 has a newer v5.0q benchmark based on a T2T-HG002 assembly. v5.0q must not be substituted into a GRCh37/GRCh38 run unless the laboratory's reference assembly and benchmark package are explicitly compatible. For a GRCh37/GRCh38 Phase-1 matrix, use a matching GIAB release/assembly pair and record the exact release and checksums; where HG002 v4.2.1 is used, document that NIST identifies v5.0q as its newer HG002 benchmark for the T2T context.

### Execution

```bash
python scripts/validation/run_giab_concordance.py \
  --truth-vcf /controlled/giab/HG002.truth.vcf.gz \
  --query-vcf /controlled/specimen/sample-specific.query.vcf.gz \
  --confident-bed /controlled/giab/HG002.confident.bed.gz \
  --reference-fasta /controlled/reference/GRCh38.fa \
  --reference-build GRCh38 \
  --assay WES \
  --target-regions /controlled/assay/capture-design-v3.bed \
  --caller approved-caller \
  --caller-version 4.2.1 \
  --truth-set-id GIAB-HG002-GRCh38 \
  --truth-set-version 4.2.1 \
  --acceptance-policy-id LAB-APPROVED-SNV-INDEL-001 \
  --engine xcmp \
  --threads 8 \
  --output-dir /controlled/evidence/HG002-WES-GRCh38-run-001
```

For WGS, omit `--target-regions`. Optional `--stratification-tsv` accepts the hap.py/GA4GH region-name-to-BED TSV. Install and validate hap.py separately; the runner records its runtime version and never installs or downloads benchmark data implicitly.

### Evidence and acceptance boundary

The private run directory contains `comparison.summary.csv`, optional `comparison.extended.csv`, `hap.py.log`, and `giab-concordance.json`. The JSON records input hashes, runtime version, engine, truth-set identifier/release, preapproved acceptance-policy identifier, intended-use cell, counts, derived metrics, and confidence intervals. The tool-generated runinfo JSON is required and hashed; symbolic SV/BND/spanning-deletion alleles are rejected by this small-variant-only runner. The run status remains `CONCORDANCE_RUN_COMPLETE_REVIEW_REQUIRED`; it is never promoted automatically to QUALIFIED. A reviewer must compare results with criteria approved before the run, assess benchmark limitations and variant classes, and retain the signed decision under the laboratory quality system.

This benchmark assesses small-variant concordance **within the benchmark's confident regions and any declared target regions only**. It does not establish performance outside those regions, validate structural variants/CNVs, validate phenotype interpretation or ACMG classification, or authorize clinical use.

### Research basis

- NIST Genome in a Bottle benchmark resources and current release notes: https://www.nist.gov/programs-projects/genome-bottle
- NIST GIAB FAQ, including exome/targeted-region limitations and recommendation to calculate confidence intervals: https://www.nist.gov/programs-projects/faqs-genome-bottle
- GA4GH Benchmarking Team tools and reference implementations: https://github.com/ga4gh/benchmarking-tools
- Zook et al., *Best practices for benchmarking germline small-variant calls in human genomes*, Nature Biotechnology (2019): https://doi.org/10.1038/s41587-019-0054-x
- Illumina hap.py manual: https://github.com/Illumina/hap.py/blob/master/doc/happy.md
- CLSI MM09, 3rd edition (2023), sequencing-based clinical test design, validation, reporting and quality management: https://clsi.org/shop/standards/mm09/

The exact controlled standard text remains subject to the laboratory's licensed copy and quality-system interpretation; this repository mapping is not a substitute for purchasing, reviewing, and implementing the standard.
