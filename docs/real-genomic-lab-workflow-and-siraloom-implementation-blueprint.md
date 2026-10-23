# Real Genomic Diagnostic Laboratory Workflow: A–Z and SIRALOOM Blueprint

**Status:** Research-backed requirements blueprint; not proof of clinical validation.  
**Intended use:** Germline rare-disease interpretation of SNV and small-indel VCFs, with explicit interfaces to the upstream laboratory.  
**Current boundary:** SIRALOOM Variant begins at VCF intake. It does not itself collect specimens, extract DNA, prepare libraries, sequence samples, align FASTQ reads, or call variants. Those steps must be completed by a qualified laboratory and upstream pipeline, with identity, QC and provenance passed into SIRALOOM.  
**Current executable scope:** SNVs and small indels only. CNVs, structural variants, mitochondrial variants, repeat expansions, mosaicism, pharmacogenomics, somatic oncology and complex/polygenic disease require separate implemented and qualified workflows before support can be claimed.

## 1. Core operating model

SIRALOOM must remain a case-centered, resource-governed, auditable interpretation and reporting system—not an autonomous diagnostician. Keep these concepts separate:

1. Analytical validity and technical quality.
2. Population frequency and rarity.
3. Phenotype prioritization.
4. Gene–disease validity.
5. Inheritance and segregation compatibility.
6. Variant pathogenicity classification.
7. Patient-level causal interpretation.
8. Clinical reportability and secondary-finding policy.
9. Authorized human sign-out.

A high rank is not a pathogenic classification. A pathogenic/likely pathogenic classification does not alone prove that a variant explains this patient's phenotype. A VUS must not be promoted to a diagnosis by a ranking model. Qualified personnel retain interpretation and release authority.

## 2. Complete laboratory lifecycle

Exact SOPs, thresholds, retention periods, consent rules, report wording and legal requirements must be approved by each laboratory for its assay, jurisdiction and intended use. Do not hard-code universal values where validated laboratory-specific rules are required.

| Stage / when | Who / where | Input → output | Required controls and failure conditions | SIRALOOM responsibility |
|---|---|---|---|---|
| 0. Test design and governance, before testing and after material changes | Lab director, quality manager, molecular/genomics lead; quality system | Intended use, specimen types, assay design → approved test specification, SOP, validation plan and limitations | Define reportable range, variant classes, performance claims, acceptance limits, roles, change control and revalidation triggers | Version approved workflow; bind every analysis to its approved assay/workflow; block unsupported classes |
| 1. Clinical order | Ordering clinician/genetic service and accessioning; EHR/LIMS | Patient identity, indication, phenotype, family history, test and urgency → authorized order | Resolve identity conflicts; ensure minimum clinical context and valid request; clarify unsuitable tests | Case/order, requester, organization, priority, indication and audit history |
| 2. Consent and privacy | Clinician/counsellor and authorized staff; consent system/LIMS | Consent form and applicable policy → versioned choices and scope | Distinguish testing, sharing, secondary findings, research, family contact and recontact where applicable; apply jurisdictional rules | Versioned consent/policy decisions; secondary-finding gates; access logs |
| 3. Collection, labeling and transport | Collection staff, courier, accessioning; collection site/LIMS | Patient identifiers, specimen type, collection time, container and transport conditions → received specimen and custody history | Two-identifier check per SOP; labeling, stability, transport, leakage/contamination and rejection criteria | Stable specimen identity, custody events, acceptance/rejection and reasons; integrate rather than pretend to collect |
| 4. Accessioning and pre-analytical review | Accessioning staff/technologist; LIMS | Order and received specimen → accession ID and accepted/held/rejected state | Match patient/order/specimen; detect duplicates and swaps; document insufficient, wrong, degraded or mislabeled samples | Unique constraints, explicit hold/reject states; never silently relink specimens |
| 5. DNA extraction and quantification, wet lab | Trained technologist; bench/instruments | Accepted specimen → extracted DNA, yield/concentration/purity and batch records | Approved SOP, controls, contamination prevention, instrument/reagent lot traceability and assay-specific acceptance criteria | Store result, operator, batch, method, QC and instrument/reagent metadata; no claim SIRALOOM performed bench work |
| 6. DNA quality and identity | Technologist and reviewer; lab instruments/LIMS | DNA and controls → QC pass/fail/conditional, identity or contamination finding | Investigate contamination, sample swaps, low yield/degradation or identity mismatch; document repeats/deviations | Structured QC and identity evidence; gate downstream processing when required |
| 7. Library preparation/enrichment, if applicable | Technologist; wet lab | Qualified DNA, kit/panel and lot → library and preparation QC | Track sample-to-library mapping, target design, lot, controls, contamination, yield and protocol deviations | Record upstream provenance and target-design version |
| 8. Sequencing | Sequencing operator; sequencer/LIMS | Qualified library and run configuration → raw reads and run QC | Run controls, yield/base quality, demultiplexing, index/sample assignment, contamination and sample tracking | Ingest run/sample manifest and QC; link immutable raw artifacts by hash and controlled location |
| 9. Primary bioinformatics, upstream boundary | Validated pipeline; controlled compute | Raw reads, reference and assay design → aligned reads, VCF/gVCF and metrics | Tool/container/reference/index pins; identity; coverage, mapping, contamination, call quality and assay-specific QC; reproducibility | Accept VCF and upstream metadata. Do not claim FASTQ alignment or variant calling exists unless separately implemented and validated |
| 10. VCF intake and integrity | Accessioning/bioinformatics service and case owner; SIRALOOM | VCF, sample manifest, genome build, upstream QC and pipeline metadata → immutable input artifact and validated intake | File type/size/checksum, parseability, sample identity/count, declared build, contigs, required metadata and duplicate-upload behavior | Stream safely, hash, link file to case/specimen/sample; reject or hold ambiguous identity/build; preserve original bytes |
| 11. Preflight and locked analysis plan | Workflow service, resource steward, case owner | Case, test specification, input metadata, approved resources → persisted plan/snapshot | Check resource qualification, approval, version, checksum, compatibility, license/access, storage and capacity; no silent fallback | Pin exact resources/tools/reference before dispatch; missing/unqualified resources block or queue with reason; resume without changing plan silently |
| 12. Reference validation and normalization | Bioinformatics pipeline | VCF and exact reference/index/build → validated normalized variants and source mapping | Check REF allele; normalize indels and multiallelic records deterministically; validate coordinates/alleles; never mix builds silently | Versioned normalizer and reference checksum; deterministic output; distinguish record-level errors from file-level failure |
| 13. Canonical identity and transcript annotation | Annotation service/provider adapters | Normalized variant, transcript set and provider versions → gene, consequences, transcript/HGVS where determinable and provenance | Correct build, contig aliases, transcript accession/version, strand and normalization; distinguish observed from predicted consequences | Preserve original and normalized records; immutable annotation snapshot; qualify providers and validate outputs |
| 14. Technical variant QC and coverage | Bioinformatics/clinical scientist | Calls, depth/quality/mapping/region metrics and assay specification → pass/fail/review/no-call per variant or region | Assay-specific thresholds; low-complexity/homology/pseudogene limitations; coverage gaps, allele balance, read support and mapping | Store QC and reason codes; prevent failed/uncertain calls silently becoming reportable conclusions |
| 15. Population frequency and ancestry context | Bioinformatics/clinical scientist | Variant identity and approved population resources → AC/AN, AF where valid, ancestry observations and source metadata | Missing is not zero; do not calculate AF with unknown/zero denominator; preserve missing-subset semantics; rarity alone is not pathogenicity; describe ancestry limitations | Versioned adapters; distinguish absent, zero, unavailable and not queried; only show regional claims supported by source |
| 16. Phenotype normalization and clinical context | Clinician/counsellor/scientist; review workspace | Clinical notes, HPO terms, age of onset, negative findings, progression and family history → structured phenotype snapshot | Preserve source, certainty and temporal context; distinguish present, absent, unknown and not assessed; version ontology | HPO observations with source/author, negation, certainty and analysis snapshot |
| 17. Phenotype-to-gene/disease prioritization | Clinical scientist/decision support | Phenotype profile and versioned gene/phenotype resources → ranked candidates and explanation | Explain matches, mismatches and missing data; account for specificity, inheritance and gene–disease validity; rank is not diagnosis | Versioned scoring, provenance, alternatives and negative evidence; no black-box conclusion |
| 18. Gene–disease validity/mechanism | Clinical scientist/curator | Gene–disease pair, inheritance, mechanism and curated evidence → validity level and applicable mechanism | Separate definitive/strong/moderate/limited/disputed/refuted/unknown where source supports; assess disease-specific mechanism, penetrance and contradictory evidence | Store assertion, source, version, date, evidence and conflicts; allow multiple disorders per gene |
| 19. Pedigree, inheritance and segregation | Scientist and clinician; pedigree/review workspace | Family relationships, genotypes, phase, de novo/segregation observations and disease model → compatible/incompatible/unknown assessment | Verify relationship and phase; handle incomplete family data, phenocopies, penetrance, expressivity, consanguinity and de novo uncertainty | Versioned pedigree and observations; inheritance is contextual evidence, not an automatic classification |
| 20. Evidence gathering | Variant curator/clinical scientist | ClinVar, literature, functional, computational, case, segregation and population data → traceable evidence items | Preserve submitter/review status/date/citation/version; evaluate conflicts, independence and applicability; avoid double-counting correlated predictors | Evidence ledger separates external assertions from lab evaluation and stores provenance/conflicts |
| 21. Variant classification | Qualified variant interpreter; engine plus review | Variant, disease mechanism and evidence → criterion assignments and proposed five-tier class | Use applicable ACMG/AMP and ClinGen VCEP specification; track evidence for/against, strength, independence and overrides; unsupported cases require review | Versioned criteria/specification, criterion-level evidence links and reproducible calculation; not autonomous final diagnosis |
| 22. Patient-level interpretation | Clinical scientist/geneticist and ordering clinician | Classification, phenotype, genotype, inheritance, gene–disease validity, QC and history → case conclusion/differential | Separate pathogenicity from causality; consider fit, zygosity, mechanism, penetrance, alternatives, limitations and secondary findings; document inconclusive/negative findings and residual risk | Structured rationale, opposing evidence, alternatives, limitations, recommendations and author |
| 23. Confirmation and follow-up | Authorized reviewer/director and technologist | Candidate finding, assay policy and uncertainty → confirmation state/result or documented waiver; follow-up tasks | Follow validated policy and context; record method/result and authorized waiver rationale; no universal rule without approved policy | Versioned decisions and follow-up; block release when required confirmation is incomplete |
| 24. Secondary findings and consent | Authorized reviewer/director | Consent snapshot, current policy and findings → include/exclude/defer decision | Separate secondary from primary findings; respect consent and policy; apply review/confirmation rules | Independent workflow and gate; no universal gene list silently imposed |
| 25. Technical and clinical review | Qualified independent reviewer; workspace | Analysis snapshots, evidence, QC and interpretation → approve/reject/query/return/escalate | Role separation where required; expose provenance, gaps, conflicts and limitations; changes create new versions | Review state machine, reviewer, rationale, timestamp, comments and snapshot hash |
| 26. Reportability | Authorized reviewer/director | Candidate, classification, phenotype relevance, assay limits and policy → reportable/non-reportable/deferred decision | Reportability differs from pathogenicity; document VUS, negative and secondary-finding policy and omissions | Versioned human-finalized decision with rationale |
| 27. Report generation and sign-out | Authorized signatory; reporting system | Approved interpretation, reportability, methods, QC and limitations → versioned signed report | Correct identifiers; genome build, HGVS, transcript, zygosity, classification, evidence, methods, limitations, coverage gaps, recommendations, signatory/date/version | Generate from approved immutable snapshot; signed artifact hash, supersession lineage and role gates |
| 28. Release and communication | Reporting team and ordering clinician | Signed report and authorized recipient/channel → delivery/acknowledgment record | Verify recipient/authorization; document delivery failure, urgent communication and acknowledgment per policy | Controlled release, delivery status and audit; no cross-tenant or unauthorized links |
| 29. Retention, privacy and access | Lab quality/IT/privacy roles | Inputs, artifacts, reports, audit and retention schedule → controlled retrievable record or lawful disposal | Least privilege, tenant isolation, encryption, backups, legal holds, retention/deletion policy and restore tests | Scoped access, integrity, retention and backup/restore evidence |
| 30. Quality management | Quality manager, director, bioinformatics lead | QC trends, incidents, benchmarks, deviations, complaints and overrides → CAPA and approved actions | Monitor sample/run metrics, false positives/negatives, no-call, contamination, turnaround, overrides and provider failures | Traceable quality events and dashboards; thresholds require assay-specific validation |
| 31. Reanalysis/reclassification | Scientist, director, ordering clinician per policy | Original immutable analysis plus new phenotype/evidence/resources/software → child analysis, comparison, review and possible amended report | Preserve original result; distinguish variant-level reclassification from case-level reanalysis; pin old/new resources; assess missing inputs and whether resequencing is needed; communicate material changes per policy | Parent/child lineage, explicit differences, fresh review/sign-out, amended report and recontact task where applicable |
| 32. Archive and closure | Records/quality team and case owner | Case, report, artifacts, decisions, signatures, provenance and open actions → closed, retrievable record | Close only after required artifacts, communication and actions; reopening creates controlled events, never history rewrite | Closure gate, provenance export, integrity, access and retention controls |

## 3. Cross-cutting engineering rules

### Identity, tenancy and authorization
Every case, specimen, analysis, artifact, queue task, resource binding, review, report and audit event must be organization-scoped. Every API, worker task and scheduled entry point must enforce authorization and trusted dispatch identity. Use role-based permissions for specimen operations, resource administration, interpretation, review, sign-out and audit. Detect duplicates and swaps; never silently relink identity.

### Resource governance
Every provider/resource needs an identity, type, endpoint or local path, supported operations, input/output contract, release/version, genome build, checksum, license/access conditions, qualification evidence, status, approval authority, organization binding, effective dates and limitations. Each analysis pins its exact approved resource snapshot. Missing, expired, unqualified, incompatible or unavailable resources must block/queue with an actionable reason, not silently substitute. Resume safely once resolved.

### Provenance and reproducibility
For every stage record input/output artifact IDs and hashes, software/container/dependency version, reference/database version and checksum, parameters, actor/service identity, timestamps, result/reason, retry/lease history, checkpoint and audit linkage. Preserve original data, prior analyses and signed reports. Reproducibility claims require pinned inputs and environment plus tested equivalence.

### Crash recovery and idempotency
Model success, retryable failure, terminal failure, resource block, review block, QC failure, cancellation and manual-review outcomes distinctly. A crash at any stage must resume from the last durable checkpoint. Use idempotency keys, unique constraints, leases/heartbeats, bounded retry/backoff, reconciliation and dead-letter handling as appropriate. Test failures before and after durable commits, including duplicate artifacts, evidence, reports and audit events. Provider outage is not automatically a scientific failure.

### Data semantics and thresholds
Keep source representation separate from normalized variant identity; explicitly store build, reference, transcript version, HGVS, genotype/zygosity and phase. Use HGVS nomenclature, HPO terms, approved HGNC gene symbols, and consider GA4GH VRS for computable variation identity/interchange. Version ontology releases. Do not invent universal coverage, allele-balance, frequency, phenotype-score, penetrance or reportability thresholds. Missing is not zero; unqueried is not negative; QC failure is not benign evidence.

## 4. SIRALOOM mapping and gap-audit order

The repository README describes existing case/specimen/artifact intake, FastAPI/SQLAlchemy/PostgreSQL, Celery/Redis, Next.js UI, SHA-256 artifacts, annotation/population/evidence adapters, HPO context, pedigree/inheritance, ACMG/ClinGen decision support, confirmation/follow-up, secondary-finding governance, reportability/sign-out, durable partitions and resource-aware scheduling. These are repository-described capabilities, not proof of end-to-end or clinical qualification.

Preserve and integrate those modules; do not rewrite the architecture or add duplicate parallel workflows. Audit and close gaps in this order:

1. Trace one case from VCF intake through signed report: every API, model, state transition, task, artifact, resource pin and audit event.
2. Audit tenant scoping and dispatch identity for every Celery task and scheduled/system entry point.
3. Prove preflight creates an immutable plan with qualified organization-bound resources; test blocked dispatch and safe recovery.
4. Test crash/replay at every stage before and after durable commits; assert no duplicate side effects, artifacts, evidence, reports or audit entries.
5. Verify scientific behavior using reviewed known-answer fixtures for reference/normalization, annotation, population count semantics, phenotype ranking, gene–disease validity, inheritance/segregation and ACMG criteria.
6. Test parent/child comparisons for identical inputs, changed inputs, changed software, changed evidence, changed resource pins and missing historical resources.
7. Run the complete stack with real PostgreSQL, Redis, Celery, artifact storage and qualified providers; test concurrent uploads, disk limits, worker loss/restart and backup restoration.
8. Benchmark the exact supported scope against an approved germline truth set with matching reference and confidence regions; review every discordance. Do not claim this gate complete without results.
9. Complete deploying-laboratory validation, SOP approval, training/competency, change control and applicable legal/accreditation review before clinical use.

For each requirement maintain traceability: laboratory requirement → risk → SIRALOOM module/API/model/task → input/output → acceptance rule → automated test → integration test → evidence artifact → owner/approval → status. Use statuses: IMPLEMENTED_UNVERIFIED, VERIFIED_SOFTWARE, VERIFIED_INTEGRATION, LABORATORY_QUALIFIED, PARTIAL, BLOCKED, NOT_STARTED. Code presence or unit tests alone do not prove clinical/lab verification.

## 5. Release gates

- **A — Workflow completeness:** each in-scope step and exception has owner, inputs/outputs, state, QC/decision rules, audit, recovery and UI/API representation.
- **B — Scientific correctness:** reviewed fixtures cover positive, negative, missing, conflicting, malformed, boundary and unsupported cases; discrepancies are adjudicated.
- **C — Reliability/security:** tenant and role isolation, storage/queue capacity, worker loss/replay, idempotency, resource outage/recovery, backup/restore and signed artifact integrity.
- **D — End-to-end integration:** real VCF → immutable plan → required stages → human review → reportability → authorized sign-out → release/archive → child reanalysis/amended report. Inspect database state, artifacts, audit, provenance and the actual report, not only HTTP status.
- **E — Laboratory qualification:** the deploying laboratory documents intended-use-specific assay/workflow validation, reportable range, limitations, QC thresholds, staff competence, approved resources, SOPs, change control and applicable legal/accreditation requirements. Software cannot self-certify this gate.

## 6. Scope boundary

- **In current SIRALOOM Variant scope:** tertiary interpretation of germline rare-disease SNVs and small indels, beginning with a validated VCF and upstream metadata/QC.
- **Upstream integration, not current execution:** referral/order, specimen collection, extraction, library preparation, sequencing, FASTQ alignment and variant calling.
- **Not supported until separately implemented and qualified:** CNV, SV, mitochondrial, repeat expansion, mosaicism, pharmacogenomics, somatic oncology and complex/polygenic disease.
- Never claim clinical validity from software tests alone, causality from phenotype rank alone, pathogenicity from rarity alone, a negative result without assay limitations, complete coverage where gaps exist, provider execution without observed outputs, or reanalysis equivalence when historical pins are missing.

## 7. Research basis

Use current applicable editions and verify jurisdictional relevance before turning guidance into mandatory rules.

1. ISO 15189:2022, medical laboratories—quality and competence: https://www.iso.org/standard/76677.html
2. Richards et al. (2015), ACMG/AMP sequence variant interpretation and five-tier classification: https://doi.org/10.1038/gim.2015.30
3. ACMG technical standard, constitutional NGS (2021 revision): validation, QC, reproducibility, limitations, reporting and reanalysis: https://doi.org/10.1038/s41436-021-01139-4
4. CLSI MM09, 3rd edition (2023), clinical genetic/genomic sequencing test lifecycle: https://clsi.org/shop/standards/mm09/
5. CCMG NGS laboratory guideline (2019), including end-to-end validation of wet-lab and analysis pipeline: https://pmc.ncbi.nlm.nih.gov/articles/PMC6929709/
6. ClinGen Variant Classification Guidance: https://www.clinicalgenome.org/tools/clingen-variant-classification-guidance/
7. ClinGen gene–disease validity framework: https://www.clinicalgenome.org/docs/gene-disease-validity-classification-information/
8. HGVS sequence variant nomenclature: https://hgvs-nomenclature.org/stable/recommendations/general/
9. GA4GH Variation Representation Specification: https://www.ga4gh.org/product/variation-representation/
10. ACMG genetics laboratory standards: https://www.acmg.net/genetics-laboratory-standards/

## 8. Governing principle

Keep a workflow event, scientific observation, interpretive assertion, human decision and authorized clinical report as distinct records with their own provenance, version, actor, evidence and status. If evidence or an approved resource is missing, use a transparent hold, qualified limitation or review request—not fabricated certainty, silent substitution or false success.
