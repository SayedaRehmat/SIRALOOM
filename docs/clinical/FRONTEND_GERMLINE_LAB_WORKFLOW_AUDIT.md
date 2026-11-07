# SIRALOOM frontend audit against a clinical germline laboratory workflow

**Audit date:** 2026-11-07  
**Audited ref:** `feature/family-sample-identity-contract-20261107` (stacked on clinical PR #303)  
**Scope:** frontend workflow, clinical review experience, family/pedigree and phenotype UX, sample identity UX, report/sign-out UX, and missing stage coverage. This is a source-level audit of the checked-in frontend, not a usability study or clinical validation.

## Executive finding

The frontend already contains substantial workflow functionality, but it is not yet a coherent end-to-end germline diagnostic laboratory workbench. The primary case workspace is a large single-page component. The variant review page contains pedigree, segregation and inheritance controls, but segregation genotypes are manually entered and the UI has no family-member/specimen/analysis/VCF-sample identity binding workflow. There is no family genotype matrix or laboratory-grade pedigree visualization. Clinical phenotype and referral context are captured, and report review/sign-out controls exist, but important pre-analytical, sample identity, assay QC, interpretation traceability and post-analytical review states are either incomplete or spread across separate pages.

**Do not implement a new inheritance visualization or score panel before the sample identity and family genotype contracts are complete.** First make the frontend accurately expose the current backend state and clearly block unsupported actions.

## 1. Existing frontend surfaces audited

| Surface | Existing behavior observed in source | Audit conclusion |
|---|---|---|
| Case workspace `frontend/app/(app)/app/workspace/page.tsx` | Case creation, specimen registration, artifact upload, analysis creation/start, workflow-step monitoring, resource readiness, variant browsing, evidence/review actions, reports, exports and audit history are colocated in a ~79 KB client component. | Functionally broad but overloaded; workflow navigation and stage ownership are not sufficiently separated. |
| Case dossier `frontend/app/(app)/app/cases/[caseId]/page.tsx` | Case identity, access grants, specimens, analyses and artifacts. | Useful case-level view, but does not yet provide a full specimen chain-of-custody or family/sample identity dossier. |
| Phenotype intake `frontend/components/PhenotypeIntake.tsx` | HPO search, subject attribution to pedigree members, PRESENT/ABSENT/EXCLUDED/UNKNOWN/NOT_ASSESSED, onset, severity, temporal course, laterality, source references, clinical notes, correction/retraction history. | Strong structured intake foundation. Needs a clinically useful longitudinal phenotype timeline, review completeness, provenance visibility and disease-specific comparison. |
| Clinical context `frontend/components/ClinicalContextIntake.tsx` | Referral indication/question, referring clinician/organization, encounters, patient age at assessment, prior tests, differential diagnoses and review attestations. | Good source-context capture. Needs structured review of source documents and explicit unresolved/unknown handling in the workflow summary. |
| Variant review `frontend/app/(app)/app/review/page.tsx` | Review queue; variant evidence; phenotype match; pedigree members and relationships; manual segregation entry; inheritance model request; QC; ACMG criterion decisions; confirmation; follow-up; secondary finding; approval/history. | Broad reviewer surface, but not yet an auditable laboratory interpretation console. Manual genotypes can diverge from VCF; pedigree is represented as lists/forms rather than a proper pedigree and family-genotype view. |
| Reports `frontend/app/(app)/app/reports/page.tsx` | Report creation, versioning, review/finalization and signed artifact details. | Needs a complete pre-sign-out checklist, report preview with structured/narrative consistency checks, limitations/coverage, and post-sign-out amendment/reanalysis lifecycle view. |
| Dashboard, audit, operations, resources | Separate route pages exist. | Must be connected to case-stage work queues and operational blockers, not treated as independent destinations without clear next actions. |

### Directly observed frontend/API mismatch

The review page calls:
- `POST /analyses/{analysis}/variants/{variant}/segregation` with manually entered genotype, zygosity, phase and phenotype status.
- `POST /analyses/{analysis}/variants/{variant}/inheritance/assess` with selected models.

It loads pedigree members, parent-child relationships, segregation observations and specimen lists. It does **not** call the new `/cases/{case_id}/pedigree/sample-bindings` endpoints. It has no identity binding status, no binding review history and no family-member → specimen → analysis → source artifact → VCF sample display.

This is a clinical safety gap: the screen currently makes manual genotype entry available without clearly distinguishing a human-entered observation from a genotype derived from a normalized VCF call. These must be visibly different evidence classes. Until the binding and call matrix are implemented, the UI must label manual entries as manually reported, prohibit treating them as source-verified genotype calls, and keep inheritance assessment at `REQUIRES_REVIEW`.

## 2. Required laboratory workflow and frontend stage map

The interface should represent the laboratory's pre-analytical, analytical and post-analytical process. The stages below are the target workflow map. They are not a claim that every capability is already implemented.

| Stage | What laboratory staff do and inspect | Required SIRALOOM frontend experience | Current state / missing work |
|---|---|---|---|
| 0. Order, referral and clinical question | Confirm ordering provider, test indication, clinical question, phenotype summary, relevant history, requested test and urgency. | Case order/referral panel; indication and test scope; referring provider; clinical question; urgency/TAT; required documentation; completeness and discrepancy warnings. | Referral and indication capture exists. Add a first-class order/requisition workflow, urgency/TAT tracking and structured source-document review. |
| 1. Patient, family and consent identity | Establish patient identity, identifiers, family relationships as reported, consent and permitted testing/reporting scope. Distinguish reported relationship from genetically confirmed relationship. | Patient/case identity; family ID; relationship assertion source and status; consent scope/version/date; authorized contacts; identity discrepancy queue. | Case/access model exists. Consent and explicit reported-vs-confirmed relationship states are incomplete in the reviewed UI. |
| 2. Specimen accession and chain of custody | Check specimen type, collection/receipt dates, identifiers, condition, quantity/quality, source tissue, aliquots, rejection criteria, transfers and custody events. | Specimen accession table and detail; collection/receipt; source tissue; specimen condition/acceptance; rejection/hold reasons; custody timeline; linked artifacts and assays. | Basic specimen registration and artifact-to-specimen linkage exist. No complete custody event workflow or accession acceptance/rejection review was observed. |
| 3. Assay/run and sample QC | Confirm validated assay/pipeline profile, sample/run identity, contamination, coverage, read quality, sex/ploidy consistency where validated, relatedness when applicable, and assay-specific QC thresholds. | Per-specimen QC dashboard with observed values, validated thresholds, pass/fail/indeterminate states, source artifact, assay/pipeline version, reviewer and override rationale. Show sample identity/relatedness separately from pedigree assertions. | Assay QC observations/assessment exist in review UI. Identity QC and relatedness evidence workflow is missing; QC entry is generic and needs metric provenance and policy context. |
| 4. Input VCF accession and validation | Inspect original file, checksum, VCF version, sample columns, headers, contigs, reference declaration, structural validity, sample selection and validation errors. | Immutable source-artifact panel; SHA-256; file metadata; VCF version; sample list; selected sample; parser/conformance report; rejected-record and warning review; explicit acceptance/rejection. | Backend VCF stages exist; workspace shows upload/workflow state. Improve detailed VCF validation report and sample-column selection/identity review. |
| 5. Reference-controlled normalization | Verify assembly and reference package; normalize representations; preserve original and normalized artifacts; inspect decomposition, left alignment, multiallelic mapping, index and provenance. | Normalization run card with pinned tool/reference versions, input/output hashes, warnings, execution attempt, retry/recovery, record-level links and immutable provenance. | Workflow stage and resource readiness exist. Detailed per-variant normalization provenance/exception UI needs audit. |
| 6. Annotation and population context | Review transcript selection, consequences, gene nomenclature, ClinVar and population observations, including missingness and ancestry limitations. | Variant detail with assembly, genomic/HGVS, transcript selection and alternatives, source/version/hash, evidence date, population AC/AN/AF and missingness semantics. | Review displays annotations and population evidence. Add clearer source freshness, missingness, coverage limitations and conflicting assertion reconciliation. |
| 7. Clinical phenotype abstraction | Abstract findings from records/exam/history; code HPO terms; record status, subject, onset, age, severity, laterality, course, source and uncertainty. Review affected and unaffected relatives independently. | Longitudinal phenotype timeline per family member; HPO search with definition/synonyms; source-document anchor; status and onset; reviewer confirmation; contradiction/negation handling; explicit not-assessed vs absent. | Structured intake exists, including amendments and family-member attribution. Add timeline, source-document viewer/anchor, review checklist and side-by-side family phenotype comparison. |
| 8. Pedigree construction and review | Build standard pedigree from proband and relatives; record relationship, sex, affected status, age/onset, reproductive history where relevant, consanguinity as reported, adoption/donor/unknown parentage and family history. Review uncertain relationships. | Interactive pedigree using standard symbols and relationship lines; keyboard-accessible table alternative; edit/review history; relationship source/status; unknown/assumed/confirmed distinctions; family-member specimen map. | Member and parent-child APIs and basic forms exist. No proper pedigree diagram, standardized symbols, relationship confidence/source, or robust family history view. |
| 9. Family sample identity and genotype matrix | Link each family member to each specimen and assay, then to exact VCF sample column and analysis; inspect identity QC and normalized calls. | Family sample-binding workbench; per-member specimen/assay/analysis/source hash/sample-name mapping; unverified/verified/rejected revisions; identity evidence; sample-call matrix by variant; GT, dosage, zygosity, DP, GQ, AD/allele balance, PL/GL, phase/PS, no-call and callability. | Backend identity contract is newly implemented but not yet qualified. Frontend binding UI and family-level genotype matrix are absent. |
| 10. Phenotype-driven gene/disease prioritization | Compare patient and relatives' phenotypes to disease-associated phenotype annotations; consider inheritance, age of onset, penetrance, expressivity, and phenotype specificity; inspect supporting and contradictory findings. | Ranked candidate table with interpretable reasons; matching and missing terms; excluded/absent findings; evidence source/version; disease inheritance/mechanism; limitations; manual reviewer override with reason. | Some exact/descendant phenotype match display exists. Full semantic similarity and disease-aware ranking UI are not yet implemented; do not imply a match score is a diagnosis. |
| 11. Inheritance and segregation evaluation | Compare observed family genotypes and phenotype status with gene/disease mechanism and candidate models; distinguish consistent, inconsistent, insufficient and uninformative data. Check phase/in-trans evidence, penetrance, age, sex/ploidy and relationship confidence. | Model-by-model evidence table; family genotype matrix; supporting/contradictory/unavailable evidence; assumptions and exclusions; phase certainty; identity/relationship confidence; versioned review. | Current engine is deliberately conservative and returns review-required states. Existing manual genotype entry must not become a substitute for verified calls. UI needs explicit review-required and missing-evidence reasons. |
| 12. Variant-level evidence and ACMG/AMP curation | Evaluate evidence independently for each variant and disease context; inspect source data; apply current ACMG/AMP criteria and applicable ClinGen/VCEP specifications; document criterion strength, evidence and rationale. | Criterion ledger with evidence provenance, source snapshot, specification version, conflicts, reviewer rationale, prior decision and audit history. Separate automated suggestions from human-adopted criteria. | Human criterion review and history exist. Improve source-level evidence inspection, criterion applicability/limitations, VCEP specification version and explicit conflict handling. |
| 13. Technical review and confirmation | Inspect read-level evidence in validated viewer where available; assess coverage/allele balance/mapping concerns; apply lab confirmation policy; document orthogonal testing or reason for exception. | Technical evidence panel; BAM/CRAM/IGV integration only if supported and approved; coverage and callability; confirmation status/method/lab/accession/result; unresolved technical caveats. | Confirmation record exists. Read-level visualization and complete technical evidence linkage are not established. |
| 14. Reportability and sign-out | Apply laboratory reporting policy, indication relevance, classification, assay scope, secondary finding policy/consent, confirmation policy and authorized signatory review. | Reportability checklist; reportable/not-reportable/uncertain disposition and rationale; test limitations; coverage; secondary findings; required reviewer/signatory approvals; blocked gates and override trail. | Reportability and sign-out controls exist. Add complete pre-sign-out completeness matrix and prevent finalization while required data/evidence are unresolved. |
| 15. Final report and communication | Produce a clear interpretive report: primary result first, variant and gene, transcript, genome build, HGVS, zygosity, classification, phenotype correlation, limitations, methodology, coverage and recommendations as appropriate. | Structured report preview, version comparison, narrative/structured-data consistency, recipient and release status, signed artifact/hash, delivery and acknowledgement tracking. | Versioned reports and signed artifact metadata exist. Audit actual report content for required variant/methodology/coverage/limitations and delivery state. |
| 16. Post-analytical QA and reanalysis | Retain data and provenance; monitor pipeline/resource updates; identify changed classifications or phenotype; review reanalysis triggers; communicate amended reports. | Reanalysis work queue; trigger and rationale; old/new evidence and classifications; impact assessment; human approval; amended/superseded report lineage; notification and acknowledgement. | Reanalysis candidates and notifications exist. Need explicit family/genotype/phenotype change impacts, source updates and signed report amendment UX. |

## 3. Required interpretation workbench: what the laboratory reviewer must see

The variant review page should not be a single form containing all interpretation operations. It should present a stable case/variant context with distinct evidence panels and decision history.

For each candidate variant, the reviewer needs:

1. **Variant identity:** genome build, chromosome/position, REF/ALT, normalized representation, HGVS genomic/cDNA/protein where applicable, transcript accession/version, gene identifier and canonical variant key.
2. **Technical validity:** originating VCF and SHA-256, selected sample, source record, normalized call, genotype, allele depth, total depth, genotype quality, allele balance, phase/phase set, filters, callability and assay-specific limitations. Missing values must display as missing, never as reference.
3. **Phenotype fit:** patient and relative observations; HPO IDs/labels; PRESENT/ABSENT/EXCLUDED/UNKNOWN/NOT_ASSESSED; source, onset, age, severity, temporal course; matching and contradictory disease features.
4. **Gene–disease validity and mechanism:** disease identifier, inheritance mode, molecular mechanism, penetrance/expressivity, age dependency, validity source and version. Do not infer inheritance from a gene name alone.
5. **Family evidence:** pedigree diagram plus table; member relationship and confidence; specimen/assay/sample mapping; identity QC; genotype matrix; segregation observations and phase; unavailable family tests clearly identified.
6. **Population evidence:** ancestry and population definition, allele count (AC), allele number (AN), AF only when mathematically supported, coverage/missingness, dataset version and limitations. AC=0 is not missing; AF is not zero when AN is missing or nonpositive.
7. **Classification evidence:** ACMG/AMP criterion, strength, source, observation, applicability, evidence ID, specification version, reviewer action and rationale. Automated suggestions are not final classifications.
8. **Decision summary:** phenotype fit, inheritance compatibility, technical confidence, variant classification, reportability, unresolved conflicts, reviewer and signatory states. Keep these as separate dimensions; do not collapse them into a diagnostic probability.

## 4. Pedigree and family genotype UX requirements

### Pedigree

- Standard pedigree symbols: square, circle, sex unknown, affected/unaffected/unknown, proband arrow, deceased where known, pregnancy/individual identifiers where appropriate, partner/mating lines, sibship lines and parent-child connections.
- Relationship records must distinguish reported, assumed and genetically confirmed relationships. A pedigree edge alone is not genetic confirmation.
- Support half-siblings, multiple unions, twins, adoption, donor conception, unknown parentage and consanguinity annotations without inventing relationships.
- Record consanguinity as reported or supported by an explicitly identified evidence source; do not infer it from ethnicity, nationality, surname or geographic origin.
- Provide an accessible tabular alternative and textual relationship summary; do not rely on color or graphical position alone.

### Family specimen/sample matrix

Rows are family members; each assay/specimen is a separately identifiable sample. Show:
- specimen identifier/type and collection/receipt;
- assay/run and analysis identifiers;
- immutable source VCF SHA-256 and selected sample column;
- binding status and reviewer;
- identity QC/relatedness result and method;
- normalized genotype per candidate variant;
- DP, GQ, AD/allele balance, phase/PS, callability and no-call reason;
- source record and normalization provenance.

A person may have multiple specimens and assays. Do not model this as one permanent specimen field on the pedigree member. A family-level analysis should compose separate member analyses; do not silently accept a multi-sample VCF if the backend contract remains one selected sample per analysis.

## 5. Safety and workflow gating requirements

- No inheritance conclusion from manually typed genotype strings.
- No inheritance conclusion from an unverified sample binding.
- A verified sample-name binding is not proof of biological identity or parentage; require identity-QC evidence and reviewed relationship evidence appropriate to the intended inference.
- No-call, missing GT, insufficient depth, low GQ, allele dropout, uncallable locus or unsupported ploidy must remain UNKNOWN/INSUFFICIENT, not HOM_REF.
- Affected status and phenotype status are not interchangeable. A relative's absence of a phenotype must account for age, penetrance, variable expressivity and whether the feature was actually assessed.
- De novo evidence requires validated parental sample identity, relationship confidence, callable parental loci and relevant technical QC; an absent parental call is not a de novo observation.
- Compound heterozygous inference requires evidence for two relevant alleles and phase (in trans, in cis or unresolved); do not assume trans from two heterozygous variants.
- Inheritance model compatibility is distinct from ACMG/AMP criterion application. Segregation evidence may inform criteria such as PP1/BS4 or de novo criteria only under the applicable current guidance and evidence strength; no automatic double counting.
- Mitochondrial, CNV/SV, repeat-expansion and other non-trial variant classes remain blocked from reportability until their dedicated pipelines and validation are qualified.
- All clinical decisions remain attributable, versioned, reasoned and reproducible from immutable input/evidence snapshots.

## 6. Frontend implementation sequence after this audit

Do not start by building the whole new UI. Implement in dependency order:

**F0 — Frontend contract audit and workflow map (this document).**
- Confirm each screen, API call, state, action and role against backend behavior.
- Add the audit's missing items to the stage backlog.
- Freeze the intended navigation and stage ownership.

**F1 — Correct unsafe existing controls.**
- Make manual segregation entries visibly manual and non-source-verified.
- Show inheritance assessment status/reasons and keep unsupported models review-only.
- Hide/disable unsupported model choices for the SNV/INDEL trial scope where appropriate; mitochondrial must not be presented as a supported trial pipeline.
- Add explicit empty, loading, error, stale-data and permission states.
- Do not remove historical records.

**F2 — Family identity workbench.**
- Build UI against the versioned sample-binding API.
- Show unverified/verified/rejected history, source digest, specimen, selected sample and reviewer evidence.
- Implement correction/replacement by creating a new revision, never editing history.
- Keep identity QC and biological relationship confirmation distinct.

**F3 — Family genotype matrix.**
- Consume only server-provided normalized sample-call projections linked to verified specimen/sample bindings.
- Display genotype, quality, callability, phase and provenance.
- Provide per-member/per-assay status and explicit missingness.
- No VCF re-parsing in the browser.

**F4 — Pedigree visualization and phenotype timeline.**
- Standard pedigree diagram plus accessible table.
- Longitudinal, family-member-specific phenotype view with source anchors and review state.

**F5 — Interpretation workbench.**
- Candidate gene/disease mechanism, phenotype evidence, inheritance compatibility, segregation, population and variant evidence in distinct panels.
- Separate automated assessment, human review, ACMG/AMP criteria and reportability.
- Do not add scoring until scientific qualification gates pass.

**F6 — Report/sign-out completeness and post-analytic lifecycle.**
- Enforce pre-sign-out checklist; display coverage/methodology/limitations; report preview and version comparison.
- Add amended report and reanalysis impact experience.

Each frontend milestone must include API contract tests, component tests, accessibility checks, localization, role-based interaction tests, stale-data/race tests, responsive layout checks and a production build. Clinical display claims require known-answer fixtures and reviewer validation, not merely a successful frontend build.

## 7. Authoritative standards and guidance used

These are the source anchors for the workflow. The applicable jurisdiction, accreditation scope, local regulations and each laboratory's validated SOPs still govern implementation.

1. **ACMG, 2021 technical standard — constitutional NGS in the clinical laboratory.** Covers specimen requirements, assay validation, QC, sample identity including family relationships, coverage, allelic fraction/zygosity, confirmation policy, staff qualifications, reporting and ongoing quality management.  
   https://doi.org/10.1038/s41436-021-01139-4
2. **ACMG/AMP, 2015 sequence variant interpretation consensus.** Five-tier classification; evidence-based pathogenic/benign criteria; segregation, computational, population and functional evidence; expert judgment and qualified clinical laboratory interpretation.  
   https://doi.org/10.1038/gim.2015.30
3. **ClinGen Variant Classification Guidance (updated July 2025).** Current consolidated general and criterion-specific recommendations; use applicable VCEP specifications from the CSpec Registry and preserve specification version.  
   https://www.clinicalgenome.org/tools/clingen-variant-classification-guidance/
4. **GA4GH Phenopackets v2.0.** Structured exchange of phenotypic, biosample, individual and family/genomic context. Interoperability model, not a substitute for a laboratory workflow or interpretation SOP.  
   https://www.ga4gh.org/product/phenopackets/
5. **HL7 FHIR Genomics Reporting IG v3.0.0.** Structured genomic report, study, finding, implication and action relationships; consumers must traverse grouped and derived observations. This is reporting interoperability guidance, not a full laboratory SOP.  
   https://hl7.org/fhir/uv/genomics-reporting/
6. **HL7 FHIR R5 DiagnosticReport.** Diagnostic reports combine clinical context, atomic observations and rendered interpretation.  
   https://hl7.org/fhir/diagnosticreport.html

## 8. Audit limitations and completion criteria

This is a code-level audit of the current frontend source. It does not establish that the screens have been observed by a clinical laboratory team, that the workflows conform to a particular accreditation program, or that the backend scientific methods are clinically validated.

The frontend audit is complete only when:
- every visible action maps to a supported API operation and an authorized role;
- every backend clinical state has an intentional display, including unknown, not assessed, failed, blocked, stale and superseded;
- the workflow stage map is represented in navigation and case-level progress;
- manual versus source-derived evidence is unmistakable;
- family-member/sample identity and genotype provenance are visible;
- the reviewer can reconstruct why a variant was prioritized, interpreted, reported or withheld;
- report output includes required method, coverage, nomenclature and limitation statements;
- tests cover all stage gates, role boundaries, race/stale-state behavior and accessible alternatives;
- clinical reviewers from the target laboratory validate the workflow against their approved SOPs.

**No claim of clinical, CAP/CLIA or ISO 15189 readiness is made by this audit.**
