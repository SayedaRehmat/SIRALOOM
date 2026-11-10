# Phenotype, Pedigree, and Inheritance: Research and Qualification Plan

**Status:** Research baseline and implementation audit plan (2026-11-07)  
**Base:** `main` at `226dd645d5ac4047e3478fd67b6b550af9633b55`  
**Branch:** `feature/clinical-phenotype-pedigree-inheritance-qualification-20261107`  
**Scope:** Clinical phenotype capture and interpretation, family pedigree, sample/genotype mapping, inheritance compatibility, segregation evidence, reviewer UI, and downstream workflow integration.

This document is a requirements and reconciliation baseline. It does not claim clinical validation, laboratory qualification, or automated diagnostic capability.

## 1. Executive findings from current-main inspection

### Existing implementation to preserve

- PR #237 is merged. It established governed HPO intake, explicit phenotype states, structured clinical attributes, subject attribution, and frozen clinical-input snapshots.
- PR #240 is merged. It established append-only clinical-intake revisions, referral context, prior testing, differential diagnosis context, and explicit phenotype/family-history review attestations.
- Current main contains `backend/app/api/v1/pedigree.py`, with family members, proband designation, parent-child relationships, cycle checks, specimen mapping, variant-level segregation observations, and human-reviewed inheritance assessment endpoints.
- Current main contains `backend/app/inheritance.py`. This is deliberately conservative: it checks data sufficiency and returns `REQUIRES_REVIEW`; it does not calculate inheritance compatibility.
- Current main contains `backend/app/domain/clinical_input_snapshot.py`, which snapshots pedigree, relationships, specimens, clinical intake and phenotype observations, and separates proband observations from relatives' observations.
- Current main contains HPO ontology adapters and governed resource resolution.
- Migration #0051 retired the previous unvalidated M10 inheritance scores. This must remain retired; do not restore the heuristic.

### Unmerged clinical PRs requiring reconciliation

| PR | Branch contribution | Current status / action |
|---|---|---|
| #244 | Append-only phenotype correction/retraction; schema-v3 lifecycle snapshots; frontend amendment controls | Open, stale against current main (head a9a39fa; current main 51 commits ahead). Port/rebase narrowly after review. Its migration filename #0058 collides with current main's #0058 artifact-upload-intents migration; assign a new migration after current head, preserving the actual current down_revision. |
| #245 | GA4GH Phenopackets v2 and HL7 FHIR R5 exports; independent validators | Open draft, stale against current main (head 9937346; current main 46 commits ahead). Preserve only the clinical interoperability delta; exclude already-merged unrelated VCF/upload changes. CI previously passed on its historical head; rerun on rebased code. |
| #247 | Referral provenance and coded prior test types | Open, stale against current main (head e29c0ab; current main 51 commits ahead). Reconcile the three changed files against the merged #240 clinical-intake model and current frontend. |
| #153 | Case-write authorization for pedigree and phenotype endpoints | Merged. Verify current-main authorization remains in place; do not replay the PR. |
| #147 | Earlier P0 authorization/deployment work | Closed unmerged/superseded by the narrower #153. Do not merge wholesale. |

Current main SHA at audit time: `226dd645d5ac4047e3478fd67b6b550af9633b55`.

### Confirmed gaps

1. There is no disease/mechanism-aware inheritance compatibility engine in current main. `assess_model` intentionally reports data sufficiency only.
2. The old M10 score/status heuristic was retired. Historical persisted conclusions are projected to human review; this safety boundary must remain.
3. The current phenotype workspace component reads pedigree members to attribute observations, but does not provide a complete pedigree editor/visualization.
4. The main workspace page has no pedigree graph, segregation matrix, inheritance result view, or family-level interpretation panel.
5. Segregation observations are currently updated in place for the same analysis/variant/member tuple. This needs an explicit audit/history design before any clinical evidence is used for sign-out.
6. Current family observation model does not by itself establish biological parentage, confirmed de novo status, phase, disease-specific penetrance, or gene-disease-specific inheritance.
7. Phenotype evidence is context-only unless independently validated; legacy overlap scores must not reappear as clinical similarity scores.

## 2. Standards and authoritative sources

### Clinical phenotype representation

- Human Phenotype Ontology (HPO): use stable HPO identifiers, pinned ontology releases, exact term-resolution provenance, and retain submitted identifiers separately from canonical resolution.
- GA4GH Phenopackets v2: use `PhenotypicFeature` for observed clinical findings, including excluded findings and temporal/severity/modifier context; use `Family`/pedigree structures for family genomic diagnosis.
- HL7 FHIR R5: map clinical observations to appropriate Observation resources and preserve subject, status, code, effective time, provenance, and references. Do not turn symptoms into confirmed Condition diagnoses.
- Keep PRESENT, ABSENT, EXCLUDED, UNKNOWN, and NOT_ASSESSED semantically distinct. Missing or unrecorded information is not a negative finding.
- HPO disease annotations must be release-pinned and carry evidence provenance. Negative annotations and annotation frequency/context must not be treated as equivalent to a positive patient finding.

### Pedigree and family data

- GA4GH Pedigree v1.0 and its computable family-history model: represent individuals and relationships as first-class records; use controlled kinship relationships and explicit index patient(s).
- GA4GH Phenopackets family/pedigree representation: map every VCF sample identifier to exactly one pedigree individual for family analysis; do not infer missing parent/sample identities.
- Preserve biological, adoptive, donor, guardian, and other relationships as distinct relationship semantics. Only biological relationships can support Mendelian segregation calculations.
- Consanguinity is a recorded clinical/family-history attribute, not a substitute for relationship topology or genotype evidence. Never infer it from ethnicity, nationality, surname, or geographic origin.
- Trio relatedness: ACMG points-to-consider guidance says relatedness assessment is essential before a trio result is described as de novo. A relatedness QC check is not itself a standalone validated relationship test. Inconsistent sample relationships require a defined laboratory escalation policy.

### Inheritance and variant interpretation

- ACMG/AMP 2015 variant interpretation framework remains the baseline variant-classification framework.
- ClinGen guidance for PP1/BS4 and PP4 must be used for segregation/phenotype specificity evidence. These are not generic family-match scores; applicability depends on gene-disease validity, phenotype specificity, inheritance, penetrance, locus heterogeneity, and family structure.
- ClinGen de novo PS2/PM6 recommendation requires phenotype consistency and distinguishes confirmed from assumed parental relationships. The software must not label a variant de novo merely because it is absent from parental calls without sample identity/relatedness and assay-quality evidence.
- Gene-disease validity and disease-specific mechanism must be sourced from governed, versioned curations (e.g. ClinGen/GenCC and approved expert-panel specifications). A gene-level inheritance label alone is insufficient where one gene has multiple disorders or mechanisms.
- Exomiser demonstrates the established computational workflow pattern: combine VCF/genotype, phenotype, variant consequence, population frequency, and disease-specific inheritance models; its ranking is a prioritization output, not a clinical diagnosis or ACMG classification.

## 3. Required end-to-end laboratory workflow

1. **Referral and clinical intake:** capture indication, question, clinician-authored summary, age at assessment, prior testing, differential diagnoses, source records, and review attestations.
2. **Phenotype abstraction:** clinician/genetic-counsellor records positive, absent, excluded, unknown, and not-assessed findings with HPO terms, onset/resolution, severity, laterality, anatomical site, course, frequency, and source/observer provenance.
3. **Family history and pedigree:** record each relative, relationship, affected status, age/onset/death where available, biological relationship semantics, proband/index patient, and explicit consanguinity information with provenance.
4. **Specimen and sample mapping:** link each family member to specimen(s), sample IDs, assay, and VCF sample column. Require exact identity mapping; prevent sample/member swaps and duplicate mappings.
5. **Technical QC gate:** use validated sample identity/relatedness checks for trio interpretation, genotype quality/depth/allele balance and callability checks, sex-chromosome ploidy policy, contamination and assay-specific QC. Missing/low-quality calls are unknown, not reference.
6. **Disease/gene hypothesis generation:** use approved disease-gene assertions and disease-specific mode/mechanism, validity level, penetrance, age of onset, sex limitations, allelic requirements, and phenotype annotations.
7. **Phenotype prioritization:** compare proband phenotype to disease annotations using a documented, versioned semantic method; handle negative/excluded terms, information content, specificity, frequency and onset. Return component explanations, not a naked score.
8. **Genotype and inheritance evaluation:** evaluate candidate variants/alleles in the context of actual family genotypes, phase, sample ploidy, relationships, disease mechanism, and penetrance. Support compound heterozygosity only when phase/trans evidence is adequate; otherwise return unresolved.
9. **Segregation review:** calculate/apply segregation evidence only under an approved gene/disease-specific policy and eligible relatives/meioses. Separate candidate inheritance compatibility from ACMG PP1/BS4/PS2/PM6 evidence.
10. **Human review:** reviewer sees source records, phenotype evidence, pedigree, genotypes, model assumptions, exclusions, missing data, conflicting evidence, and provenance; reviewer can accept, reject, or request additional testing with rationale.
11. **Evidence and reporting:** only validated and explicitly reviewed evidence can contribute to ACMG/ClinGen classification and signed report. Context-only ranking cannot become a pathogenicity criterion automatically.
12. **Reanalysis:** phenotype corrections, family-history changes, sample remapping, new family genotypes, disease-curation updates, or resource-version updates create a new analysis candidate; historical snapshots and signed reports remain immutable.

## 4. Inheritance model scope and safeguards

Initial SNV/INDEL qualification should include, as separately tested model families:

- Autosomal dominant (including reduced penetrance, age-dependent penetrance, variable expressivity, and de novo hypotheses).
- Autosomal recessive (homozygous and compound heterozygous; phase-aware).
- X-linked dominant/recessive where disease-specific sex and dosage assumptions are available.
- Mitochondrial inheritance only when mitochondrial variant analysis, heteroplasmy, tissue context, and validated thresholds are supported; otherwise explicitly unsupported.
- De novo as a hypothesis/evidence pathway, not a generic inheritance mode inferred from parental absence.
- Unknown/complex/oligogenic/imprinting/mosaic mechanisms remain explicit review/unsupported states until separately specified and qualified.
- Pseudoautosomal and sex-chromosome calls must use assembly-specific PAR intervals and qualified sample/caller ploidy policies. Do not infer ploidy from recorded sex or pedigree alone.
- Consanguinity can motivate evaluation of homozygous/autozygous candidates only where validated genotype/ROH evidence exists; it must not automatically promote a homozygous variant.

Every model result must include: status, disease/gene/mechanism context, required and observed evidence, missing evidence, assumptions, penetrance/age limitations, source/version identifiers, genotype/sample identity provenance, and a reproducible fingerprint.

Allowed result states should distinguish at minimum: `SUPPORTED_FOR_REVIEW`, `INCONSISTENT`, `INSUFFICIENT_DATA`, `CONFLICTING_EVIDENCE`, `UNSUPPORTED_MODEL`, and `REQUIRES_HUMAN_REVIEW`. These states must not be mistaken for variant pathogenicity classifications.

## 5. Frontend deliverables

- **Clinical phenotype panel:** searchable governed HPO terms; explicit status; clinical modifiers; onset/resolution; source; observer; review state; amendment history.
- **Pedigree editor and graph:** standard pedigree symbols; explicit proband/index patient; affected/unaffected/unknown status; sex/unknown; deceased status where captured; parent-child/partner relationships; consanguinity/relationship annotations; sampled/specimen badges; validation errors and keyboard-accessible alternative table.
- **Family sample mapping panel:** pedigree member ↔ specimen ↔ VCF sample column, with exact match and QC state.
- **Segregation matrix:** rows are family members, columns include phenotype status, genotype, zygosity, phase, callability/QC, source, and review status. Missing is rendered as missing, never reference.
- **Inheritance results:** model-by-model results with evidence for/against, assumptions, missing data, disease-specific mechanism, penetrance, phenotype concordance explanation, and source versions.
- **Variant-level view:** link consequence/transcript annotation, population evidence, disease-gene assertion, phenotype match, segregation, ACMG evidence, and reviewer decision without conflating their semantics.
- **Auditability:** show the snapshot/revision analyzed and distinguish current intake from the frozen historical analysis view.

## 6. Integration contracts

- **After VCF validation/normalization:** map each VCF sample to an explicit specimen and pedigree member; verify multi-sample inputs; reject ambiguous identity mapping.
- **After annotation:** consume gene/transcript/consequence data as variant context; do not treat VEP consequence alone as disease mechanism.
- **Population stage:** provide ancestry-aware allele frequency/AC/AN context without substituting missing allele number with zero.
- **Evidence stage:** consume the immutable clinical snapshot, approved HPO/HPOA release, and approved gene-disease/mechanism resources. Persist a reproducible evidence manifest.
- **Candidate prioritization:** combine phenotype, genotype, inheritance, population and variant evidence with explainable components. Do not let one score conceal a failed hard constraint.
- **ACMG/ClinGen:** segregate automated candidate compatibility from formal evidence criteria; PP1/BS4/PP4/PS2/PM6 require policy-specific evidence and human review.
- **Review/report:** report only reviewed, supported assertions; include limitations and unresolved family/sample identity issues.
- **Reanalysis:** all clinically material inputs and resource revisions must invalidate/recreate downstream candidate analyses without rewriting prior signed results.

## 7. Dependency-ordered implementation plan

A. Reconcile PR #244, #245, #247 against current main; preserve #237/#240 and merged #153. Resolve stale branches and migration numbering without merging unrelated stacked commits.

B. Complete current-main audit of pedigree data model, API authorization, family sample mapping, snapshot semantics, HPO resource lifecycle, inheritance endpoints, evidence engine, ACMG evidence binding, report inclusion, and frontend behavior.

C. Define and validate canonical domain contracts for pedigree relationships, sample mapping, phenotype evidence, disease-specific inheritance model, genotype/callability, phase, penetrance, and segregation observations.

D. Implement a complete accessible pedigree editor/graph and sample mapping UI, backed by validated APIs and immutable history.

E. Implement phenotype-to-disease ranking as a separately qualified, versioned prioritization component with known-answer cases and explicit limitations.

F. Implement inheritance compatibility only after approved disease-specific mechanism data, genotype semantics, ploidy, phase, and family identity contracts are available.

G. Implement segregation evidence calculations and ACMG/ClinGen criterion mapping under versioned policies, including negative/conflicting evidence and reviewer attestations.

H. Integrate with the evidence/prioritization/review/report/reanalysis workflow.

I. Execute unit, property-based, integration, PostgreSQL, frontend, API, migration, security/tenant, snapshot/replay, synthetic pedigree, and independent known-answer scientific tests. Only then consider laboratory validation planning.

## 8. Minimum qualification corpus

Create synthetic, explicitly labelled fixtures and independently reviewed expected outcomes for:
- AD inherited, de novo, reduced penetrance, age-dependent and non-segregating scenarios.
- AR homozygous, compound heterozygous in-trans, in-cis, unknown phase, one missing parent, and unaffected carrier scenarios.
- X-linked affected/unaffected individuals with validated ploidy assumptions.
- Mitochondrial heteroplasmy/tissue limitations (or explicit unsupported results).
- Consanguineous pedigree loops and multiple affected siblings; avoid inferring causality from homozygosity alone.
- Phenocopy, locus heterogeneity, variable expressivity, incomplete penetrance, late onset, and conflicting phenotype findings.
- Missing/partial genotype, low depth, allele balance anomalies, multiallelic calls, phased/unphased GT, sample swaps, duplicate sample mappings, and relationship inconsistencies.
- Phenotype correction/retraction after an analysis snapshot; ensure old results remain reproducible and new analyses use current inputs.
- Large pedigrees, disconnected relatives, half-siblings, twins, donor/guardian relationships, unknown parentage, and invalid/cyclic relationships.

## 9. External references

- ACMG/AMP 2015 variant interpretation: https://doi.org/10.1038/gim.2015.30
- ACMG 2021 NGS technical standard: https://www.nature.com/articles/s41436-021-01139-4
- ACMG points to consider for family-based testing and sample relatedness: https://www.nature.com/articles/s41436-020-0821-6
- GA4GH Phenopackets v2: https://www.ga4gh.org/product/phenopackets/
- GA4GH Pedigree v1.0: https://www.ga4gh.org/product/pedigree/
- GA4GH pedigree model: https://github.com/ga4gh/pedigree
- Phenopacket schema: https://github.com/ga4gh/phenopacket-schema
- HPO: https://hpo.jax.org/
- ClinGen PP1/BS4/PP4 guidance: https://clinicalgenome.org/docs/clingen-guidance-for-use-of-the-pp1-bs4-co-segregation-and-pp4-phenotype-specificity-criteria-for-sequence-variant/
- ClinGen de novo PS2/PM6 guidance: https://www.clinicalgenome.org/site/assets/files/3461/svi_proposal_for_de_novo_criteria_v1_1.pdf
- ClinGen gene-disease validity: https://www.clinicalgenome.org/curation-activities/gene-disease-validity/
- Exomiser results and inheritance-aware prioritization documentation: https://exomiser.readthedocs.io/en/latest/result_interpretation.html

---
**Acceptance rule:** no claim of clinical readiness based solely on unit tests, a visually convincing graph, a similarity score, or a successful export. Clinical use requires source governance, analytical validation, laboratory-specific validation, documented SOPs, qualified personnel review, and traceable sign-out.


## 11. Clinical-laboratory standard implementation map

The binding source-to-function requirements, current code disposition, implementation order, and release gates for phenotype, pedigree, disease-specific inheritance, segregation, and ACMG/ClinGen evidence are defined in [C1 Phenotype and Inheritance Standard Implementation Map](C1_PHENOTYPE_INHERITANCE_STANDARD_IMPLEMENTATION_MAP.md). This map is the implementation authority for subsequent C1 work. The existing exact/IS-A HPO context ordering remains non-clinical and unqualified; no home-grown phenotype score or inheritance conclusion may be enabled.

## 10. C1.3 family known-answer corpus execution

The C1.2 source qualification gate is now verified on the current C1 branch. C1.3 is the active next milestone. Its source inventory, required case coverage, per-case evidence contract, independent reviewer workflow, access constraints, and exit criteria are maintained in:

- [C1.3 Family Known-Answer Corpus Qualification](C1_3_FAMILY_KNOWN_ANSWER_CORPUS_QUALIFICATION.md)

The existing PAVS fixtures remain proband-only and are not counted as family inheritance known answers. No inheritance compatibility conclusions may be enabled until the C1.3 exit criteria pass.
