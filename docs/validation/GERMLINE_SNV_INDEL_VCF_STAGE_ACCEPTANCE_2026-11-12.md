# Germline SNV/indel VCF stage — scoped acceptance audit

**Audit date:** 2026-11-12  
**Audited main commit:** `47e137fa4f1009142f90eac66fc90164a75f8744`  
**Scope:** SIRALOOM's VCF-to-report intake boundary for sample-level germline SNV/indel reanalysis.  
**Decision:** **SOFTWARE VCF INTAKE/NORMALIZATION STAGE COMPLETE FOR THE DECLARED SCOPE**, with the explicit limitations below. This is not a claim of upstream caller analytical qualification or laboratory accreditation.

## 1. Scope boundary

SIRALOOM receives caller-produced VCF artifacts. This stage begins at VCF upload and ends with a validated, reference-bound, normalized, indexed, provenance-linked small-variant artifact eligible as input to downstream annotation and interpretation.

Included:
- VCF text intake, preservation, structural validation and version-aware semantics needed by the supported small-variant path.
- Sample genotype, allele-index, ploidy, missing-call and multiallelic semantics used by the analysis.
- Exact GRCh37/GRCh38 reference-package binding and REF concordance.
- Reference-aware normalization, multiallelic splitting, index generation/validation and source-to-derived allele/genotype lineage.
- Caller metadata/provenance capture and documented field-declaration compatibility for GATK HaplotypeCaller, DeepVariant and DRAGEN SNV.
- Single-sample/specimen mapping and eligibility gates before genotype-based analysis.
- Explicit fail-closed handling and preservation/routing of unsupported or unresolved inputs.

Excluded from this stage:
- FASTQ base calling, alignment and upstream variant calling.
- Clinical interpretation of CNV, SV/BND, mitochondrial or repeat-expansion variants.
- gVCF joint genotyping; gVCF/reference-confidence input is distinguished and routed, not treated as a variant-only callset.
- Assay-specific base-modification interpretation.
- Universal implementation of optional VCF features that the SNV/indel workflow does not consume.
- Laboratory analytical validation of upstream caller performance, which belongs to the laboratory's caller/assay validation programme.

## 2. Requirement-to-main implementation map

| Required VCF-stage capability | Main implementation/evidence | Status |
|---|---|---|
| Preserve immutable uploaded source and verify artifact identity | Artifact storage, SHA-256/size verification and durable validation lifecycle | PASS |
| Durable validation dispatch, retries and recovery | Artifact validation dispatch/outbox/worker and recovery tests | PASS |
| Validate paired TBI/CSI against the source record stream | Artifact validation and index validation path | PASS |
| Recognize supported VCFv4.0–4.5 declarations; reject unknown versions | `backend/app/domain/vcf_validation.py` | PASS for declared supported profile; not universal feature conformance |
| Validate VCF header, columns, records, INFO/FORMAT declarations, types and cardinalities | `backend/app/domain/vcf_validation.py` | PASS for implemented/consumed profile |
| Validate GT allele indexes, genotype syntax, ploidy/cardinality and missing alleles | Strict VCF validator and VCFv4.0/4.5 GT regression suites | PASS |
| Preserve multiallelic semantics through decomposition | BCFtools normalization path with source ALT/GT lineage | PASS |
| Bind exact reference build and sequence package | Reference-package validation, FASTA/FAI/manifest checks, contig resolution and REF concordance | PASS |
| Normalize against the selected reference and fail on REF mismatch | Pinned BCFtools normalization profile using reference-aware normalization and strict REF checking | PASS |
| Preserve original-to-normalized record and genotype lineage | Ingestion/normalization provenance and regression tests | PASS |
| Capture declared caller identity/release without trusting headers as authentication | `backend/app/domain/vcf_caller_profiles.py` | PASS |
| Check documented caller-specific field declarations and semantics | GATK HaplotypeCaller, DeepVariant and DRAGEN SNV profiles | PASS within documented profile coverage |
| Prevent caller-semantic incompatibility from entering genotype analysis | Persisted `REVIEW_REQUIRED` eligibility and analysis-input rejection | PASS (fail-closed) |
| Require sample-level genotype and correct specimen/sample mapping | Analysis-input validation | PASS |
| Prevent unsupported gVCF/SV-like records from being silently interpreted as small variants | Explicit markers, routing, unsupported/unresolved handling | PASS within declared product boundary |

## 3. Verification evidence

PR #324 (`feat(vcf): add caller-aware germline SNV/indel provenance profiles`) was merged into main as the audited commit.

The exact PR head `4e222bf13d299582f7b7e54a7f4c4cda0cb9a011` passed the reported SIRALOOM CI checks:
- backend tests;
- frontend tests and build;
- PostgreSQL/Celery integration;
- startup, compile and container checks.

The BCFtools/HTSlib source-profile matrix passed for:
- BCFtools 1.22.3 / HTSlib 1.22.4;
- BCFtools 1.23.3 / HTSlib 1.23.3;
- BCFtools 1.24.1 / HTSlib 1.24.1.

The merged change includes regression coverage for caller identity/release, unknown and conflicting caller metadata, required GT, GVCF routing, caller declaration mismatches, caller-field preservation, DRAGEN multiallelic normalization lineage, VCFv4.0 GT/reserved fields and VCFv4.5 GT/ploidy/Number=P behavior.

The Vercel status for the merged main commit is reported as successful. No separate new test run is claimed by this documentation-only acceptance record.

## 4. Explicit safe limitations (not blockers for this stage)

1. **Header provenance is not authenticated run provenance.** Caller name/version extracted from VCF headers remain declarations. SIRALOOM does not claim cryptographic proof of the executable, mode, model, assay or run configuration.
2. **Caller analytical performance is not established by VCF parsing.** GIAB sensitivity/precision/genotype-concordance validation is required before a laboratory claims a specific caller-release/assay combination is clinically qualified. This is upstream caller/assay qualification, not a missing VCF parser operation in this VCF-to-report product.
3. **DRAGEN FORMAT/GP deviation remains fail-closed.** The documented DRAGEN Phred-scale GP values are not silently interpreted as VCF posterior probabilities. Out-of-range values are rejected; the compatibility metadata records the deviation. No unauthenticated header can authorize a reserved-field semantic override.
4. **Caller review-required artifacts remain blocked.** A structural VALID status does not imply analysis eligibility. Such an artifact cannot start genotype-based analysis; a conformant replacement artifact or separately governed disposition is required.
5. **gVCF is not joint-genotyped here.** It is identified and routed. The current product does not claim reference-confidence joint genotyping.
6. **Unsupported variant classes are not clinically interpreted.** They must remain preserved and visibly routed/unresolved; this stage's completion does not extend to CNV, SV, mitochondrial or repeat-expansion analysis.

## 5. What is deliberately not a release gate

The following work must not be used to hold the scoped germline SNV/indel VCF intake stage open:
- byte-pinning the historical VCFv4.0 source if the approved product claim is limited to the implemented VCFv4.0 compatibility behavior and its tested input profile;
- adjudicating every VCFv4.0–4.5 optional or informative statement unrelated to accepted SNV/indel records or fields consumed by SIRALOOM;
- complete BND derivative-chromosome reconstruction;
- base-modification assay/strandedness qualification;
- CNV/SV/repeat/mitochondrial interpretation;
- VRS identifier generation;
- analytical qualification of every possible caller or every release of a caller.

Any new VCF feature may be added only when a declared supported caller/input profile requires it for the SNV/indel path. Its exact semantics, tests and routing behavior must be added with that feature.

## 6. Acceptance decision

**The SIRALOOM software VCF intake and normalization stage is accepted as complete for its declared germline SNV/indel VCF-to-report scope on main commit `47e137fa4f1009142f90eac66fc90164a75f8744`.**

This acceptance means the in-scope VCF intake, validation, reference binding, normalization, provenance and analysis-eligibility controls are implemented and covered by the reported software verification.

It does **not** mean:
- upstream caller analytical performance has been validated by a clinical laboratory;
- every caller/release/assay combination is qualified;
- gVCF joint genotyping or non-SNV/indel variant interpretation is supported;
- every optional feature of VCFv4.0–4.5 is implemented.

The next pipeline stage may consume the validated normalized SNV/indel artifact under these boundaries. The VCF stage should be reopened only for a demonstrated defect in this accepted scope or a newly declared supported caller/input requirement.
