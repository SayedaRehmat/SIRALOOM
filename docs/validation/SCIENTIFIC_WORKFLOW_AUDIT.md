# SIRALOOM Scientific Workflow Audit — Implementation and Qualification Gates

**Audit date:** 2026-10-30  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Audit basis:** source inspection on `main`; latest source revision when this audit was drafted is recorded in Git history.  
**Purpose:** map what the current implementation actually executes, what it only records, and what remains unimplemented or unqualified.

> **Clinical boundary:** this is a research/software implementation with partial verification. This audit does not establish diagnostic validity, ISO 15189 conformity, regulatory authorization, or readiness for clinical reporting. The laboratory must validate the intended use, exact resource versions, local workflow, acceptance criteria, and authorized human decisions.

## 1. Current source-backed capability map

| Scientific area | What the repository currently does | What it does not yet establish | Required gate |
|---|---|---|---|
| VCF intake and normalization | Validates small-variant input, pins reference/resource/toolchain identity, invokes BCFtools normalization, and preserves artifacts/provenance. Unsupported variant classes are intended to block rather than silently enter the SNV/INDEL path. | Clinical equivalence or callset concordance across all supported input conditions. | Reference-pinned golden fixtures plus independent HG001/GRCh38 concordance run with hash-verified truth assets and predeclared acceptance criteria. |
| Consequence annotation | Has GeneBe HTTP and local Ensembl VEP execution adapters. VEP checks the actual executable/cache pairing against the governed contract. | Every annotation configuration or plugin is not automatically qualified merely because the adapter ran. | Record exact provider/build/cache/plugin configuration and validate transcript/consequence outputs against curated expected cases. |
| Population evidence | Uses governed population adapters including gnomAD; stores population/cohort and resource provenance. AF is only valid when the denominator is positive and the counts are valid. | A provider response or absence of a match is not proof of a valid population observation. Every ancestry/cohort is not guaranteed available. | Test AC/AN semantics, ancestry identity, cohort scope, unavailable/missing states, exact-variant matching, and source release per adapter. |
| ClinVar | Has a direct ClinVar adapter and workflow query path. It can preserve assertion/accession/version provenance. GeneBe may also return ClinVar-derived fields, which are explicitly not equivalent to direct ClinVar execution. | Conflicting assertions are not automatically resolved into a final clinical conclusion. | Curated accession-level golden tests; review status, condition, origin, conflict and version semantics; ensure direct vs upstream-provider origin stays distinct. |
| ClinGen variant assertions | Queries the governed ClinGen variant pathogenicity/VCEP resource when configured and records source provenance. | A VCEP assertion is not a substitute for matching disease context, applicable specification, and current review. | Verify source release, exact variant/disease match, assertion status, and reviewer interpretation. |
| ClinGen gene–disease validity | Has a local official CSV provider and an execution path that queries by gene and records execution/provenance. | A gene–disease validity assertion does not itself classify a variant or prove that the variant explains this patient's phenotype. | Verify dataset release/hash, exact gene–disease identity, inheritance/mechanism fields, validity classification, and human review. |
| ACMG/AMP classification | Has a versioned ACMG/AMP 2015 combination engine and criterion evaluators for PM2, BA1, BS1, PP3, BP4, and a conservative PVS1 gate. Missing evidence, unresolved source IDs, conflicting criterion proposals, unsupported configured criteria, and PVS1 candidates can require review. | This is not a complete evaluator for every ACMG/AMP criterion or every ClinGen VCEP specification. The PVS1 implementation is not the complete ClinGen PVS1 decision tree. | Criterion-by-criterion golden corpus with source-cited expected outcomes; versioned supported-specification matrix; independent adjudication; fail-closed behavior for every unsupported criterion. |
| Computational / functional prediction | GeneBe normalization can preserve selected computational and splice predictor values. Evidence records can preserve predictor observations. PP3/BP4 requires explicit predictor-specific configured score bounds. | The presence of a score is not proof that the correct predictor ran, that calibration applies to the variant context, or that a score is a validated clinical criterion. The VEP normalizer currently emits empty computational and splice objects unless the normalization contract is extended. | Trace each score to the real executed provider/plugin, model/version, transcript, source output, calibration data and approved specification. Missing/unrecognized model context must require review. |
| HPO ontology | Loads a local pinned HPO OBO resource, resolves current/alternate/obsolete terms, and records release/checksum/provenance. | Ontology term resolution alone is not a validated patient-to-disease ranking model. | Test ontology release, alternate/obsolete term behavior, unresolved/ambiguous terms, and provenance. |
| Disease phenotype associations | Has an HPOA provider that reads a governed local release and preserves qualifier, frequency, evidence, reference, onset and curation fields. It compares patient context to disease annotations and surfaces possible discordances for review. | It does not produce a calibrated clinical phenotype-similarity score. Exact overlap or HPO ancestry is contextual evidence, not a validated Exomiser/Phenomizer-like ranking model. | If prioritization scores are required, select a specified method (for example, an approved implementation of an established semantic-similarity algorithm), pin the ontology/annotation corpus, validate against reviewed cases, and define acceptance criteria before enabling scores. |
| Patient phenotype intake | Stores PRESENT, ABSENT, EXCLUDED, UNKNOWN and NOT_ASSESSED semantics and can validate terms against the pinned ontology during evidence construction. | Unknown or not-assessed terms cannot be treated as absent; contradictory entries must not be silently resolved. | Test conflicting statuses, ontology failures, duplicates, obsolete IDs, and report rendering of negative/unknown semantics. |
| Pedigree and segregation | Stores family members, relationships, specimen links, variant-specific observations, phase/genotype/zygosity, audit history and an analysis snapshot. Structural controls include same-case membership and cycle prevention. The current inheritance assessment intentionally returns data-sufficiency/review states rather than a compatibility score. | There is no disease/mechanism-aware segregation likelihood model. It does not infer de novo status, phase, penetrance, segregation strength, or AD/AR/X-linked/mitochondrial compatibility. | Define a governed inheritance-model contract using exact gene–disease mechanism, penetrance/age, sex/chromosome, phase, relationship, genotype quality, parental testing and de novo confirmation requirements. Validate each supported model against curated pedigrees. Do not enable automated conclusions until this exists. |
| Literature | Evidence records can store literature citations/summaries supplied in the clinical-input snapshot, with gene/disease scoping and provenance fields. | The inspected workflow does not show an automatic PubMed/Europe PMC literature search-and-retrieval provider. User-entered literature is not proof that the system retrieved or comprehensively reviewed literature. Summaries alone are not sufficient variant-level evidence. | Add a governed retrieval adapter (source, query, retrieval date, PMID/DOI, version/content hash where permitted), then require curation of variant, disease, inheritance, segregation, functional assay, case count, limitations and evidence level by qualified reviewers. |
| Evidence construction | Creates distinct observation/context records for population, computational/splice, consequence, provider assertions, phenotype, gene–disease and literature. Evidence is intended to remain separate from final classification. It can preserve resource IDs, versions, request fingerprints and response hashes for provider executions. | A persisted evidence row is not automatically a scientifically valid claim. Manually entered records and provider-derived assertions must retain their origin. | Audit every evidence type's producer, required source fields, immutable provenance, analysis/variant binding, deduplication/fingerprint, error state, and every consumer in review/report exports. |
| Resource execution | Workflow records governed resource executions and can expose provider limitations instead of silently substituting a resource. | Registry presence alone does not prove executable availability, current data, approved organization binding, or successful execution. | Run the controlled staging workflow with actual organization-bound resources and verify success/NO_DATA/FAILED/unavailable outcomes in both API and UI. |
| Interpretation and report | The repository contains review, reportability, report generation, sign-out, versioning and artifact-integrity workflows and tests. | Source inspection and CI do not establish that each real UI screen displays the correct persisted evidence, provenance, uncertainty, interpretation and signed artifact for each lab role. | Execute the controlled laboratory end-to-end runbook, then compare API records, UI, report body, audit events, artifact hashes and fresh-session reads. |

## 2. Important integration findings

### 2.1 Pedigree and inheritance are currently observation-only

The current `backend/app/inheritance.py` explicitly says it does not implement a disease/mechanism-aware segregation model. The API persists a neutral, review-required segregation evidence record with source version `M11_OBSERVATIONS_ONLY`. This is scientifically safer than a heuristic score, but it does **not** satisfy the requirement for an automated inheritance/segregation model.

Do not label this stage as “inheritance compatible,” “de novo,” or “segregation supports pathogenicity” based only on current observations. Those conclusions need a governed method and the necessary relationship, genotype, phase, phenotype, penetrance, disease mechanism and confirmation context.

### 2.2 Phenotype evidence is not yet a clinical ranking model

The current HPO/HPOA path validates terms, preserves negative and unknown states, records ontology provenance, and surfaces potential discordances. It intentionally marks phenotype comparison as context-only or review-required; it does not return a validated clinical similarity score.

Do not display raw overlap counts or legacy overlap fractions as “phenotype similarity,” probability, pathogenicity, or clinical rank. A production prioritization model must identify its exact algorithm, corpus, ontology release, gene–disease associations, version and benchmark evidence.

### 2.3 Literature retrieval and literature interpretation are different stages

The evidence builder accepts literature records from the clinical-input snapshot. The inspected execution path does not establish automatic literature retrieval. Even after adding retrieval, bibliographic matching cannot be treated as scientific interpretation: each paper needs evidence-level curation and traceability to the exact variant, transcript, condition and claim.

### 2.4 Computational predictions require execution and calibration lineage

A predictor field in an annotation payload is only an observation. For each score used in PP3/BP4, SIRALOOM must be able to identify the actual provider/tool and release, exact score field and transcript/context, score calibration, applicable gene/disease specification, evidence record and reviewer-facing explanation. If any link is missing, the criterion must remain unresolved/review-required.

### 2.5 Evidence must flow through every consumer

For each evidence class, verify this complete path:

`resource/profile selection → real provider execution → request/response provenance → normalized observation → persisted evidence → criterion-specific assessment (if applicable) → variant review bundle → human decision → reportability → report content → signed artifact → audit/reanalysis`

A provider call that never produces a persisted evidence record is not complete. A persisted record not visible in review/report context is not integrated. A report that omits evidence provenance or renders an unresolved result as a negative result is not acceptable.

## 3. Scientific release gates

The following are mandatory before claiming a complete clinically qualified workflow:

1. **Supported-method registry:** each active method has intended use, source guidance, algorithm/version, required inputs, known limitations, output semantics, resource dependencies, validation set, acceptance criteria, approval authority and retirement/change-control policy.
2. **Criterion golden corpus:** source-cited positive, negative, borderline, conflicting, missing, malformed, transcript-dependent, population-dependent and unsupported cases for every automated criterion and enabled ClinGen specification.
3. **Pedigree/segregation validation corpus:** curated pedigrees spanning supported inheritance modes, affected/unaffected relatives, age-dependent penetrance, de novo parental testing, phase/compound heterozygosity, sex/chromosome context, missing family members, uncertain relationships and contradictory observations. Expected results must be independently adjudicated.
4. **Phenotype validation corpus:** versioned patient phenotypes and disease annotations with PRESENT/ABSENT/EXCLUDED/UNKNOWN/NOT_ASSESSED states, HPO term migrations, discordance cases, and independent expected ranking/interpretation if a ranking model is enabled.
5. **Functional/computational validation corpus:** predictor-specific score calibration and known-answer cases for the exact provider/model/plugin versions; no generic thresholds or cross-model score substitution.
6. **Literature governance:** retrieved records and manual curation are separate artifacts; each interpretive assertion cites exact source records and the curator/reviewer, evidence type, condition, variant/transcript and limitations.
7. **Population validation:** exact build/allele matching, AC/AN/AF semantics, population/cohort identity, ancestry limitations, missingness and source-version checks.
8. **Independent benchmark:** configure and run GIAB HG001/GRCh38 concordance with checksum-verified truth VCF, confidence BED, reference FASTA, query VCF, pinned tool versions and acceptance criteria approved before results are seen. The current benchmark protocol says this run has not yet been executed.
9. **Workflow integration:** real database/queue/provider/storage path, retry/replay and crash injection at every durable stage, no duplicate evidence/artifacts/audit records, and tenant/role checks.
10. **UI/report acceptance:** each screen/action is traced to its API and persisted records; evidence, method/version, uncertainty, missingness, reviewer decisions, reportability and sign-out state agree across UI, API, PDF and stored artifact.
11. **Laboratory qualification:** the responsible laboratory approves intended use, SOPs, QC, acceptance thresholds, resource qualification, change control, staff authorization and applicable jurisdictional requirements.

## 4. Evidence-status vocabulary

Use these labels precisely:

- **IMPLEMENTED:** source code exists.
- **UNIT-TESTED:** focused tests passed for the recorded commit.
- **INTEGRATION-TESTED:** real configured service/database/queue/artifact path passed.
- **BENCHMARK-RUN:** pinned benchmark assets and tools were actually executed.
- **SCIENTIFICALLY-REVIEWED:** qualified reviewers examined results against predeclared criteria.
- **LAB-QUALIFIED/VALIDATED:** the responsible laboratory approved the intended use under its quality system.
- **BLOCKED / NOT RUN / REQUIRES REVIEW:** a dependency, method, input, resource or approval is missing.

Never equate CI success with scientific validation.

## 5. Primary references to pin per implementation

- ACMG/AMP sequence-variant interpretation consensus (Richards et al., 2015): https://pubmed.ncbi.nlm.nih.gov/25741868/
- ClinGen Variant Classification Guidance: https://www.clinicalgenome.org/tools/clingen-variant-classification-guidance/
- ClinGen Criteria Specification Registry: https://cspec.clinicalgenome.org/cspec/ui/svi/
- ClinGen Gene-Disease Validity resources: https://clinicalgenome.org/curation-activities/gene-disease-validity/
- Human Phenotype Ontology and HPOA: https://hpo.jax.org/
- Ensembl Variant Effect Predictor: https://www.ensembl.org/info/docs/tools/vep/index.html
- gnomAD: https://gnomad.broadinstitute.org/
- ClinVar: https://www.ncbi.nlm.nih.gov/clinvar/
- NCBI PubMed / E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- GA4GH Variation Representation Specification: https://www.ga4gh.org/product/variation-representation/
- NIST Genome in a Bottle: https://www.nist.gov/programs-projects/genome-bottle
- ISO 15189:2022: https://www.iso.org/standard/76677.html

Live links are discovery references, not immutable execution provenance. For every actual analysis, persist the exact dataset/tool/specification version and checksum used.

## 6. Immediate next implementation order

1. **Implemented, unit-tested:** strict VCF GT syntax checks now prevent malformed non-empty genotype strings from being counted as interpretable pedigree observations. This is an input-quality guard only; it does not infer inheritance compatibility. See commits `8a57d926` and `10e427af`.
2. **Partially implemented:** PP3/BP4 now match predictor field names case-insensitively and can bind a proposed criterion to a persisted COMPUTATIONAL/SPLICING Evidence record from the same analysis, variant, annotation provider and provider version. A regression test exercises the end-to-end assessment service. The remaining scientific gate is explicit predictor/model release and calibration-reference provenance, plus independent validation of the selected thresholds.
3. **Next:** separate literature retrieval, citation storage, and human evidence curation; do not synthesize clinical conclusions from titles/abstracts.
4. Build versioned pedigree and phenotype method contracts and golden datasets before enabling scores.
5. Run the independent GIAB benchmark and controlled lab end-to-end workflow.
6. Verify the UI/report path against the same persisted evidence IDs, resource versions, interpretation states and hashes.

Until those gates pass, the correct product behavior is to show available evidence and its limitations, require review for unsupported interpretation, and block any unsupported clinical conclusion.
