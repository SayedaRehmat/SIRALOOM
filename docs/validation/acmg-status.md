# SIRALOOM Variant — Scientific Method and Validation Status

**Status snapshot:** 2026-10-30  
**Repository revision reviewed:** `7290b151a24717862d8a26efb34bbaf0e23b3d29` (`main`)  
**Purpose:** Distinguish implemented scientific decision-support mechanisms from independently validated methods and laboratory-qualified clinical use.

> **Release boundary:** This document is not a declaration of clinical validity, diagnostic fitness, accreditation, regulatory authorization, or production readiness. Software tests establish only the behavior covered by those tests. Clinical use requires an authorized laboratory's intended-use-specific verification/validation, approved SOPs and policies, qualified resources, competent review, and applicable regulatory/accreditation controls.

## 1. Current implementation evidence

### ACMG/AMP classification and ClinGen specifications

- The repository contains a versioned ACMG/AMP 2015 baseline combination engine. Automated outputs remain proposed; the engine does not replace human review.
- The ClinGen/CSpec integration has import/snapshot code, version-aware specification retrieval, a database registry, explicit validation/activation, gene/disease-scope selection, and fail-closed behavior for missing or ambiguous applicable specifications.
- The assessment service currently declares these automated criterion evaluators: **PM2, BA1, BS1, PP3, BP4, and PVS1**. This is not a complete automated evaluator for all ACMG/AMP criteria.
- PM2, BA1, and BS1 require explicit frequency thresholds and a minimum allele-number requirement. PP3/BP4 require an explicitly configured predictor and calibrated score interval. PVS1 uses a conservative gate and is **not** a complete PVS1 decision tree.
- Unsupported criteria, unconfigured rules, ambiguous specification selection, and alternative combination methods without a registered validated engine must not be approximated by the baseline engine; they must remain review-required.
- A CSpec snapshot's successful import or structural validation is not, by itself, proof that the laboratory has scientifically validated the specification for automated use. Automation approval and clinical validation are distinct decisions.

### Population evidence

- Population observations preserve population/cohort identity and provenance. Global, ancestry-specific, exome, genome, and laboratory cohort observations must not be silently interchanged.
- The gnomAD adapter calculates AF only when AC is a non-negative integer, AN is a positive integer, and AC does not exceed AN. If AN is missing or zero, AF is not emitted. A missing population observation is not represented as AF=0.
- Nullable gnomAD GraphQL counts must remain nullable. Provider outage, an exact-variant non-match, an unavailable denominator, and a valid measured frequency are distinct states.
- PM2/BA1/BS1 evaluation must consume only observations eligible under the explicitly selected specification and configured population requirements. Missing or incomplete observations must remain indeterminate/review-required rather than being treated as evidence of absence.

### Variant normalization and benchmark

- Phase-1 scope is VCF/VCF.GZ small variants with explicit reference-build and reference-package identity. The repository's variant-class matrix states that symbolic structural variants, breakends, and other unsupported classes must be blocked rather than silently treated as analyzed.
- BCFtools normalization and the application-level variant identity are distinct from GA4GH VRS canonicalization. Any transformation policy must be pinned and validated against appropriate fixtures; do not infer scientific equivalence from a matching string key alone.
- The repository contains a GIAB HG001/GRCh38 benchmark harness and protocol. The protocol explicitly states **the benchmark has not yet been executed**. The latest recorded benchmark-runner change also says that the manifest is unconfigured, approved truth assets/query-sample attestation/acceptance policy are not supplied, and no GIAB concordance claim is made.
- A successful harness exit is not a pass/fail clinical conclusion: the runner deliberately returns `RUN_COMPLETE_REVIEW_REQUIRED`; a qualified reviewer must compare the observed metrics and discrepancies against acceptance criteria approved before the run.

## 2. Evidence status vocabulary

Use these terms in all scientific status reports:

- **IMPLEMENTED:** behavior exists in source.
- **UNIT-TESTED:** focused tests passed for the recorded source revision.
- **INTEGRATION-TESTED:** the real configured API/database/queue-worker/artifact path passed in a controlled environment.
- **BENCHMARK-RUN:** the declared benchmark was executed using recorded, hash-verified assets and pinned tools.
- **SCIENTIFICALLY-REVIEWED:** an authorized reviewer evaluated outputs/discrepancies against predeclared criteria and recorded a decision.
- **LAB-QUALIFIED/VALIDATED:** the responsible laboratory's controlled quality process approved the intended use against predefined acceptance criteria.
- **NOT RUN / BLOCKED / REQUIRES REVIEW:** use these when the required evidence, resource, policy, or authority is absent.

Do not use “validated” as a synonym for “has tests,” “passed CI,” “imported from ClinGen,” or “ran without an exception.”

## 3. Scientific gates still open

1. **Independent normalization/concordance benchmark — NOT RUN.** Configure a controlled HG001/GRCh38 manifest with exact truth VCF, confidence BED, reference FASTA, normalized query VCF, SHA-256 values, pinned BCFtools and hap.py/vcfeval versions, license/usage records, and a preapproved acceptance policy. Run and independently review discrepancies. Do not choose thresholds after viewing results.
2. **Criterion-level golden cases — PARTIAL.** Build a versioned, source-cited test corpus for every automatically executed criterion and every supported specification type. Include positive, negative, borderline, missing-evidence, conflicting-evidence, transcript-dependent, population-denominator, and unsupported-rule cases. Record expected outcomes and independent reviewer adjudication.
3. **Specification governance — PARTIAL.** For each activated ClinGen specification, preserve the exact source/version/hash, release state, gene/disease scope, structured rule mapping, validation evidence, approving role/reason, supported evaluator/executor, and applicable combination method. Verify that imported content cannot be treated as automatically executable merely because it is parseable.
4. **Predictor calibration — NOT ESTABLISHED GENERICALLY.** For PP3/BP4, identify the exact predictor/model version, transcript/context, training/validation evidence, score calibration and approved intervals. No arbitrary score or generic threshold may be converted into a clinical criterion.
5. **Phenotype and inheritance — REQUIRES METHOD-SPECIFIC EVIDENCE.** Version HPO and gene–disease resources, preserve present/absent/excluded/unknown semantics, and validate any ranking or similarity method against reviewed cases. Phenotype similarity and inheritance fit are prioritization evidence, not pathogenicity classification.
6. **End-to-end laboratory qualification — NOT ESTABLISHED.** Demonstrate a controlled, authenticated case from VCF intake through persisted evidence, proposed classification, human review, reportability, authorized sign-out, immutable report/provenance, and reanalysis. Repeat with actual organization-approved resources and durable storage; inject failures and verify replay.
7. **Deployment and quality-system evidence — NOT ESTABLISHED by source/CI alone.** The laboratory must approve intended use, SOPs, roles, QC/acceptance criteria, change control, resource qualification, backup/restore, monitoring, retention, and applicable jurisdictional requirements.

## 4. Authoritative references to pin in the implementation record

- Richards et al., ACMG/AMP sequence-variant interpretation consensus recommendation (2015): https://pubmed.ncbi.nlm.nih.gov/25741868/
- ClinGen Variant Classification Guidance (current index; page states last updated July 2025): https://www.clinicalgenome.org/tools/clingen-variant-classification-guidance/
- ClinGen Criteria Specification Registry: https://cspec.clinicalgenome.org/cspec/ui/svi/
- ISO 15189:2022, Medical laboratories — Requirements for quality and competence: https://www.iso.org/standard/76677.html
- NIST Genome in a Bottle program and benchmark resources: https://www.nist.gov/programs-projects/genome-bottle
- GA4GH Variation Representation Specification (VRS; current approved version shown by GA4GH as v2.0): https://www.ga4gh.org/product/variation-representation/
- HTS specifications (VCF/BCF): https://github.com/samtools/hts-specs

Each production analysis must snapshot the exact resource/specification release and checksum actually used. A link to a live web page is not a substitute for an immutable execution record.

## 5. Immediate engineering rule

Until the open scientific gates are closed, SIRALOOM is a **research/software decision-support implementation with partial verification**, not a clinically validated diagnostic system. Preserve evidence, fail closed on unsupported or ambiguous methods, route unvalidated conclusions to qualified human review, and report limitations plainly.
