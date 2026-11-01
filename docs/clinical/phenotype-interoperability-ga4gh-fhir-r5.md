# SIRALOOM clinical phenotype interoperability: GA4GH Phenopackets v2 and HL7 FHIR R5

## Status and scope

This implementation adds case-level export for the phenotype and family context already stored by SIRALOOM:

- GA4GH Phenopackets v2 Phenopacket export for a case without a pedigree.
- GA4GH Phenopackets v2 Family export when exactly one proband is explicitly designated.
- HL7 FHIR R5 Bundle export containing Patient, Observation, RelatedPerson, FamilyMemberHistory (where a relationship-to-proband assertion exists), Organization, and Provenance resources.
- Case-read authorization and a persisted SIRALOOM audit event for each export.
- Schema/model validation before the export is returned.

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
2. PRESENT, ABSENT, EXCLUDED, UNKNOWN, and NOT_ASSESSED remain distinct in SIRALOOM.
3. A family observation remains attached to the explicitly selected family member. It is not silently added to the proband's phenotype vector.
4. A family export requires exactly one explicitly designated proband. SIRALOOM does not infer a proband.
5. Parent-child edges are exported only when the stored relationship type is PARENT_CHILD. Parent roles are not inferred from absent or ambiguous sex information.
6. A submitted HPO identifier is retained. A canonical identifier is emitted only when the stored ontology resolution is CURRENT or ALTERNATE_ID.
7. An ontology release/checksum is never invented. The actual HPO release and resource provenance are included only when they exist in the stored resolution record.
8. Export does not infer a disease, inheritance model, penetrance, de novo status, pathogenicity criterion, causal variant, or clinical diagnosis.
9. The export audit event records format, schema version, warning/resource counts, and actor identity. It does not replace the clinical observation's source provenance.

## GA4GH Phenopackets v2 mapping

| SIRALOOM record | GA4GH v2 representation | Rule |
|---|---|---|
| Case without pedigree | Phenopacket | Subject identifier is a SIRALOOM case UUID; no demographic value is fabricated |
| Explicit proband | Family.proband.subject | Uses the designated pedigree member identifier |
| Family members with recorded phenotype observations | Family.relatives | Each relative has a separate Phenopacket |
| Pedigree members | Family.pedigree.persons | Includes recorded sex, affected status, and resolvable paternal/maternal parent IDs |
| HPO observation | PhenotypicFeature.type | Uses canonical HPO ID only for CURRENT or ALTERNATE_ID; otherwise retains submitted ID |
| Free-text label | PhenotypicFeature.description | Preserves supplied label; it is not treated as a replacement for the ontology code |
| PRESENT | excluded=false | Positive feature |
| ABSENT | excluded=true | GA4GH negative feature |
| EXCLUDED | excluded=true | Same base-schema representation as ABSENT; strict export flags this distinction as lossy |
| UNKNOWN / NOT_ASSESSED | No PhenotypicFeature emitted in lossy mode | Never emitted as a positive feature |
| HPO severity/modifiers/course | severity / modifiers | Included only when the stored related-term resolution is CURRENT or ALTERNATE_ID |
| ISO 8601 onset/resolution age | TimeElement.age.iso8601duration | No conversion from ambiguous free text |
| HPO release | MetaData.resources | HPO release included only when a single release is represented |
| SIRALOOM-only attributes | Export warnings | Laterality, anatomical site, temporal pattern, patient-specific episode frequency, and other non-equivalent fields are reported rather than silently discarded |

### Strict and lossy export

GET /api/v1/cases/{case_id}/phenopackets-v2 is strict by default.

The endpoint returns a response envelope containing the schema-validated GA4GH document and field-level warnings. If a local field cannot be represented faithfully, strict export returns HTTP 422. A caller may explicitly request allow_lossy=true; the response then reports each known loss. This option does not modify the stored clinical data.

The following distinctions are not fully represented by the base Phenopackets v2 PhenotypicFeature model:

- ABSENT versus EXCLUDED (both map to excluded=true).
- UNKNOWN and NOT_ASSESSED (omitted in lossy mode rather than encoded as present).
- Patient-specific episode frequency, laterality, anatomical site, and temporal pattern.
- Arbitrary local evidence payloads and free-text onset/severity without an ontology/time mapping.

A caller must retain the SIRALOOM clinical record/snapshot alongside any lossy Phenopackets exchange.

## HL7 FHIR R5 mapping

GET /api/v1/cases/{case_id}/fhir-r5/phenotypes returns a validated FHIR R5 Bundle of type collection.

| SIRALOOM concept | FHIR R5 resource/element | Rule |
|---|---|---|
| Case/proband | Patient | Uses case UUID when no pedigree exists; otherwise the explicitly designated proband |
| Family member | RelatedPerson | References the proband Patient; stores the member identifier and recorded relationship text |
| Family relationship summary | FamilyMemberHistory | Emitted only when relationship-to-proband was explicitly recorded; status is partial; no condition is invented |
| Phenotype | Observation.code | HPO coding system http://purl.obolibrary.org/obo/hp.owl |
| PRESENT | Observation.valueBoolean=true | Positive assertion |
| ABSENT / EXCLUDED | Observation.valueBoolean=false | Exact SIRALOOM status is retained in an extension |
| UNKNOWN | Observation.dataAbsentReason=unknown | Not encoded as a negative or positive finding |
| NOT_ASSESSED | Observation.dataAbsentReason=not-performed | Not encoded as a negative or positive finding |
| Family phenotype | Observation.focus | References the corresponding RelatedPerson; Observation.subject remains the proband Patient |
| Onset/attributes/term resolution | SIRALOOM extensions | Retains local values and terminology-resolution provenance |
| Export assembly provenance | Provenance | Identifies SIRALOOM as the assembler of the exchange representation, not as the original clinical observer |
| Export audit | SIRALOOM audit ledger | Records the export action separately from clinical provenance |

Observations use status=preliminary because the current phenotype record does not itself carry an observation-level verification/sign-off attestation. The export does not assert that a clinical director has reviewed or signed out the observation.

## SIRALOOM FHIR extension contract

The canonical base is https://siraloom.org/fhir/StructureDefinition/.

| Extension suffix | Value | Purpose |
|---|---|---|
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
| specimen-reference-id | valueString | Existing SIRALOOM specimen identifier |
| pedigree-parent / pedigree-child | valueReference | Directed parent-child edge between Patient/RelatedPerson resources |

These canonical URLs are implementation identifiers and documentation contracts in this repository. They are not claimed to be published or externally governed StructureDefinitions. Before external production exchange, the laboratory must publish/version the corresponding StructureDefinitions and validate the Bundle against those profiles using the official HL7 validator and the receiving system's implementation guide.

## Security, provenance, and workflow boundaries

- Both endpoints require authenticated case-read permission and tenant/case authorization.
- Every export writes a CLINICAL_INTEROPERABILITY_EXPORT audit event with actor, case, format, version, and export metrics.
- The export is read-only with respect to clinical observations, pedigree members, and source artifacts.
- The Phenopackets export returns a document inside an envelope so loss warnings are explicit. Consumers should extract the document property for the GA4GH message.
- The FHIR export returns a FHIR Bundle inside an envelope so the API format/version is explicit. Consumers should extract the bundle property.
- SIRALOOM is the assembler in FHIR Provenance; the original clinical observer is not fabricated because the current phenotype observation model does not store a direct author reference.
- The export does not include source VCF/BAM/FASTQ artifacts or expose internal storage URIs.
- Family-member specimens are not yet emitted as FHIR Specimen resources; the current export preserves the local specimen reference ID as a SIRALOOM extension. A later specimen-interoperability stage must add the resource only when the complete specimen status, type, collection, processing and subject linkage can be represented without guessing.

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

## Primary references

- GA4GH Phenopackets product and v2 version record: https://www.ga4gh.org/product/phenopackets/
- GA4GH Phenopacket Schema source: https://github.com/ga4gh/phenopacket-schema
- GA4GH Phenopackets Python bindings: https://phenopacket-schema.readthedocs.io/en/latest/python.html
- GA4GH Phenopacket schema paper: https://www.nature.com/articles/s41587-022-01357-4
- HL7 FHIR R5 Observation: https://hl7.org/fhir/R5/observation.html
- HL7 FHIR R5 Observation definitions: https://hl7.org/fhir/R5/observation-definitions.html
- HL7 FHIR R5 Patient: https://hl7.org/fhir/R5/patient.html
- HL7 FHIR R5 RelatedPerson: https://hl7.org/fhir/R5/relatedperson.html
- HL7 FHIR R5 FamilyMemberHistory: https://hl7.org/fhir/R5/familymemberhistory.html
- HL7 FHIR R5 Provenance: https://hl7.org/fhir/R5/provenance.html
- HL7 FHIR Genomics Reporting IG v3.0.0 (FHIR R4): https://hl7.org/fhir/uv/genomics-reporting/
- Python FHIR R5 models: https://pypi.org/project/fhir.resources/
