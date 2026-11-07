# SIRALOOM clinical phenotype interoperability: GA4GH Phenopackets v2 and HL7 FHIR R5

## Status and scope

This implementation adds case-level export for the phenotype and family context already stored by SIRALOOM. Only analysis-independent clinical-intake phenotype observations (analysis_id IS NULL) are exported; analysis-derived annotations/observations are not reclassified as patient-reported clinical findings:

- GA4GH Phenopackets v2 Phenopacket export for a case without a pedigree.
- GA4GH Phenopackets v2 Family export when exactly one proband is explicitly designated.
- HL7 FHIR R5 Bundle export containing Patient, Observation, RelatedPerson, FamilyMemberHistory (where a relationship-to-proband assertion exists), Organization, and Provenance resources.
- Case-read authorization and a persisted SIRALOOM audit event for each export.
- Schema/model validation before the export is returned.
- Timezone-aware serialization only; naive source timestamps are rejected instead of being assigned UTC.

This is an export capability. It does not claim that Phenopackets or FHIR import, round-trip reconciliation, profile publication, terminology server conformance, or a full EHR integration has been implemented. The returned exchange documents do not replace the immutable SIRALOOM analysis snapshot or source records.

## Standards and implementation versions

| Standard or implementation | Version | Use |
|---|---:|---|
| GA4GH Phenopacket Schema | v2.0 | Individual and family clinical/phenotypic exchange model |
| Python phenopackets | 2.0.2.post5 | Official generated Protobuf message classes and Protobuf JSON parsing |
| HL7 FHIR | R5 / 5.0.0 | Clinical resource and Bundle representation |
| Python fhir.resources | 8.3.0 | Pydantic R5 resource-model validation |
| Human Phenotype Ontology | Per qualified SIRALOOM resource | HPO term identifiers and release provenance |

The GA4GH Phenopacket schema is Protobuf-defined. The serializer validates with the generated GA4GH v2 message descriptors; it does not treat a hand-written subset JSON schema as authoritative.

FHIR R5 core resources are used here. This is not a claim of conformance to the HL7 Genomics Reporting Implementation Guide: the currently published Genomics Reporting IG v3.0.0 is based on FHIR R4, and the IG explicitly focuses on data structures rather than workflow. SIRALOOM therefore keeps the R5 clinical phenotype mapping distinct from the R4 Genomics Reporting IG.

## Clinical semantic invariants

1. A phenotype observation is not a diagnosis. SIRALOOM exports it as a GA4GH PhenotypicFeature or FHIR Observation, never as a FHIR Condition.
2. PRESENT, ABSENT, EXCLUDED, UNKNOWN, and NOT_ASSESSED remain distinct in SIRALOOM and in the FHIR export: EXCLUDED is a coded SIRALOOM result, not valueBoolean=false.
3. A family observation remains attached to the explicitly selected family member. It is not silently added to the proband's phenotype vector.
4. A family export requires exactly one explicitly designated proband. SIRALOOM does not infer a proband.
5. Parent-child edges are exported only when the stored relationship type is PARENT_CHILD. Parent roles are not inferred from absent or ambiguous sex information.
6. A submitted HPO identifier is retained. A canonical identifier is emitted only when the stored ontology resolution is CURRENT or ALTERNATE_ID.
7. An ontology release/checksum is never invented. The actual HPO release and resource provenance are included only when they exist in the stored resolution record.
8. A timezone is never inferred for a naive clinical timestamp during FHIR serialization; export fails until the source timezone is explicit.
9. Export does not infer a disease, inheritance model, penetrance, de novo status, pathogenicity criterion, causal variant, or clinical diagnosis.
10. The export audit event records format, schema version, warning/resource counts, and actor identity. It does not replace the clinical observation's source provenance.

## GA4GH Phenopackets v2 mapping

| SIRALOOM record | GA4GH v2 representation | Rule |
|---|---|---|
| Case without pedigree | Phenopacket | Subject identifier is a SIRALOOM case UUID; no demographic value is fabricated |
| Explicit proband | Family.proband.subject | Uses an opaque SIRALOOM member UUID; the mapping to the human-entered member identifier is carried only in the SIRALOOM sidecar |
| Family members with recorded phenotype observations | Family.relatives | Each relative has a separate Phenopacket |
| Pedigree members | Family.pedigree.persons | Includes recorded sex, affected status, and resolvable paternal/maternal parent IDs |
| Explicit parental consanguinity assertion | Family.consanguinous_parents | Only an explicitly stored boolean is mapped; strict export rejects not-recorded because the GA4GH boolean cannot represent unknown |
| HPO observation | PhenotypicFeature.type | Uses canonical HPO ID only for CURRENT or ALTERNATE_ID; otherwise retains submitted ID |
| Free-text label | PhenotypicFeature.description | Preserves supplied label; it is not treated as a replacement for the ontology code |
| PRESENT | excluded=false | Positive feature |
| ABSENT | excluded=true | GA4GH negative feature |
| EXCLUDED | excluded=true | Same base-schema representation as ABSENT; strict export flags this distinction as lossy |
| UNKNOWN / NOT_ASSESSED | No PhenotypicFeature emitted in lossy mode | Never emitted as a positive feature |
| HPO severity/modifiers/course | severity / modifiers | Included only when the stored related-term resolution is CURRENT or ALTERNATE_ID |
| ISO 8601 onset/resolution age | TimeElement.age.iso8601duration | No conversion from ambiguous free text |
| HPO release | MetaData.resources | The pinned OBO data-version is encoded as the dated HPO OBO version PURL; it is included only when a single valid release is represented |
| Age at assessment | SIRALOOM response sidecar | Not equated with Individual.time_at_last_encounter, which specifically represents age at last encounter; exact age value/unit/as-of date are preserved in the sidecar |
| Referral, prior testing, differential diagnoses, and review attestations | SIRALOOM response sidecar | Not forced into Phenopacket disease/diagnosis fields; field-level loss warnings are returned |
| SIRALOOM-only attributes | Export warnings and response sidecars | Laterality, anatomical site, temporal pattern, episode frequency, relationship-to-proband text, sampled flags, specimen links, and arbitrary pedigree metadata are reported rather than silently discarded |

### Strict and lossy export

GET /api/v1/cases/{case_id}/phenopackets-v2 is strict by default.

The endpoint returns a response envelope containing the schema-validated GA4GH document, field-level warnings, a complete phenotype-observation sidecar, a pedigree sidecar, and the latest clinical-intake revision sidecar. If a local field cannot be represented faithfully, strict export returns HTTP 422. A caller may explicitly request allow_lossy=true; the response then reports each known loss. This option does not modify the stored clinical data.

The following distinctions are not fully represented by the base Phenopackets v2 PhenotypicFeature model:

- ABSENT versus EXCLUDED (both map to excluded=true).
- UNKNOWN and NOT_ASSESSED (omitted in lossy mode rather than encoded as present).
- Patient-specific episode frequency, laterality, anatomical site, and temporal pattern.
- Arbitrary local evidence payloads and free-text onset/severity without an ontology/time mapping.

The phenotype-observation sidecar preserves the original submitted/canonical HPO identifiers, exact status, clinical attributes, ontology resolution/resource provenance, source, evidence, timestamps, and family-member attribution without exporting internal analysis/member foreign keys. The pedigree sidecar preserves relationship text, sampled flags, specimen-link presence, and opaque member/relationship metadata. The clinical-intake sidecar preserves revision context while replacing internal artifact UUIDs with a presence flag. These sidecars are SIRALOOM-specific and must accompany any lossy Phenopackets exchange; the GA4GH document alone does not contain these fields.

## HL7 FHIR R5 mapping

GET /api/v1/cases/{case_id}/fhir-r5/phenotypes returns the validated FHIR R5 Bundle directly with Content-Type application/fhir+json.

| SIRALOOM concept | FHIR R5 resource/element | Rule |
|---|---|---|
| Case/proband | Patient | Uses case UUID when no pedigree exists; otherwise the explicitly designated proband |
| Family member | RelatedPerson | References the proband Patient; uses an opaque UUID resource ID and stores recorded relationship text without exporting the human-entered member identifier |
| Family relationship summary | FamilyMemberHistory | Emitted only when relationship-to-proband was explicitly recorded; status is partial; no condition is invented |
| Parental consanguinity | SIRALOOM consanguinity-assessment extension | Explicit true/false or NOT_RECORDED; never inferred from pedigree structure |
| Excluded phenotype state | SIRALOOM phenotype-observation-status CodeSystem | Bundled code system defines EXCLUDED distinctly from ABSENT and UNKNOWN |
| Phenotype | Observation.code | HPO coding system http://purl.obolibrary.org/obo/hp.owl |
| PRESENT | Observation.valueBoolean=true | Positive assertion |
| ABSENT | Observation.valueBoolean=false | Negative phenotype assertion |
| EXCLUDED | Observation.valueCodeableConcept with the SIRALOOM phenotype-observation-status code system | Explicitly excluded finding; never collapsed into a negative assertion |
| UNKNOWN | Observation.dataAbsentReason=unknown | Not encoded as a negative or positive finding |
| NOT_ASSESSED | Observation.dataAbsentReason=not-asked | Not encoded as a negative or positive finding; exact local state remains in the status extension |
| Family phenotype | Observation.focus | References the corresponding RelatedPerson; Observation.subject remains the proband Patient |
| Onset/attributes/term resolution | SIRALOOM extensions | Retains local values and terminology-resolution provenance |
| Export assembly provenance | Provenance | Identifies SIRALOOM as the assembler of the exchange representation, not as the original clinical observer |
| Export audit | SIRALOOM audit ledger | Records the export action separately from clinical provenance |
| Clinical intake revision | Patient extension clinical-intake-revision | Preserves revision/version, referral, age at assessment, prior testing, clinician-entered differentials, source references, and review attestations |

Observations use status=preliminary because the current phenotype record does not itself carry an observation-level verification/sign-off attestation. The export does not assert that a clinical director has reviewed or signed out the observation.

## SIRALOOM FHIR extension and terminology contract

The canonical extension base is https://siraloom.org/fhir/StructureDefinition/. The local phenotype-observation-status CodeSystem URI is https://siraloom.org/fhir/CodeSystem/phenotype-observation-status; its EXCLUDED code preserves the local state without presenting it as a negative finding. Child URLs inside complex extensions are relative to the parent extension, as required by FHIR. These canonical identifiers are implementation contracts, not a claim that the CodeSystem or StructureDefinitions have been published in a terminology registry.

| Extension suffix | Value | Purpose |
|---|---|---|
| clinical-intake-revision | Nested extensions | Versioned clinical context, review attestations, referral indication/question, prior testing, differentials, age at assessment, and source references |
| age-at-assessment | Nested valueDecimal/valueCode/valueDate | Exact age value, unit, and assessment date; never converted into a fabricated birth date |
| prior-testing | Nested extensions | Prior test type, date, laboratory, accession, result state/summary, and source reference; internal artifact UUID is not exported |
| differential-diagnosis | Nested extensions | Original coding system/code/display and clinician-entered certainty/status; not emitted as a confirmed Condition |
| revision-version / revision-fingerprint | valueInteger/valueString | Stable clinical-intake revision lineage without exposing the internal revision UUID |
| phenotype-status | valueCode | Exact local phenotype state |
| source | valueString | SIRALOOM source category |
| ontology-resolution | Nested extensions | Submitted HPO ID, resolution status, canonical ID |
| ontology-resource-provenance | valueString JSON | Exact stored HPO resource, qualification, checksum and execution-contract provenance |
| onset-age / resolution-age | valueString | ISO 8601 age duration |
| severity / clinical-course / modifier | valueCodeableConcept | HPO-coded clinical attribute |
| laterality / temporal-pattern | valueString | Stored local attribute |
| anatomical-site | valueCodeableConcept | Stored coding system, code and display |
| episode-frequency | Nested count/period extensions | Patient-specific episode frequency; never HPOA disease prevalence |
| source-onset-text / source-severity-text | valueString | Original free-text value when it cannot be safely normalized |
| source-evidence | valueString JSON | Original local evidence payload |
| family-affected-status | valueCode | Stored affected status for a relative |
| pedigree-sex | valueCode | Stored pedigree sex; not silently conflated with gender identity |
| sampled | valueBoolean | Stored pedigree sampling flag |
| specimen-reference-present | valueBoolean | Indicates a local specimen link exists without exposing an internal specimen UUID |
| pedigree-parent / pedigree-child | valueReference | Directed parent-child edge between Patient/RelatedPerson resources |
| pedigree-member-metadata / pedigree-relationship-metadata | valueString JSON | Opaque local pedigree metadata is preserved but not interpreted as standard inheritance or consanguinity evidence |
| consanguinity-assessment | Nested status/valueBoolean | Explicit parental consanguinity assertion; NOT_RECORDED remains distinct from false |
| phenotype-observation-status | CodeSystem resource | Defines EXCLUDED as a separate state; FHIR Observation uses this code rather than valueBoolean=false |

The only recognized consanguinity metadata key for the GA4GH boolean is consanguinous_parents, and its value must be a JSON boolean. SIRALOOM searches the case clinical-context JSON, clinical-intake revision context, pedigree-member metadata, and pedigree-relationship metadata; conflicting values or string/number coercion are rejected. If no value is recorded, Phenopackets strict export refuses the Family because the GA4GH boolean cannot distinguish unknown from false, while FHIR records NOT_RECORDED.

These canonical URLs are implementation identifiers and documentation contracts in this repository. They are not claimed to be published or externally governed StructureDefinitions. Before external production exchange, the laboratory must publish/version the corresponding StructureDefinitions and validate the Bundle against those profiles using the official HL7 validator and the receiving system's implementation guide.

## Security, provenance, and workflow boundaries

- Both endpoints require authenticated case-read permission and tenant/case authorization.
- Every export writes a CLINICAL_INTEROPERABILITY_EXPORT audit event with actor, case, format, version, and export metrics.
- Server-generated SIRALOOM timestamps use the model's UTC clock contract. Clinician-entered observed_at values must carry an explicit timezone for FHIR dateTime export; the serializer rejects timezone-naive clinical timestamps rather than guessing.
- The export is read-only with respect to clinical observations, pedigree members, and source artifacts.
- The Phenopackets export returns a response envelope so loss warnings and SIRALOOM sidecars are explicit. Consumers should extract the document property for the GA4GH message and retain the sidecars with it when local semantics/provenance are required.
- The FHIR export returns a FHIR Bundle directly as the response body with application/fhir+json media type; clinical-intake revision details are carried in the documented Patient extension. Patient, RelatedPerson, Observation, FamilyMemberHistory, Provenance, Organization, and CodeSystem resource IDs are deterministic pseudonyms, not database IDs.
- SIRALOOM is the assembler in FHIR Provenance; the original clinical observer is not fabricated because the current phenotype observation model does not store a direct author reference.
- The export does not include source VCF/BAM/FASTQ artifacts or expose internal storage URIs.
- Clinical intake revision context from the versioned clinical-intake model is included in the FHIR patient extension and in the Phenopackets response sidecar. Age at assessment is mapped to Phenopackets TimeElement; referral details, prior testing, differential diagnoses and review attestations remain in the sidecar because the base Phenopackets schema does not represent them without changing their meaning.
- Family-member specimens are not yet emitted as FHIR Specimen resources; the current export preserves only the presence of a local specimen link; it does not expose an internal specimen UUID or claim that a specimen is available. GA4GH Phenopackets export returns the specimen-link presence and full pedigree metadata in its SIRALOOM sidecar, with a loss warning. A later specimen-interoperability stage must add the resource only when the complete specimen status, type, collection, processing and subject linkage can be represented without guessing.

## Verification and qualification boundary

Automated tests validate:
- GA4GH v2 Protobuf parsing for Phenopacket and Family documents.
- FHIR R5 Bundle model validation.
- Proband/family subject attribution.
- Parent-child relationship mapping and refusal of ambiguous parentage.
- Exact phenotype status semantics.
- Explicit lossy-export warnings and omission of non-representable unknown states.
- No conversion of phenotype observations into diagnosis/Condition resources.

Passing software tests does not establish clinical validity, ISO 15189 accreditation, laboratory SOP approval, or conformance to a national implementation guide. Before laboratory use, qualify the local extension definitions, identity/pseudonymization policy, consent/legal basis, retention, access controls, receiving-system profiles, terminology releases, and round-trip reconciliation process.

## Independent external-validator qualification

The clinical interoperability CI adds an independent validation layer in addition to SIRALOOM's Python model/Protobuf parsing and application-level reference checks. The workflow creates deterministic synthetic fixtures only; no real patient records or production exports are used.

| Validator | Pinned release | Scope in CI |
|---|---:|---|
| GA4GH `phenopacket-tools` CLI | 1.0.0 | Base schema requirements and semantic checks for one Phenopacket and one Family |
| HL7 FHIR Validator CLI | 7.0.3 | FHIR R5 core validation using FHIR version 5.0.0; terminology-server lookups are disabled for deterministic core validation |

The downloaded validator archives are SHA-256 checked before execution. CI inspects the GA4GH CSV findings and FHIR validator output and fails on any validator-level ERROR; warnings and informational findings are retained without being silently suppressed. The validator reports are retained as a GitHub Actions artifact named `clinical-interop-external-validation`.

Reproduce locally after installing the project and Java 17 or newer:

```bash
python scripts/validate_clinical_interop_exports.py --output-dir build/clinical-interop

# Download/unpack the GA4GH phenopacket-tools 1.0.0 distribution from:
# https://github.com/phenopackets/phenopacket-tools/releases/tag/v1.0.0
java -jar phenopacket-tools-cli-1.0.0.jar validate -H build/clinical-interop/phenopacket.json
java -jar phenopacket-tools-cli-1.0.0.jar validate -H -e family build/clinical-interop/family.json

# Download validator_cli.jar from the pinned HL7/HAPI release 7.0.3.
java -jar validator_cli.jar build/clinical-interop/fhir-r5-bundle.json -version 5.0.0 -tx n/a -extension any
```

The explicit `-extension any` option permits the currently unpublished SIRALOOM extension domain while the validator checks the FHIR R5 core resource structure. It does not validate the extension value types, cardinalities, contexts, or nested child contracts. That stronger check remains blocked on publishing and loading the SIRALOOM StructureDefinitions. The validator is not being configured to ignore malformed core FHIR resources.

The Phenopacket CLI is GPL-3.0 licensed and is used as a CI qualification tool only; it is not added to SIRALOOM's runtime dependencies or distributed by the application.

This gate validates the GA4GH base schema semantics and FHIR R5 core resource constraints. It does **not** validate SIRALOOM's custom extension URLs against published StructureDefinitions, because those profiles have not yet been published. It also does not validate a receiving laboratory's national or vendor-specific implementation guide, establish terminology-server completeness, or replace clinical review. The FHIR validator's own specification documentation explicitly distinguishes computable conformance checks from narrative/business rules and human inspection.

## Primary references

- GA4GH Phenopackets product and v2 version record: https://www.ga4gh.org/product/phenopackets/
- GA4GH Phenopacket Schema source: https://github.com/ga4gh/phenopacket-schema
- GA4GH Phenopackets Python bindings: https://phenopacket-schema.readthedocs.io/en/latest/python.html
- GA4GH Phenopacket schema paper: https://www.nature.com/articles/s41587-022-01357-4
- OBO Foundry versioning principle FP-004: https://obofoundry.org/principles/fp-004-versioning.html
- HL7 FHIR R5 Observation: https://hl7.org/fhir/R5/observation.html
- HL7 FHIR R5 Observation definitions: https://hl7.org/fhir/R5/observation-definitions.html
- HL7 FHIR R5 Patient: https://hl7.org/fhir/R5/patient.html
- HL7 FHIR R5 RelatedPerson: https://hl7.org/fhir/R5/relatedperson.html
- HL7 FHIR R5 FamilyMemberHistory: https://hl7.org/fhir/R5/familymemberhistory.html
- HL7 FHIR R5 Provenance: https://hl7.org/fhir/R5/provenance.html
- HL7 FHIR Genomics Reporting IG v3.0.0 (FHIR R4): https://hl7.org/fhir/uv/genomics-reporting/
- Python FHIR R5 models: https://pypi.org/project/fhir.resources/
