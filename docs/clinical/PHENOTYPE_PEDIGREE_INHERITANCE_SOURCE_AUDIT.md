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
2. `assess_inheritance` constructs these limited observations from segregation rows and does not pass phase, allele_observed, relationship topology or the captured pedigree snapshot into the model assessment.
3. `assess_model` explicitly implements data sufficiency only. It is correct and safer than the retired heuristic; do not add model compatibility until the required clinical and technical contracts exist.
4. The assessment fingerprint is calculated from the limited FamilyObservation set. Since phase and pedigree edges are excluded, a change to those facts cannot invalidate an assessment fingerprint. Before real inference is implemented, fingerprint must cover every consumed fact and relevant resource/policy version.
5. Assessment model aliases collapse X-linked inheritance into one `X_LINKED` category; disease-specific X-linked dominant/recessive mechanism and PAR/ploidy policy are absent.

### P0 — pedigree/sample identity is insufficient for segregation
1. `PedigreeMember` has one nullable `specimen_id`, a free-text sex field, free-text relationship-to-proband, and affected status. There is no dedicated VCF sample-column identity mapping.
2. `Specimen` has a case-local identifier and metadata but no enforced link to a VCF sample name. One member can reference only one specimen in the current model; longitudinal/repeat specimens and multiple assays are not represented by a normalized member-specimen-sample mapping.
3. `sampled` can disagree with `specimen_id`; no invariant currently enforces consistency.
4. Segregation input accepts genotype/zygosity/phase as free text. The endpoint does not establish that the values were extracted from the analysis VCF, are technically callable, pass genotype QC, or match the family member's specimen/sample.
5. Missing genotype and no-call must remain unknown, never be coerced to 0/0/reference. Genotype calls must be tied to validated artifact, sample, caller, FORMAT fields, QC and ploidy.
6. Trio/de novo interpretation requires validated sample identity and relatedness evidence; pedigree assertions alone cannot confirm biological parentage.

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
1. `SegregationObservation` has a unique key per analysis/variant/member and the endpoint updates the existing row in place. Audit events record updates, but the current row is not an append-only clinical observation history.
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
- **Verification:** source port only; working-branch CI has not yet run.

### PR #244 — phenotype correction/retraction lifecycle
- Current PR delta against audited main: seven files: phenotype API, clinical snapshot, reproducibility, DB model, phenotype UI, one migration and amendment tests.
- Contribution: append-only supersession/retraction, required reason, original observation preservation, amendment audit, active-analysis snapshot freeze, lifecycle-aware snapshots and exclusion from new patient/family phenotype vectors.
- Historical SIRALOOM CI passed at head `a9a39fa904b3a25b9c085a56b926f4469408293f`; this is historical branch evidence only.
- Blocking integration issue: its migration is revision `0058_phenotype_observation_amendments` with down_revision `0057_clinical_intake_revisions`. Current main already has `0058_artifact_upload_intents` and `0059_specimen_ploidy_evidence`. It must be renumbered to a new revision after `0059_specimen_ploidy_evidence` and tested on a database upgraded through current head.
- API file overlaps PR #245's phenotype export routes. Merge the lifecycle and export changes in one combined API file; do not overwrite either feature with the other's stale full file.
- Review lifecycle constraints, idempotency, concurrent amendment behavior, active-analysis freeze, snapshot schema v1/v2/v3 compatibility, digest stability and UI history before merge.
- **Action:** not yet ported; waiting for a combined phenotype API and migration-safe integration.

### PR #245 — GA4GH Phenopackets v2 and FHIR R5 export
- Current compare against audited main shows a 10-file remaining delta: FHIR R5 adapter, Phenopackets v2 adapter, phenotype API export routes, interoperability documentation, validator script, workflow, dependency pins and tests.
- The broader PR file list also contains 32 paths due its older branch history. It includes artifact upload and VCF/reportability changes in that history; do not merge the PR branch wholesale.
- Historical PR comments include an explicit architecture review rejecting unconditional CNV/SV/MT/repeat reportability blockers and asking that unrelated upload/VCF work be split. Current-main compare must remain the source of truth for any proposed port; retain only the clinical interoperability delta.
- Historical SIRALOOM CI and external interoperability workflow passed at head `99373466996cd07b03f08cd6f4754fdfa290b65c`. This does not establish current-main compatibility.
- The PR itself acknowledges limitations: export-only, no round-trip import/reconciliation, no published FHIR StructureDefinitions/profiles, no official HL7 validator execution/receiver testing, no full FHIR Specimen resources, no consent/legal-basis workflow, and no observation-level sign-off.
- Phenopackets strict export blocks lossy states unless explicit lossy opt-in; FHIR preserves custom status extensions. Custom extensions are not yet externally governed.
- **Action:** not yet ported; integrate after phenotype lifecycle so both use the same active/history semantics. Keep interoperability explicitly optional and loss-aware.

## 5. Reconciliation order

1. PR #247 is ported on this working branch; run all relevant backend/frontend tests and compare its changed files against current main.
2. Port PR #244 as a single atomic lifecycle feature:
   - add amendment model,
   - add migration revision after current 0059,
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
- PR #244 and #245 remain unported pending the combined lifecycle/export integration.
- No test/CI/clinical qualification claim is made for the working branch yet.
