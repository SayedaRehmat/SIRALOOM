# SIRALOOM clinical phenotype intake: standards and semantic contract

## Scope

This document governs the Stage 02 clinical-context and phenotype-intake implementation. It distinguishes the data-capture contract from downstream phenotype matching, disease inference, variant classification and clinical sign-out. Capturing a coded phenotype is not a diagnosis and does not establish a causal relationship to a variant.

## Standards baseline

| Standard/resource | Role in SIRALOOM | Boundary |
|---|---|---|
| Human Phenotype Ontology (HPO) OBO | Preferred rare-disease terminology for individual phenotypic features, clinical modifiers, onset/course and related phenotype concepts | The exact approved release, checksum and qualification must be known before a term is labelled validated |
| HPO Annotation (HPOA) | Disease-to-phenotype association data used as disease-context evidence | Disease-cohort feature frequency is not an individual patient's episode frequency |
| GA4GH Phenopackets v2.0 | Target computable exchange model for an individual, phenotypic features, measurements, biosamples, family/pedigree and metadata | Local intake fields must map without semantic loss; use explicit extensions for states or details not represented by the base schema |
| HL7 FHIR R5 Observation | Interoperable representation of point-in-time signs, symptoms, measurements and clinical observations | Do not use Observation as a substitute for a diagnosis |
| HL7 FHIR R5 Condition | Interoperable representation of a clinician-asserted condition, problem or diagnosis | A symptom/observation must not be promoted to a Condition automatically |
| HL7 FHIR FamilyMemberHistory | Interoperable representation of relevant family health history | Family-member findings remain attributed to the relative and must not be merged into the proband |
| HL7 FHIR Provenance and AuditEvent | Data-origin/process provenance and security/operational audit | Provenance and audit are complementary, not interchangeable |

## Clinical record contract

Each phenotype observation is an event-like clinical assertion with its own identity and provenance. It is associated with exactly one case and either the primary patient/proband or an explicitly identified pedigree member.

Required semantic elements:

- Submitted HPO identifier, retained exactly after case/format normalization.
- Human-readable label, retained as the clinician's supplied wording unless an approved ontology release resolves a preferred label.
- Explicit local state: `PRESENT`, `ABSENT`, `EXCLUDED`, `UNKNOWN`, or `NOT_ASSESSED`.
- Observation subject (proband or a pedigree member), observation time when known, source and supporting evidence reference.
- Structured onset, severity, modifiers, laterality, anatomical site, temporal pattern and patient-specific episode frequency when supplied.
- HPO term-resolution result and exact resource/qualification/release/checksum provenance.

### HPO resolution policy

1. A syntactically valid `HP:nnnnnnn` identifier is not proof that the term exists in the approved ontology.
2. Resolution uses the single organization-approved and technically qualified HPO OBO resource selected by the governed resource plan.
3. `CURRENT` and `ALTERNATE_ID` may receive a canonical identifier while preserving the originally submitted identifier.
4. `OBSOLETE_REPLACED`, `OBSOLETE`, `AMBIGUOUS`, `UNKNOWN`, `INVALID`, and `ONTOLOGY_UNAVAILABLE` remain visible as review states. SIRALOOM does not silently replace an obsolete term or choose among ambiguous candidates.
5. The exact resource ID, version, release, checksum, qualification ID/version and execution-contract hash are retained with the resolution.
6. If no qualified HPO resource is available, the clinical assertion may be preserved as unvalidated, but it must not be represented as ontology-validated.

## Phenopackets v2 mapping

| SIRALOOM field | Phenopackets v2 target | Mapping rule |
|---|---|---|
| `hpo_id` / `canonical_hpo_id` | `PhenotypicFeature.type` (`OntologyClass.id`) | Preserve submitted ID locally; emit canonical ID only when resolution policy permits |
| `label` | `PhenotypicFeature.description` / ontology label | Free text supplements the coded type; it is not a replacement for the ontology term |
| `phenotype_status` | `PhenotypicFeature.excluded` plus a SIRALOOM extension | `ABSENT`/`EXCLUDED` can map to excluded=true while retaining their distinction locally; `UNKNOWN` and `NOT_ASSESSED` must never be converted to excluded=true |
| `severity_hpo_id` (planned extension) | `PhenotypicFeature.severity` | Must be an ontology-coded severity concept; free-text severity alone is not equivalent |
| `modifier_hpo_ids` | `PhenotypicFeature.modifiers` | Each modifier is a separately resolved ontology class |
| onset/resolution time (structured) | `PhenotypicFeature.onset` / `resolution` (`TimeElement`) | Prefer the Phenopackets time representation; preserve source wording where supplied |
| `evidence` | `PhenotypicFeature.evidence` | Emit structured Evidence only when its evidence type/reference is known; do not invent evidence codes |
| `subject_member_id` | `Family.proband` / `Family.relatives` / pedigree linkage | A relative's phenotype is scoped to that relative, not to the proband |
| case specimens and sample mapping | `Biosample` and family/pedigree file linkage | Preserve the exact specimen-to-member relationship |
| pinned HPO release/checksum | `MetaData.resources` | Export the exact ontology resource identity used for interpretation |

SIRALOOM's current implementation captures a subset of this mapping. The local `clinical_attributes` and `ontology_resolution` JSON contracts are versioned and retained in the analysis snapshot; a complete Phenopackets v2 serializer and schema-validation gate remain separate implementation work.

## Frequency semantics

Two different concepts must never be conflated:

- **Disease feature prevalence** in HPOA describes the proportion/count of affected individuals with a feature in a disease cohort (for example, 7/13).
- **Patient-specific episode frequency** describes how often a feature occurs in one individual (for example, two episodes per month).

SIRALOOM's `episode_frequency` field is patient-specific. HPOA frequency is kept with disease-phenotype annotations and must not be copied into a patient's observed feature record.

## Subject and family semantics

- A case-level observation with no `subject_member_id` is treated as a proband/primary-patient observation.
- A family observation must reference a pedigree member in the same case.
- The clinical snapshot captures pedigree members, relationships and specimen links alongside phenotype observations.
- The evidence stage's proband phenotype vector includes only case-level observations and observations explicitly attached to the single designated proband.
- Family-member phenotype observations remain in the snapshot for later family-aware interpretation; they are not automatically used as proband features.
- More than one designated proband or a phenotype-to-member reference outside the case is a snapshot integrity error.

## Clinical interpretation safeguards

- No phenotype term, modifier, status, onset or frequency is itself a variant pathogenicity criterion.
- Phenotype similarity and disease matching must remain separately validated and provenance-bearing. The current exact/ancestor HPO matching is contextual and is not a validated clinical prioritization score.
- A diagnosis is a clinician assertion and is represented separately from a phenotype observation.
- Absence of a phenotype record is not evidence that the phenotype is absent.
- Unknown and not-assessed states remain distinct.
- No automated inheritance, penetrance, de novo or causal conclusion is produced by this intake layer.
- Human review and authorized sign-out remain mandatory.

## Qualification and verification gates

Before this stage is described as laboratory-qualified, the laboratory must qualify its own SOPs, terminology release, source-document handling, staff roles, review requirements, retention policy and applicable jurisdictional controls. Software tests alone do not establish ISO 15189 accreditation or clinical validity.

Required engineering verification includes:

1. Migration upgrade/downgrade behavior and preservation of pre-existing phenotype records.
2. Same-case subject validation, cross-tenant authorization and concurrent write/idempotency behavior.
3. Distinct longitudinal observations for the same HPO term and status.
4. Pinned HPO release/checksum/qualification enforcement and every term-resolution state.
5. Explicit state semantics and no conversion of unknown/not-assessed to absent.
6. Proband/family separation, pedigree integrity and specimen-to-member linkage.
7. Snapshot digest stability, retry replay and reproducibility after later phenotype/pedigree changes.
8. Reanalysis candidate creation for phenotype, clinical-context and pedigree changes without automatically launching a new analysis.
9. Frontend behavior, keyboard/accessibility, bilingual support and production build.
10. A schema-valid Phenopackets v2 export and FHIR mapping tests before claiming standards-based exchange.

## Primary references

- GA4GH Phenopackets v2.0: https://www.ga4gh.org/product/phenopackets/
- GA4GH Phenopackets schema documentation: https://phenopacket-schema.readthedocs.io/en/latest/
- Phenopackets PhenotypicFeature: https://phenopacket-schema.readthedocs.io/en/stable/phenotype.html
- Phenopackets Family: https://github.com/ga4gh/phenopacket-schema/blob/master/docs/family.rst
- Human Phenotype Ontology documentation: https://obophenotype.github.io/human-phenotype-ontology/
- HPO Annotation documentation: https://obophenotype.github.io/human-phenotype-ontology/annotations/introduction/
- HL7 FHIR R5 Observation: https://fhir.hl7.org/fhir/observation.html
- HL7 FHIR R5 Condition: https://fhir.hl7.org/fhir/condition.html
- HL7 FHIR R5 Provenance: https://fhir.hl7.org/fhir/provenance.html
- HL7 FHIR R5 AuditEvent: https://fhir.hl7.org/fhir/auditevent.html
