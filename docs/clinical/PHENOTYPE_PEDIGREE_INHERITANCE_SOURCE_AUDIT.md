# Source Audit: Phenotype, Pedigree, Inheritance and Clinical PR Reconciliation

**Audit date:** 2026-11-07  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Audited main:** `226dd645d5ac4047e3478fd67b6b550af9633b55`  
**Working branch:** `feature/clinical-phenotype-pedigree-inheritance-qualification-20261107`

## 1. Scope and evidence boundary

This audit inspects the current-main source, model definitions, migrations, tests, frontend workspace, PR changed-file lists, PR diffs, comments, branch comparisons, and historical workflow runs. It is not a local execution of the current working branch. Historical CI success is not evidence that a stale PR passes against current main. No clinical/laboratory validation is claimed.

## 2. Existing architecture: preserve

### Phenotype
- `backend/app/api/v1/phenotypes.py`: governed HPO resource resolution, case-scoped phenotype intake, explicit five-state phenotype status, clinical attributes, subject-member validation, idempotency fingerprint, and active-analysis snapshot freeze.
- `backend/app/phenotype.py`: HPO identifier normalization and exact/descendant matching. It deliberately does not produce a similarity score.
- `backend/app/adapters/phenotype/hpo_obo.py` and `hpoa.py`: pinned HPO OBO resolution and disease annotation ingestion.
- `backend/app/evidence/engine.py`: provenance-bearing contextual phenotype/gene-disease/HPOA evidence; HPOA NOT/frequency context; unresolved terms and contradictions require review.
- `backend/app/domain/phenotype_evidence.py`: strips historical unvalidated phenotype overlap scores from presentation.
- `backend/app/domain/clinical_input_snapshot.py`: schema v2 snapshot of clinical intake revision, pedigree, specimens and phenotype observations; case-level NULL subject is the primary patient; family member observations remain separate.
- `frontend/components/PhenotypeIntake.tsx`: governed HPO search and structured intake; it fetches family members and attributes observations to a selected member.
- Workspace mounts phenotype intake and clinical context intake.

### Pedigree and inheritance
- `backend/app/api/v1/pedigree.py`: read pedigree, add member, add parent-child relationship, record variant-level segregation observations, and request inheritance assessment; access control, case/analysis locks, audit events, cycle checks, same-case checks and reanalysis-candidate creation exist.
- `backend/app/inheritance.py`: normalizes aliases, checks whether family genotype/affected-status observations are minimally interpretable, and deliberately returns only `INSUFFICIENT_DATA` or `REQUIRES_REVIEW`. The M10 heuristic is retired and must not be restored.
- `tests/test_m10_pedigree_inheritance.py`: protects against unvalidated compatibility/score claims, missing genotypes, and treating unaffected carriers as contradictions without penetrance context.
- `migrations/versions/0051_retire_unvalidated_inheritance_scores.py`: retires legacy unvalidated conclusions.

## 3. Confirmed source-level gaps and risks

### P0 — inheritance cannot currently calculate compatibility
1. `FamilyObservation` contains member identifier, sex, affected status, genotype and zygosity only. It does not carry pedigree edges, biological relationship type, phase, allele identity, genotype quality/callability, sample identity, ploidy, penetrance, disease mechanism, age of onset or source provenance.
2. `assess_inheritance` constructs these limited observations from manually recorded segregation rows and does not pass phase, allele_observed, relationship topology or the captured pedigree snapshot into the model assessment.
3. The VCF pipeline's sample-call partition metadata contains phase and dosage, but the inheritance endpoint does not consume it. It instead accepts independently editable GT/zygosity/phase strings, creating a source-of-truth divergence risk.
4. `assess_model` explicitly implements data sufficiency only. It is correct and safer than the retired heuristic; do not add model compatibility until the required clinical and technical contracts exist.
5. The assessment fingerprint is calculated from the limited FamilyObservation set. Since phase and pedigree edges are excluded, a change to those facts cannot invalidate an assessment fingerprint. Before real inference is implemented, fingerprint must cover every consumed fact and relevant resource/policy version.
6. Assessment model aliases collapse X-linked inheritance into one `X_LINKED` category; disease-specific X-linked dominant/recessive mechanism and PAR/ploidy policy are absent.

### P0 — pedigree/sample identity is insufficient for segregation
1. `PedigreeMember` has one nullable `specimen_id`, a free-text sex field, free-text relationship-to-proband, and affected status. There is no dedicated VCF sample-column identity mapping.
2. `Specimen` registration already accepts an optional `vcf_sample_name` and stores it in `Specimen.metadata_json`; this is an unvalidated intake hint, not an identity binding. It is not tied to a specific source artifact/analysis, does not prove that the named sample exists in that artifact, and is not linked to a pedigree member through a versioned relation. One member can reference only one specimen through `PedigreeMember.specimen_id`; longitudinal/repeat specimens and multiple assays are not represented by a normalized member-specimen-sample mapping.
3. The VCF normalization workflow already parses and persists sample-specific genotype evidence, including sample name, GT, zygosity, normalized/source genotype, phase, phase set, FORMAT values, per-ALT dosage, missing-allele count, and source-record SHA-256. It stores these calls in bounded `AnalysisPartition.metadata_json.sample_calls` records. This is useful source evidence and must be reused rather than re-parsed independently.
4. However, each analysis selects one `vcf_sample_name` from `analysis.configuration`; the parser explicitly rejects an unselected multi-sample VCF. `get_analysis_sample_calls` returns one call per canonical variant, not a member/sample-indexed family genotype matrix. There is no family-analysis aggregate joining the proband and relatives' separate sample analyses.
5. `sampled` can disagree with `specimen_id`; no invariant currently enforces consistency. The single specimen FK cannot model repeated specimens/assays for a family member.
6. Segregation input accepts genotype/zygosity/phase as free text and is not bound to the normalized partition call, source artifact SHA, selected sample name, genotype quality, or sample identity evidence. It can therefore diverge from the actual normalized call.
7. Missing genotype and no-call must remain unknown, never be coerced to 0/0/reference. Genotype calls must be tied to validated artifact, sample, caller, FORMAT fields, QC and ploidy.
8. Trio/de novo interpretation requires validated sample identity and relatedness evidence; pedigree assertions alone cannot confirm biological parentage.

### P1 — pedigree domain completeness
1. Current API creates members and parent-child edges but has no member/relationship update, supersession, or deletion workflow. It cannot correct an erroneous family structure with an auditable lifecycle.
2. `relationship_type` is free text on a directed parent-child edge. Biological/adoptive/donor/guardian/unknown relationships are not governed as separate semantics.
3. No explicit partner/mating edge exists; no formal representation of consanguineous union, degree/path, or source of the assertion is defined.
4. The API prevents cycles and duplicate parent-child pairs, but does not enforce valid biological parent count, parent/child role constraints, temporal plausibility, relationship-specific edge rules, or a complete pedigree validation report.
5. A case can have zero designated probands. Snapshot validation rejects multiple probands but does not require exactly one. This may be acceptable for an intake draft but must block any analysis path requiring a defined index patient.
6. No complete pedigree graph/editor or segregation matrix is mounted in the workspace. The phenotype component only uses the member list for attribution.

### P1 — phenotype clinical completeness
1. Phenotype states are correctly distinct; unknown/not-assessed are not negatives. This invariant must be retained.
2. HPO matching is currently exact/descendant context, not an information-content semantic similarity method or calibrated ranker.
3. HPOA NOT, frequency and evidence assertions are retained as context; no calibrated disease-specific phenotype prioritization is validated.
4. The case-level `NULL` subject convention means primary patient. The UI must make this explicit and prevent family findings being silently merged into the proband.
5. Review attestations exist in clinical intake revisions, but phenotype observation-level verification/sign-off is not yet part of the base observation model.

### P1 — segregation history and reproducibility
1. **Resolved on the current working branch (migration 0067; awaiting CI):** the original `SegregationObservation` is now an immutable version-1 root; corrections are stored in append-only `SegregationObservationRevision` rows with a version chain and canonical fingerprint. The API returns the current revision and a separate history. PostgreSQL/SQLite triggers reject UPDATE/DELETE. Manual observations remain review notes, not source-derived genotypes.
2. Every segregation observation embeds a pedigree snapshot in metadata, but the inheritance assessor does not consume it or bind its fingerprint to the assessment.
3. The clinical-input snapshot includes pedigree and phenotype context, but the inheritance assessment is a separate object and is not yet bound to disease assertion/mechanism and technical genotype evidence.
4. Corrected/retracted phenotype records must be excluded from new active interpretation while retained in historical snapshot/provenance. PR #244 implements this; it needs migration and combined-API reconciliation.

## 4. PR reconciliation ledger

### PR #247 — referral provenance and coded prior tests
- Current PR delta against audited main: three files: clinical-intake API, clinical context frontend, revision tests.
- Contribution: referral date, referring clinician/organization/service, encounter date; optional prior-test terminology system/code/display; ruled-out differential status consistency.
- Safe to port independently. Do not claim terminology validation: codes are stored as supplied and no pinned LOINC/SNOMED CT terminology resource is used.
- **Action taken on working branch:** selectively ported its three changed files:
  - `backend/app/api/v1/clinical_intake.py`
  - `frontend/components/ClinicalContextIntake.tsx`
  - `tests/test_clinical_intake_revisions.py`
- **Verification:** source port committed; the full working-branch CI is still pending.

### PR #244 — phenotype correction/retraction lifecycle
- Current PR delta against audited main: seven files: phenotype API, clinical snapshot, reproducibility, DB model, phenotype UI, one migration and amendment tests.
- Contribution: append-only supersession/retraction, required reason, original observation preservation, amendment audit, active-analysis snapshot freeze, lifecycle-aware snapshots and exclusion from new patient/family phenotype vectors.
- Historical SIRALOOM CI passed at head `a9a39fa904b3a25b9c085a56b926f4469408293f`; this is historical branch evidence only.
- Blocking integration issue: its migration is revision `0058_phenotype_observation_amendments` with down_revision `0057_clinical_intake_revisions`. Current main has the ordered migration tail `0058_artifact_upload_intents` → `0059_specimen_ploidy_evidence` → `0060_caller_ploidy_policy_revisions` → `0061_analysis_toolchain_profiles`. It must be renumbered to `0062_phenotype_observation_amendments` after `0061_analysis_toolchain_profiles` and tested on a database upgraded through current head.
- API file overlaps PR #245's phenotype export routes. Merge the lifecycle and export changes in one combined API file; do not overwrite either feature with the other's stale full file.
- Review lifecycle constraints, idempotency, concurrent amendment behavior, active-analysis freeze, snapshot schema v1/v2/v3 compatibility, digest stability and UI history before merge.
- **Action taken:** ported lifecycle API, snapshot v3, reproducibility digest behavior, phenotype amendment UI, and amendment tests. Renumbered the migration to `0062_phenotype_observation_amendments` with down_revision `0061_analysis_toolchain_profiles`. Added PostgreSQL and SQLite database triggers that reject UPDATE/DELETE of amendment events, plus migration trigger assertions. Combined the API with PR #245 export routes instead of overwriting one feature with the other.
- **Remaining verification:** run upgrade from empty database and from deployed schema, verify downgrade protection with real amendment rows, run concurrent correction/retraction tests, and test old snapshot v1/v2 replay plus new v3 digests. Full working-branch CI is pending.

### PR #245 — GA4GH Phenopackets v2 and FHIR R5 export
- Current compare against audited main shows a 10-file remaining delta: FHIR R5 adapter, Phenopackets v2 adapter, phenotype API export routes, interoperability documentation, validator script, workflow, dependency pins and tests.
- The broader PR file list also contains 32 paths due its older branch history. It includes artifact upload and VCF/reportability changes in that history; do not merge the PR branch wholesale.
- Historical PR comments include an explicit architecture review rejecting unconditional CNV/SV/MT/repeat reportability blockers and asking that unrelated upload/VCF work be split. Current-main compare must remain the source of truth for any proposed port; retain only the clinical interoperability delta.
- Historical SIRALOOM CI and external interoperability workflow passed at head `99373466996cd07b03f08cd6f4754fdfa290b65c`. This does not establish current-main compatibility.
- The PR itself acknowledges limitations: export-only, no round-trip import/reconciliation, no published FHIR StructureDefinitions/profiles, no official HL7 validator execution/receiver testing, no full FHIR Specimen resources, no consent/legal-basis workflow, and no observation-level sign-off.
- Phenopackets strict export blocks lossy states unless explicit lossy opt-in; FHIR preserves custom status extensions. Custom extensions are not yet externally governed.
- **Action taken:** selectively ported only the 10-file current-main delta: FHIR R5 and Phenopackets v2 adapters, API routes, docs, validator script, external conformance workflow, dependency pins and tests. Excluded the historical branch's unrelated upload/VCF/reportability/deployment work. Integrated with PR #244 lifecycle semantics: standards documents receive only active phenotype rows; the Phenopackets sidecar retains amendment lifecycle and replacement fingerprints.
- **Remaining verification:** run the official GA4GH CLI and HL7 validator on the combined working branch; verify exact release/checksum retrieval and report artifacts. Historical CI success is not current-branch qualification.

## 5. Reconciliation order

1. PR #247 is ported on this working branch; run all relevant backend/frontend tests and compare its changed files against current main.
2. Port PR #244 as a single atomic lifecycle feature:
   - add amendment model,
   - add migration revision 0062 after current 0061,
   - merge phenotype API lifecycle endpoints with export routes,
   - update snapshot and reproducibility semantics,
   - update UI and tests.
3. Port only PR #245's clinical export delta after lifecycle integration; exclude unrelated artifact-upload, VCF, reportability and deployment changes.
4. Run migration upgrade from empty DB and from the current deployed predecessor/current-main schema, including rollback protection when amendment rows exist.
5. Run full backend suite, PostgreSQL integration, frontend tests/build, standards validators, and security/authorization regression on the working branch.
6. Only then open/update a reviewable PR. Do not merge automatically.

## 6. Standards and scientific qualification constraints

- Phenotype ontology and HPOA resources must be organization-approved, version-pinned, checksum-verified and traceable.
- Phenopackets v2 and FHIR R5 exports must be loss-aware and validated with their actual official schemas/validators. An export that parses locally is not equivalent to receiver interoperability.
- Pedigree data should map to GA4GH Pedigree/Phenopackets semantics without inventing biological parentage or proband status.
- Genotype/segregation must use VCF sample calls tied to specimen identity, callability and QC, not manually supplied unverified GT strings for automated inference.
- Disease-specific gene-disease validity and molecular mechanism must be governed and versioned before inheritance inference.
- PP1/BS4/PP4 and PS2/PM6 are distinct ClinGen/ACMG evidence criteria, not generic inheritance model outputs.
- No phenotype or inheritance score, candidate rank or graph visualization can substitute for qualified human review and laboratory validation.

## 7. Working-branch state

- Base: current main SHA above.
- PR #247's three-file clinical-intake delta is committed selectively.
- PR #244's lifecycle implementation is ported with a new migration 0062 after current main's 0061, database-level append-only triggers, schema-v3 snapshots, reproducibility handling, UI and tests.
- PR #245's clinical interoperability delta is ported selectively. Unrelated artifact upload, VCF, reportability and deployment work was excluded.
- The phenotype API combines both PRs; standards exports exclude superseded/retracted observations while the Phenopackets sidecar preserves lifecycle history.
- A dedicated regression test covers current-vs-historical phenotype export behavior.
- **No tests have yet been executed on this combined branch.** No CI, external-validator or clinical/laboratory qualification claim is made until the new branch PR checks complete.


## 8. Combined-branch verification evidence (PR #303)

Latest fully completed validation set inspected on 2026-11-07:

- Dependency lock verification: **passed** with repository-pinned uv 0.10.0; resolved 109 packages, added `fhir-core 1.1.12`, `fhir.resources 8.3.0`, `phenopackets 2.0.2.post5`, and adjusted the protobuf resolution to 6.33.6.
- PostgreSQL integration: **passed**. Alembic applied the complete graph through `0062_phenotype_observation_amendments`; the PostgreSQL + real Celery worker-loss integration job passed.
- Frontend: **passed**. Frontend behavior tests, localization architecture guard, production build, production frontend container build, and Compose validation passed.
- External clinical interoperability: **passed** using GA4GH Phenopacket Tools 1.0.0 and HL7 FHIR Validator 7.0.3 against deterministic synthetic exports. GA4GH Phenopacket and Family validator CSVs contained no findings. FHIR validator reported **0 errors, 8 warnings, 19 informational notes**. Warnings include missing DomainResource narrative, missing Observation performer, and inability to validate the HPO code system from the validator's terminology package. SIRALOOM custom extensions are reported as unknown because their StructureDefinitions are not yet published. These are interoperability hardening items, not validator errors.
- Backend full suite: **2,278 passed, 6 failed, 49 skipped** on the combined branch. All six failures are the existing VCF validator cases listed below.
- Baseline current-main CI at `226dd645d5ac4047e3478fd67b6b550af9633b55`: **2,241 passed, the exact same 6 failed, 49 skipped**. The six identical failures are:
  - `test_vcf40_gl_is_not_defined_for_multiallelic_records`
  - four parameter cases in `test_vcf40_reserved_format_header_definitions_are_version_pinned`
  - `test_vcf45_populated_number_p_requires_gt`
- Therefore the clinical changes add 37 passing tests without introducing an additional backend failure. The backend job is still red because current main already has the six VCF failures; this branch does not change VCF validator code and those failures are kept outside this clinical PR.
- Backend packaging/container steps after the failed backend test command were skipped. They are not claimed as passed.

External validation artifact: `clinical-interop-external-validation` (run 42358331365, artifact 13568965850). The report was inspected, not just the workflow conclusion.

**Release decision:** PR #303 remains draft and must not be merged while required CI is red. It is suitable for review of the reconciled clinical changes, but not a clinical/laboratory qualification claim.
