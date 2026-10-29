# Germline genomic laboratory workflow: research and implementation guide

**Research snapshot:** 2026-10-24
**Product boundary:** SIRALOOM begins with a laboratory-supplied VCF. It is not a sequencing, alignment, base-calling, variant-calling, or wet-laboratory system.
**Purpose:** Explain the real operational and scientific lifecycle, the information exchanged at each stage, the decisions and outputs, the transitions to the next stage, the relevant standards and resource classes, and the specific controls a software platform must provide. This document informs engineering; it is not a laboratory SOP, a clinical interpretation, or evidence of accreditation, regulatory authorization, or clinical validation.

## 1. How to read this document

There is no single universal workflow, threshold set, report policy, or legal regime for every medical laboratory. The actual process depends on the assay, jurisdiction, accreditation, laboratory director, validated SOP, intended-use statement, test indication, consent, and the data supplied by the upstream laboratory. The stages below describe a defensible reference workflow for a germline rare-disease VCF interpretation platform. They explicitly distinguish generally applicable controls from laboratory-specific decisions.

Four types of statement are kept separate:

1. **Normative/specification:** format or interoperability requirements published by the relevant standards body.
2. **Professional guidance:** consensus or expert recommendations, whose authority and intended scope are stated by their publisher.
3. **Laboratory policy:** assay-validated thresholds, acceptance rules, reportability rules, and authorization procedures chosen and approved by the laboratory.
4. **SIRALOOM implementation observation:** code paths and test coverage inspected in the repository at the snapshot commit below. This can change independently of the standards.

An API response, software test, database record, benchmark result, or generated PDF proves only the property actually tested. It does not by itself establish that a laboratory assay is validated or that a report is clinically authorized.

### Repository scope observed for this research

- Repository: `SayedaRehmat/SIRALOOM`, Linux checkout `/home/usama/SIRALOOM`.
- Branch and HEAD at inspection: `main`, `a862a4fd9602e9d1120c4889beffa4c51f9a28fb`.
- At the time of inspection, the worktree already contained separate uncommitted VCF-fixture/documentation changes and untracked `ci.db` and `siraloom.egg-info/`; this research does not overwrite or remove them.
- Existing workflow specification: [`SCIENTIFIC_LAB_WORKFLOW_SPECIFICATION_V1.md`](../SCIENTIFIC_LAB_WORKFLOW_SPECIFICATION_V1.md).
- Existing source-level lifecycle matrix: [`END_TO_END_WORKFLOW_AUDIT.md`](../engineering/END_TO_END_WORKFLOW_AUDIT.md). That matrix contains older snapshots and must be reconciled against current code before its row statuses are treated as current.
- This document is a detailed, source-backed domain explanation and mapping supplement. It does not mark the product workflow complete.

## 2. What a diagnostic laboratory does around a VCF platform

A germline diagnostic process is conventionally managed across pre-examination, examination, and post-examination activities under the laboratory's quality system. A VCF interpretation application generally enters after upstream specimen processing and variant calling. It may receive data and metadata from those earlier processes, but it cannot claim those steps happened correctly simply because the file is syntactically valid.

The practical chain is:

```text
authorized order and identity
  → accession/specimen association
  → upstream assay and variant-calling provenance received
  → immutable VCF intake
  → file, sample, assembly and record validation
  → reference-controlled normalization
  → technical eligibility/QC assessment within supplied evidence
  → consequence annotation
  → evidence retrieval and phenotype/inheritance context
  → candidate review and variant classification
  → case-level interpretation and reportability decision
  → independent review/authorization under laboratory policy
  → controlled sign-out and delivery
  → archive, amendment, and reasoned reanalysis when indicated
```

The sequence is not always a single linear queue. A missing resource may block a stage; poor call quality may request additional data; a reviewer may return a case for further evidence; and a valid partial analysis may be retained while a specified item is pending. Workflow status must describe these real conditions rather than collapse all outcomes into “success” or “failed.”

## 3. Stage-by-stage operational and scientific requirements

Each stage defines: what laboratory staff do; why it is needed; inputs; actual processing; durable output; exit decision; failure/recovery; and what the next stage is allowed to assume. The exact acceptance thresholds belong to the validated laboratory method and SOP unless a published specification defines them.

### 3.1 User identity, organization and laboratory authority

**Laboratory activity.** A person obtains an individual account, proves control of the permitted identity channel, joins the correct laboratory organization, and receives an approved role. Administrators manage invitations and membership; reviewers and signatories receive explicitly scoped powers. Staff leave, are suspended, or change roles through controlled lifecycle actions.

**Why it matters.** A login answers “who authenticated?” It does not establish “which organization does this user represent?”, “may they access this case?”, or “may they approve/sign this report?” Those are separate authorization decisions. A browser-hidden button is not an access control.

**Inputs:** identity-provider subject and claims; verified contact/identity state as required by policy; organization; membership status; role; case grants/assignment; session and revocation state; identity-provider configuration.

**Processing and durable record:** validate the identity-provider token server-side; resolve an active local principal; verify active organization membership and case-level authority for every protected operation; audit role grants/revocations, invitations, login/session events where policy requires; use short-lived credentials and explicit session revocation/expiry policy. Background work should carry a durable dispatch identity and tenant/case scope, rather than trusting a caller-supplied organization ID.

**Output/next:** authenticated principal and authorized organization/case context. Only then may the platform expose case lists, data, artifacts or workflow actions.

**Failure behavior:** invalid, expired, revoked, disabled, or unverified identity is denied; inactive membership is denied; no implicit administrator fallback. A provider outage is an authentication outage, not anonymous access. Identity recovery is delegated to a configured identity provider but the application must verify resulting token/session state.

**SIRALOOM trace points:** frontend public signup/login/onboarding pages; Firebase client integration; `/api/v1/auth/session` and onboarding endpoints; `backend/app/auth/principal.py`; shared authorization helpers in `backend/app/auth/authorization.py`; secured route registration in `backend/app/main.py`. Repository tests cover several server-side membership and authorization contracts, but source tests do not prove a live Firebase email, browser cookie/token lifecycle, or deployed cross-lab storage boundary. Those remain separate live evidence requirements.

**Controls to demonstrate:** account takeover protections at the identity provider; server-side identity verification; tenant-aware database reads and mutations; authorization on direct object IDs; download/export authorization; worker identity/ownership checks; role revocation and account offboarding; audit trail; no patient identifiers in avoidable logs.

### 3.2 Test order, case accession, clinical context and specimen linkage

**Laboratory activity.** The lab receives an authorized test request, confirms that the requested assay and intended analysis are in scope, assigns an accession, links the correct patient or pseudonymous identity and specimen, records indication and ordering context, and captures phenotype/family information available to the lab.

**Inputs:** organization and case/accession IDs; patient pseudonym; specimen ID/type and collection metadata as needed; ordering provider and indication; test/panel and genome assembly intent; consent/data-use restrictions; assay method; upstream pipeline/caller; requested analysis scope; phenotype and family observations.

**Processing:** enforce organization boundaries; ensure specimen IDs and sample identifiers cannot be silently reassigned; validate required fields and allowed state transitions; preserve original clinical narrative alongside normalized terminology; distinguish phenotype present, explicitly absent, unknown and not assessed; store pedigree relationship claims as supplied and their provenance without assuming biological confirmation; capture the source and author of every meaningful clinical-context change. Changing indication, phenotype, specimen or scope after an analysis may invalidate selected computations and should create a reasoned change/reanalysis event.

**Output:** an auditable case and specimen record, authorized analysis scope, phenotype/family context with provenance, and an accession state eligible for file intake.

**Next-stage precondition:** the submitting actor is allowed to upload for this case; specimen and sample identity metadata are consistent; any required consent/scope checks pass.

**Failures:** duplicate accession/specimen, cross-case sample linkage, unsupported assay scope, missing required authorization, or invalid phenotype identity should be rejected or explicitly held for correction. A missing HPO ontology cannot mean a submitted term has been validated; preserve the raw term and mark validation unavailable/review-required.

**SIRALOOM trace points:** `/api/v1/cases` in `backend/app/api/v1/cases.py`; case application logic in `backend/app/application/cases.py`; phenotype routes and HPO/HPOA adapters; pedigree routes in `backend/app/api/v1/pedigree.py`; audit and change/reanalysis records. An HPO ontology release is a controlled resource; HPO disease associations are a distinct HPOA data product and must not be presumed interchangeable with the ontology.

### 3.3 Source file receipt, integrity and chain of custody

**Laboratory activity.** The laboratory submits the exact upstream VCF intended for this analysis. The platform records its source and protects the original; a derived normalized file is never substituted for it.

**Inputs:** VCF or supported compressed VCF; optional index if region-based access is used; sample identifier(s); declared assembly; caller/pipeline and assay metadata when known; uploader; expected digest if supplied; allowed size/type/storage policy.

**Processing:** stream under configured byte and time limits; calculate SHA-256 over the original bytes; validate compression and truncation; store immutably under controlled tenant/case storage; record original filename only as metadata after safe normalization; store artifact ID, bytes, digest, media/format, uploader, receipt time, case/specimen binding, and upload decision. Validate an index against the corresponding file when relied upon. Never treat client filename or path as a storage location.

**Output:** immutable source artifact and intake event, with digest and file facts. Derived files are new artifacts linked to this source.

**Next-stage precondition:** durable storage write and database linkage have both committed; the file can be retrieved and its digest rechecked. If object storage succeeds but database commit fails, reconciliation/cleanup must not leave a false completed intake. If DB state commits before queue publish, an outbox or replay mechanism must ensure the work is eventually dispatched.

**Failures:** exceeded capacity is explicit; interrupted upload is not a successful artifact; retry cannot overwrite another artifact; retry exhaustion leaves recoverable state; temporary files are cleaned without deleting the immutable source. A checksum proves byte identity, not biological sample identity or VCF correctness.

**SIRALOOM trace points:** `/api/v1/cases/{case_id}/artifacts` and `/api/v1/artifacts/{artifact_id}/download` in `backend/app/api/v1/artifacts.py`; artifact integrity and storage profile/capacity domain modules; storage route. Existing Firebase/object-storage integration tests and local storage tests are not substitutes for verification against the lab's own configured bucket/permissions and restore process.

### 3.4 VCF structural validation, sample identity and declared scope

**Laboratory activity.** Staff determine whether the delivered file is structurally valid and compatible with the ordered test and downstream processing contract. This gate does not revalidate upstream sequencing or variant-calling performance.

**Inputs:** immutable VCF; supported specification versions; declared assembly; expected sample names; supported variant classes; reference contig dictionary; assay/caller metadata and laboratory policy.

**Structural checks:** VCF version/header; required fixed fields; exact tabular field count; INFO/FORMAT declarations and cardinalities; CHROM/POS syntax and coordinate bounds; nonempty/legal REF and ALT representation; sample-column uniqueness and genotype syntax; valid missing-value representation; contig declarations and sorting expectations where required; compressed stream completion; index association if used; duplicate/conflicting records and unsupported constructs. [VCFv4.3 permits telomere sentinels at POS 0 and N+1 (N is the contig length)](https://github.com/samtools/hts-specs/blob/master/VCFv4.3.tex#L2696-L2703); these are structurally valid but are not ordinary 1-based SNV/indel coordinates. `ALT=.` is a valid reference-only/no-alternate record in the supported VCF specification and must not be treated as a sequence allele.

**Semantic checks:** selected genome build is explicit; file sample(s) correspond to intended specimen; GT and ploidy are represented and supported; REF allele can be checked against the selected reference; `ALT=.` rows are retained in the immutable source and excluded from variant processing with an explicit count; a file containing only such rows is not a negative clinical result and requires upstream callset review. POS=0 records are retained and routed for explicit telomere review; they are excluded from normalization and are explicitly not marked REF-validated because POS=0 has no 1-based FASTA interval. POS=N+1 records are recognized from a declared contig length at intake, and are re-routed after the organization-approved reference is pinned so header omission cannot cause the sentinel to enter BCFtools. A declared contig length is checked against the selected reference before treating N+1 as a telomere sentinel; disagreement blocks processing. The sentinel is preserved in a dedicated review artifact and is not claimed REF-validated. Symbolic ALT, breakend, spanning-deletion `*`, `<NON_REF>`/gVCF reference blocks, and unsupported classes are routed to an explicit unsupported/review state rather than parsed as small alleles. A multisample VCF needs an explicit policy: which sample is the proband, whether relatives are included, whether sample names are allowed, and how each sample maps to a specimen/pedigree member.

**Output:** versioned validation record with file checksum, validator/tool version, record/sample/contig counts, per-record findings, warnings and exclusions, expected sample match, assembly status, and a typed decision such as ACCEPTED, ACCEPTED_WITH_WARNINGS, REQUIRES_REVIEW, REJECTED or BLOCKED. Retain diagnostics with line/record coordinates but avoid leaking identifiers unnecessarily.

**Quality fields:** DP, GQ, AD, allele balance, FILTER and caller-specific values are not universally present. The platform must say “missing/not assessable” rather than infer pass. Thresholds must come from the laboratory's validated assay/caller SOP, with policy version and rationale. File-level call-rate or contamination/relatedness calculations require data and validated tools not necessarily present in a VCF; never claim them from a parse alone.

**Next-stage precondition:** no fatal format/sample/scope error; required assembly/reference is known; excluded records and warnings are visible; only supported records are eligible for normalization.

**SIRALOOM trace points:** `backend/app/domain/vcf_validation.py`, `backend/app/domain/ingestion.py`, VCF artifact/analysis routes and variant worker unsupported-input routing. The current declared validator allowlist and actual command versions must be read from code/config at release time; repository docs currently describe VCFv4.2/v4.3 acceptance, so this is not a claim of full VCFv4.5 support.

### 3.5 Reference identity and normalization

**Laboratory activity.** Normalize equivalent sequence variants into a consistent allele representation against an exact reference, so subsequent annotation and evidence matching operate on the same allele.

**Inputs:** accepted VCF; declared supported assembly (e.g. GRCh37 or GRCh38 only if configured/qualified); FASTA and index; contig alias map; pinned bcftools/htslib version and command policy; normalization policy; input digest.

**Processing:** verify resource identity/checksums and declared assembly; validate REF sequence against FASTA; left-align and represent indels parsimoniously using a pinned, tested tool/policy; split multiallelic records only where the policy calls for it and preserve/re-map GT and allele-indexed INFO/FORMAT fields according to VCF `Number=A`, `R`, and `G`; preserve phase separators/phase set semantics and sample order; do not set REF alleles, discard records, atomize MNVs, or liftover unless that exact transformation is separately approved and validated. Record source-to-output mappings and exclusions.

**Output:** new normalized artifact; input/output digest; exact reference package ID/version/checksum; tool version and effective command/config; record mapping, warning and validation report.

**Next-stage precondition:** every emitted record has a validated reference allele and supported representation; the exact reference/tool package is pinned to the analysis.

**Failures:** reference mismatch or ambiguous assembly is a scientific/data block, not a silent correction. Missing FASTA/index or process termination is an operational/resource block with retry policy. Never fall back to a public reference or different build during retry.

**SIRALOOM trace points:** `backend/app/domain/vcf_tools.py`, `backend/app/domain/normalization.py`, `backend/app/domain/reference.py`, `backend/app/domain/reference_package.py`, `backend/app/domain/ingestion.py`, normalization worker and resource plan. The executable BCFtools golden test exercises a phased multi-sample multiallelic record and checks remapping of INFO/FORMAT `Number=A`, `R`, and `G` fields and phase sets. It is a deterministic software contract test, not a benchmark or full genotype/phase qualification.

**Multiallelic genotype projection policy (verified 2026-10-26):** the official [BCFtools manual](https://samtools.github.io/bcftools/bcftools.html) documents `--multi-overlaps 0|.` as selecting whether other ALT alleles after splitting are represented as reference (`0`) or missing (`.`). SIRALOOM now passes `--multi-overlaps 0` explicitly in both multiallelic split paths and records `REFERENCE_ALLELE_ZERO` in normalization metadata, rather than inheriting the tool default silently. With a phased `1|2` call, BCFtools 1.19 emitted biallelic `1|0` and `0|1` projections, retaining haplotype orientation; AC/AF/R and AD/PL fields were allele-remapped in the executed golden fixture. This representation makes each split record's zero mean “not this ALT in the per-allele projection”; it is not evidence that the other original ALT was absent at the locus. Downstream analysis must retain the source-to-normalized mapping and avoid interpreting these projected genotypes as the original unsplit record. The regression fixture does not establish clinical validity of segregation or inheritance conclusions.

**Standard/tool sources:** the HTS specification repository currently identifies VCFv4.5 as canonical and v4.1–4.4 as predecessors; BCFtools documents `norm` behavior. The project should pin compatible software and spec behavior rather than claim newest-spec compliance merely because a parser accepts a file. VCF normalization is not the same representation layer as GA4GH VRS normalization/identifier generation.

### 3.6 Technical call quality assessment

**Laboratory activity.** Review whether the observed variant call has adequate technical support for its intended interpretation, based on the assay/caller and relevant quality evidence.

**Inputs:** normalized calls plus supplied FORMAT/INFO metrics; filters; upstream pipeline details; validation policy for this assay; optionally raw reads or orthogonal validation results if a lab provides them.

**Processing:** apply only a versioned, assay-validated rule set. Record every measurement, threshold, missing field, and rule outcome separately. Mark uncertain quality as not assessable/review-required. Variant quality is distinct from pathogenicity: a technically strong call can be benign; a pathogenic variant can be poorly supported in a particular sample.

**Output:** per-variant and analysis-level QC findings, eligibility and rationale. If the application lacks the raw data or a validated contamination/sample identity tool, make that limitation explicit.

**Next:** eligible calls proceed; policy exceptions require an authorized reviewer, a rationale, and audit record; unresolved quality conflicts block or flag interpretation as the SOP determines.

### 3.7 Consequence annotation and transcript choice

**Laboratory activity.** Determine transcript-specific predicted consequences of each normalized allele. Consequence prediction describes a possible molecular effect; it does not establish pathogenicity or clinical causality.

**Inputs:** normalized allele; exact assembly/reference; annotation software and release; transcript cache/database and release; transcript policy; plugin/database versions; command/configuration; optional local custom tracks.

**Processing and tool behavior:** Ensembl VEP can use local cache, database or GFF/GTF sources, and can report consequence terms, transcript/gene identifiers and HGVS-related output with appropriate options. A VEP software release and matching cache release should be kept compatible and pinned together. Cache/source selection changes available annotations. RefSeq, Ensembl and MANE transcript identities must not be collapsed into unversioned display strings. MANE Select gives a matched NCBI/Ensembl transcript pair useful as a stable clinical display default; MANE Plus Clinical adds transcripts where Select alone misses clinically relevant variants. Preserve all relevant transcript consequences and the selected report transcript/rationale rather than retaining only an undocumented “most severe” consequence.

**Output:** immutable raw provider response plus normalized annotation rows, allele/transcript identifiers and versions, consequence ontology terms, HGVS if calculable, plugin results, warnings, and full tool/cache/reference/config provenance.

**Next:** evidence/evaluation consumes only annotations tied to this analysis's normalized alleles and pinned resources. Provider failure is not empty/no-consequence annotation.

**SIRALOOM trace points:** `backend/app/adapters/annotation/vep.py`, `genebe.py`, annotation normalizers, `backend/app/workflows/variant.py`, provider execution contracts and governed resource plan. GeneBe and VEP are distinct execution routes with distinct service/locality and provenance boundaries; the presence of an adapter does not prove that a given laboratory profile can execute it.

### 3.8 Population variation evidence

**Laboratory activity.** Assess observed population allele counts/frequencies in relation to the condition, disease prevalence, penetrance, inheritance and maximum credible frequency assumptions where a documented disease-specific method applies.

**Inputs:** normalized allele/build; exact dataset/resource version; requested population labels; provider result or local indexed files; coverage/callability and filtering semantics; interpretation policy.

**Processing:** exact allele normalization and assembly compatibility first; query approved source; record dataset release, request and response identity/time, population code, AC, AN, AF, homozygote count where available, filtering/quality flags and coverage. Keep joint/exome/genome and ancestry-specific values distinct. Validate arithmetic/consistency, but do not calculate AF unless AC is a valid nonnegative integer, AN is a valid positive integer and AC is compatible with AN. A missing variant record, explicit AC=0 with callable AN, missing AN, zero AN, insufficient coverage, unavailable ancestry, API error and malformed response are different outcomes. Do not convert “not observed” or a request failure into AF=0 or proof of rarity. Population underrepresentation can limit ancestry-specific interpretation.

**Output:** resource-versioned evidence snapshot with status, counts, frequency only when denominator permits, matched allele identity, limitations, source record, query/response provenance and rule eligibility.

**Next:** a classification criterion may consume the observation only when its denominator, population and disease-specific requirements are met. Missing evidence must remain unknown/unavailable, not benign or pathogenic evidence.

**Resource considerations:** gnomAD is a population reference, not a clinical assertion authority. The gnomAD v4.1 release described restored allele-number information across called sites and changes to joint AN; the public changelog snapshot retrieved on 2026-10-24 lists v4.1.2 as a constraint-only update with variant frequency data unchanged from v4.1.1. Production must pin the actual dataset release/API selector and query semantics rather than treating “gnomAD v4” as a sufficiently exact version. A local indexed dataset is suitable for governed laboratory operation only after checksum, index, build, release, license, and lookup behavior are qualified.

**SIRALOOM trace points:** `backend/app/adapters/population/gnomad.py` has GraphQL and local tabix providers; `secondary.py` covers a local secondary source; population evidence is persisted through the variant workflow, evidence engine, evaluator, report and tenant-guarded endpoints. Existing code has regression coverage for AN missing/zero, bad counts, provider response errors and downstream null-frequency interpretation. This is software behavior evidence, not population dataset qualification.

### 3.9 Clinical assertions, gene–disease validity and knowledge sources

These sources answer different questions. A trustworthy platform preserves the assertion type, exact source record, disease context, evidence, release/retrieval time and limitations. It does not flatten all records into “known pathogenic.”

| Resource class | What it can answer | What it cannot establish by itself | Engineering treatment |
|---|---|---|---|
| ClinVar | Submitted variant-condition assertions, evidence/criteria where provided, submitter, date and aggregate conflict/review status | ClinVar does not independently choose the correct classification; aggregate record is not necessarily condition-specific evidence | Preserve VCV, RCV and SCV identities/versions, condition, submitter, review status, criteria and conflicts. Use as evidence to inspect, not as a classification oracle |
| ClinGen VCEP/CSpec | Approved disease/gene-specific refinements to ACMG/AMP criteria and expert-curated assertions | Not every gene/disease has an applicable specification; a registered specification is not automatically approved for every use | Pin CSpec/version/status, gene/condition scope, effective date and exact criteria; if absent/inapplicable, use only a separately approved baseline workflow or require review |
| ClinGen gene–disease validity | Strength of evidence for a gene–disease relationship | Does not prove an individual variant is causal | Preserve gene, disease, classification category, date and curation evidence; distinguish limited/disputed/refuted/no-known relationship |
| ClinGen dosage sensitivity | Evidence for haploinsufficiency/triplosensitivity, relevant primarily to dosage mechanisms/CNV interpretation | Does not validate small-variant consequence or establish pathogenicity of every variant in gene | Use only for supported dosage questions; SIRALOOM's small-variant scope must not imply a validated CNV interpretation pathway |
| GenCC / PanelApp / curated panels | Gene–disease assertions or panel inclusion with source-specific status | Panel inclusion is not variant classification; curation systems use different terms and processes | Preserve source vocabulary, panel/version, disease scope and panel-level confidence |
| OMIM / Orphanet | Disease/gene nomenclature and disease knowledge; access/redistribution differs | Not every record is open for bulk redistribution; disease entry is not variant-level evidence | Confirm license and access before local caching or redistribution; use stable identifiers and retain citation/provenance |
| Literature/lab internal evidence | Published case, functional, segregation and internal observations | Abstract text or internal observation does not establish a criterion without review and evidence quality assessment | Store source citation, excerpt/claim, evidence type, curator, date, patient de-identification, consent/access and conflict status |

**ClinVar caution:** NCBI describes ClinVar as an archive aggregating submitter assertions and transparently reporting conflict; a review status reflects the nature/transparency/consensus of submissions, and ClinVar does not decide which conflicting assertion is correct. Review stars must be interpreted in their record context. A VCV aggregate (variant-level) differs from an RCV variant-condition record and an SCV submitter record.

**Output:** versioned evidence objects linked to specific allele, disease/gene, source assertion and analysis. Conflicting assertions remain visible.

**Next:** phenotype prioritization and classification can consume only evidence with a compatible gene/disease context and appropriate source status. A novel/weak gene association is not interchangeable with an established disease relationship.

### 3.10 Phenotype normalization and phenotype-to-disease comparison

**Laboratory activity.** Convert clinical observations into standardized terms without deleting the clinician's words; document presence/absence, onset, age, source and certainty; compare the phenotype with known disease-associated findings.

**Inputs:** narrative findings; HPO ontology release; disease-phenotype annotation release such as HPOA; patient context; negation and onset; mapping provenance and confidence.

**Processing:** resolve HPO IDs against pinned ontology; mark obsolete, unknown, ambiguous and unmapped terms explicitly; preserve raw terms; distinguish observed present from observed absent, not observed, unknown and not assessed. HPO's hierarchy supports term relationships. HPOA disease annotations are a separate dataset and may contain frequency/onset/negation information; pin it independently and verify its ontology release. Any semantic similarity method (e.g., information-content similarity or graph-based method) must record its algorithm, ontology and annotation versions, parameters, handling of negative terms and missing phenotype coverage. Explain matched terms and conflicts to reviewers; do not present a similarity score as diagnostic probability.

**Output:** validated phenotype profile, mappings, source/time, positive and negative observations, annotation snapshot, per-candidate matched/unmatched findings, method/version and uncertainty.

**Next:** prioritize candidates for review. Phenotype similarity alone cannot establish gene validity, variant pathogenicity, causality or reportability.

**SIRALOOM trace points:** `backend/app/adapters/phenotype/hpo_obo.py` (when present), `hpoa.py`, phenotype routes, HPO/HPOA provider resource contracts, and case-context evidence in `backend/app/evidence/engine.py` and `backend/app/workflows/variant.py`. Current behavior must be checked for the selected organization's installed and approved data artifacts; no public live ontology is presumed.

### HPOA frequency and negative-assertion semantics verified 2026-10-26

The official [HPO frequency guide](https://obophenotype.github.io/human-phenotype-ontology/annotations/frequency/) distinguishes the HPO frequency term `HP:0040285` (Excluded, 0% of affected individuals), a cohort count such as `0/3`, and a percentage such as `0%`. It explains that `0/3` is a finite study observation and should not be promoted to an expert `NOT` assertion: denominator size matters and later studies may contribute additional observations. The [HPOA format specification](https://github.com/obophenotype/human-phenotype-ontology/blob/master/docs/annotations/phenotype_hpoa.md) places `NOT` in qualifier field 3 and frequency in field 8; it also says some similarity algorithms restrict inputs to aspect `P` (Phenotypic abnormality). These are separate source fields and must remain distinguishable in storage and review.

SIRALOOM now persists a narrowly scoped HPOA-to-patient-context comparison using the pinned HPO ontology's exact and `is_a` descendant relations. It separately records source `NOT`, HPO's Excluded frequency category, literal zero percent, and finite `0/N` cohort observations. The reviewer UI labels each context and cautions that frequency observations are not the same as `NOT`; it retains their original frequency/denominator and never converts these overlaps into a score, ACMG criterion, or automated diagnosis. Unresolved terms, non-P aspects, missing ontology, and conflicting patient statuses are surfaced for review. This comparator is a reviewer aid only; it is not a validated phenotype-similarity or diagnostic-ranking algorithm. Automated fixture and workflow tests cover the distinctions, but real clinical utility and disease-specific interpretation have not been independently validated.

### 3.11 Pedigree, inheritance and segregation

**Laboratory activity.** Interpret observed genotype with disease inheritance and family evidence when family data exist. The lab records reported relationships and whether biological relationships/sample identity were independently confirmed.

**Inputs:** family member/specimen mapping; affected status and age; genotype calls and QC for each member; disease inheritance/mechanism; phase; penetrance/phenocopy information; parental identity evidence if available.

**Processing:** evaluate dominant/recessive/X-linked models only in supported contexts; for compound heterozygous claims, distinguish variants proven in trans, proven in cis, statistically/inferred phase, and unknown phase; de novo status requires sufficient parental calls and sample/relationship validation and must distinguish confirmed from assumed de novo; absent family samples are unknown, not evidence against a variant. Model ploidy appropriately only where validated. Segregation counts should not be converted into a criterion without applying the applicable specification and quality/ascertainment assumptions. Do not infer consanguinity, pedigree links or biological parentage.

**Output:** inheritance compatibility and conflicts with inputs, assumptions, family-member IDs, genotype evidence, phase/segregation status, policy/spec version and provenance.

**Next:** candidate interpretation can reference this assessment. Compatibility helps explain a candidate but does not alone classify it pathogenic or prove patient causality.

**SIRALOOM trace points:** `backend/app/api/v1/pedigree.py` and inheritance/segregation services in the application/workflow. Confirm per-route object authorization and variant/case/member lineage before relying on the output.

### 3.12 Computational and functional evidence

**Computational predictions:** examples include splice prediction (SpliceAI), missense prediction (REVEL and others), conservation (phyloP/phastCons), and consequence/LoF interpretation tools. For each, record model/tool version, score definition, reference/assembly, transcript, calibration and intended operating context. Prediction score is not functional assay evidence. Multiple correlated predictions cannot be counted as independent evidence; criteria such as PP3/BP4 require the currently applicable calibrated/specification-defined use and threshold. A tool's publication or installation does not validate it for every gene, mechanism, transcript or population.

**Functional evidence:** assay construct, cell/model system, controls, replicates, validation and interpretation are part of the evidence. The ClinGen SVI PS3/BS3 recommendations call for assessing disease mechanism, assay class, the specific assay's validity, and then the variant evidence. A functional lab result must be curated to the variant/gene/disease and cannot be synthesized from an in-silico prediction.

**Literature:** literature retrieval can discover candidate papers; evidence extraction and application need human/scientific curation, source traceability and duplicate/overlap checks. Automated summaries are not independent evidence.

**Output:** separate, source-linked evidence records with eligibility/quality assessment and explicit reviewer disposition. Missing predictors/assays are unavailable, not negative.

### 3.13 Variant classification: ACMG/AMP and applicable ClinGen guidance

**Question answered:** how strong is the evidence that a particular variant is pathogenic or benign for a specified Mendelian condition? It is not the same question as whether the variant explains this patient's presentation.

The ACMG/AMP 2015 framework standardizes five labels: Pathogenic, Likely Pathogenic, Uncertain Significance, Likely Benign and Benign. It organizes evidence into pathogenic and benign criteria of different strengths and combination rules. It expects professional judgment over the full body of evidence. The criteria are condition/inheritance aware in application; a label without the asserted condition/context is incomplete.

**Inputs:** normalized allele and transcript; gene/disease validity and mechanism; population evidence; quality; functional/segregation/case/phenotype/computational evidence; source-specific assertions; applicable expert-panel specification; laboratory policy; evidence independence and conflicts.

**Processing:** for every criterion, persist: criterion code; evidence direction and strength; whether applicable; evidence IDs; data/source/version; rule/specification version; rationale; conflicts; reviewer decision. Do not automatically turn VEP consequence or prediction into a criterion. Do not double-count the same underlying data. Apply PVS1 only with disease mechanism/transcript-specific loss-of-function context and the applicable decision process; use PP3/BP4 only according to calibrated/specification-appropriate methods; assess population thresholds in the relevant disease/inheritance context; separate evidence appraisal from combination logic. ClinGen SVI guidance says PP5/BP6 should not be applied in any context; preserve such imported assertions for audit but exclude them from automated criterion assessment and require review if they appear as source assertions. If applicable specification is missing, a prerequisite is unavailable, evidence conflicts materially, or rule is outside tested scope, record unclassified/review-required rather than inventing a score or final category.

**Output:** machine-proposed classification with criterion-level ledger and reproducible inputs; separate human-reviewed classification and final report authorization.

**Review:** a qualified authorized reviewer examines sources, transcript/representation, criterion rationale, conflicts, gene/disease mechanism, quality and evidence gaps. Changes preserve machine proposal, reviewer override, rationale, attribution/time and previous history.

**Sources:** ACMG/AMP 2015 is a consensus recommendation and should be read with current ClinGen SVI general guidance and the relevant approved VCEP/CSpec specification. ClinGen's [SVI variant curation SOP](https://clinicalgenome.org/site/assets/files/3677/clingen_variant-curation_sopv1.pdf), pp. 39–40, states PP5/BP6 should not be applied in any context and notes those criteria are disabled in the VCI. ClinGen's current page provides versioned recommendations. A VCEP protocol includes pilot validation requirements for proposed specifications; a specification's existence is not evidence that SIRALOOM implemented it correctly.

### 3.14 Candidate ranking, case-level interpretation and reportability

**Ranking question:** which eligible variants/genes deserve human review first? Ranking features might include phenotype fit, consequence, inheritance, population, gene-disease validity and QC. Every feature, weight, missingness policy and algorithm version must be inspectable. Ranking is not probability unless a separately validated calibrated model justifies that claim.

**Case interpretation question:** do the variant and disease evidence plausibly explain this patient's clinical indication? This can differ from variant classification. A pathogenic variant may be incidental or unrelated to the indication; a VUS is not a diagnosis. Preserve alternatives, limitations, negative findings, unresolved evidence and reviewer-written narrative.

**Reportability question:** should this finding appear under this assay's validated reporting policy and consent/secondary-finding policy? Reportability is a separate controlled decision from ranking and classification. Scope, penetrance/clinical relevance policy, consent, age/secondary finding rules, and jurisdictional requirements are laboratory governance decisions.

**Output:** ranked candidates with explanations; interpretation draft tied to specific analysis/evidence IDs; reportability decisions with policy version and reviewer status.

### 3.15 Report assembly, review, authorization and sign-out

**Laboratory activity.** The reporting professional ensures identifiers, assay scope, result representation, classification rationale, relevant limitations and interpretation are correct. Authorized personnel approve the exact version for release.

**Inputs:** approved case context; analysis snapshot; variants and transcript/HGVS; classification/evidence; assay method and limitations; reference/tool/resource manifest; reportability and consent policy; reviewers/signatories; recipient/delivery rules.

**Processing:** render a structured report from persisted, validated records; identify draft/review-ready/approved/signed-out states; validate required fields and cross-record linkage; require designated reviewer and signer roles and any separation-of-duties rules; bind approval to immutable report version and exact analysis; sign or seal artifact according to policy; store rendered artifact and structured source; audit access, downloads, release recipient, time and status. A generated PDF is not a signed report. A background task success is not signout.

**Report content, depending on assay/policy:** patient/specimen/accession; test indication/scope/method; genome build and analysis limitations; normalized allele, transcript and HGVS; zygosity; classification and evidence summary; phenotype/inheritance context; QC/technical limitations; unassessed variant classes/regions; interpretation; references; report author/reviewer/signatory; version/date; amendment/supersession linkage; contact details where required by local policy.

**FHIR:** HL7 Genomics Reporting IG v3.0.0 is currently published for FHIR R4 and defines structured data profiles including report, observations/variants and relationships. It explicitly focuses on data structures and does not define all order/request/create/approve/route/deliver/amend workflow processes. Conformance requires validating actual resources against the exact IG package and terminology dependencies; it cannot be inferred from “FHIR-like JSON.”

**Output:** a versioned, validated draft or final report artifact and authorization event tied to the exact analysis, report content hash, evidence and resource manifest.

**Next:** only authorized final state can be delivered. Post-signout changes require a new report version/amendment/withdrawal under policy; no silent edit.

**Failure/recovery:** rendering failure leaves report review/signout incomplete; durable retry must not duplicate report versions or approval events; if artifact storage succeeds but DB transaction fails, reconcile idempotently. Concurrent edits invalidate stale approval or force conflict handling.

**SIRALOOM trace points:** review queue and decisions in `backend/app/api/v1/review.py`; report and finalization modules/routes; signout locking, artifact integrity and provenance; report UI. Existing automated tests cover review/report contracts and recovery pieces, but deployed lab identity, configured storage, actual signed artifact retrieval and end-to-end two-person workflow remain separate deployment checks.

### 3.16 Delivery, archival, amendment and case closure

**Laboratory activity.** Release the authorized report to the permitted recipient through an approved channel; preserve the exact result and underlying evidence under retention policy; close or hold the case according to outstanding work.

**Inputs:** signed report, recipient authorization, delivery method, retention schedule, archive manifest, access/export rules.

**Processing:** verify report final state and artifact checksum; enforce tenant/case permissions at download; record recipient and delivery outcome; keep original VCF, all derived artifacts, resource manifest, evidence and audit lineage; control corrections, withdrawal, amendment and supersession; document closure and reopen reasons.

**Output:** retrievable archive and delivery record, with version lineage and audit evidence.

**Next:** subsequent access is read-only as appropriate; a new evidence/resource/phenotype event creates a new reanalysis, not mutation of history.

### 3.17 Reanalysis, resource change and historical reproducibility

**Triggers:** clinician/lab request, changed phenotype/family data, new clinically relevant evidence, variant reclassification, new approved resource release, updated reference/annotation/rules, or an identified prior error. Trigger must identify reason and authority.

**Inputs:** immutable parent analysis/report; change event; child analysis request; exact new resource/software manifest; dependency graph; reuse policy; authorization.

**Processing:** create child analysis linked to parent; freeze old outputs; compare resource manifest and stage dependencies; recompute only unaffected outputs when their full input/resource/configuration hashes match; invalidate dependent stages otherwise; never silently adopt rejected or unapproved resources; expose queued/running/blocked/retryable/complete/review-required status; prevent duplicate active children; produce machine-readable and human-readable change report; route material changes to review and amendment.

**Output:** immutable child analysis, change report, comparison provenance, reviewer decisions and, if approved, amended report linked to the prior signed report.

**Failures:** dispatch/publish failures remain queued/retryable and visible; worker loss resumes from durable checkpoints; duplicate delivery is idempotent; new release failure does not erase prior evidence; no automatic fallback to a different resource.

**SIRALOOM trace points:** `/api/v1/reanalysis` in `backend/app/api/v1/reanalysis.py`; `backend/app/domain/reanalysis.py`; analysis resource planning; `_apply_reanalysis_reuse` and workflow terminal logic in `backend/app/workflows/variant.py`; frontend candidate and child status. Current test evidence must be read from latest ledger/CI and does not prove live deployment recovery.

## 4. Resource ecosystem: what each resource is and is not

The priority column answers whether a resource class is needed for a safe declared workflow; it does not mean the named vendor is the only option. “Execution status” must be maintained per laboratory/profile: discovered, catalogued, configured, installed/reachable, integrity-verified, technically qualified, lab-approved, pinned, executed, persisted and independently validated are separate states.

| Priority / category | Examples and purpose | Inputs/outputs that matter | Qualification and limitations |
|---|---|---|---|
| P0 — reference assembly | GRCh37/GRCh38 reference FASTA, `.fai`, sequence dictionary, contig aliases, checksum/manifest | Assembly/contig sequence to validate REF and normalize coordinates | Exact identity/checksum, contig equivalence and tool compatibility; never silently interchange assemblies or liftover |
| P0 — VCF parser/validator | HTSlib/bcftools or maintained VCF library | VCF headers/records/genotypes to structured validation findings | Test declared versions, malformed files, allele classes, multi-sample and genotype semantics; acceptance does not prove caller accuracy |
| P0 — normalizer | BCFtools `norm` plus pinned HTSlib | Accepted VCF + FASTA → normalized records/artifact/mapping | Version/reference/config pinned; test REF mismatch, repeat indels, multiallelic INFO/FORMAT remapping, phase and idempotence |
| P0 — annotation | Local VEP/cache or qualified contracted provider | normalized variants/build → transcript consequences, IDs and optional plugins | VEP release/cache/transcript/reference compatibility; offline mode and licensing/storage; complete per-transcript provenance; no clinical classification implied |
| P0 — population evidence | gnomAD versioned local/API dataset and optional approved local cohorts | normalized allele → source AC/AN/AF/population/coverage status | Exact release/build/allele match; missing vs zero; ancestry representativeness; callability/filters; public API may be unsuitable for bulk or private identifiers |
| P0 — clinical assertions | ClinVar plus applicable expert curation sources | variant/disease query → submission records, review/conflict/assertion metadata | Preserve SCV/RCV/VCV identity and review status; conflicts are not resolved by database aggregation |
| P0 — interpretation framework | ACMG/AMP baseline plus applicable ClinGen general/VCEP specification | criterion evidence + scoped rules → proposed five-tier classification | Rule version, condition/gene scope, validation set, criterion independence, human review; unsupported criteria must remain unresolved |
| P0 — phenotype vocabulary | HPO ontology plus compatible HPOA (if used) | clinical findings → validated IDs, disease annotations, matching features | Ontology and annotation releases pinned independently; preserve negation/onset and mapping; score is not probability |
| P0 — identity and audit | Identity provider, DB-backed ACL, immutable audit/event records | authenticated principal/action → allow/deny plus attributed history | live auth expiry/revocation, direct object and cross-tenant tests, least privilege, no bypass in workers/downloads |
| P0 — workflow, database and storage | PostgreSQL, object/file storage, Celery/broker, outbox/replay, backup | durable stages and artifacts → recoverable state | transaction/idempotency/failure injection, tenant namespaces, checksum, storage quota, backup restore and worker restart |
| P0 — validation datasets | GIAB/NIST benchmark appropriate to scope and independent fixtures | callset + truth + benchmark regions → TP/FP/FN and metrics | Pin sample/release/build/confidence regions/tool; comparator scope limits claims; GIAB is not clinical interpretation validation |
| P1 — disease-gene validity | ClinGen gene–disease validity, GenCC, PanelApp, disease panels | gene-condition assertions → source-specific status and evidence | Do not map divergent source vocabularies without documented mapping; panels are context, not variant pathogenicity |
| P1 — transcript harmonization | MANE Select/Plus Clinical, RefSeq, Ensembl/GENCODE, HGVS | allele+transcript → stable cross-database descriptions | exact release and assembly; display/report selection policy and exceptions; unversioned transcript IDs unsafe |
| P1 — additional phenotype/clinical knowledge | Orphanet, Monarch, OMIM, curated disease resources | disease IDs, phenotype links and inheritance/mechanism | licenses, access, release cadence and provenance vary; no assumption of redistributable bulk copy |
| P1 — variant identifier interoperability | GA4GH VRS, HGVS, SPDI/NCBI Variation Services as applicable | normalized sequence allele → identifier/representations | distinct representation layers, assembly and transcript context; test matching and version contracts |
| P1 — benchmark extensibility | GIAB difficult-region and SV benchmarks, hap.py/RTG vcfeval or appropriate comparator | callset and truth-set → class/context metrics | choose correct comparator for representation and benchmark; do not mix benchmark regions or variant classes without justification |
| P2 — computational predictions | SpliceAI, REVEL, conservation, other calibrated predictor | variant/transcript/context → score and metadata | version, threshold provenance, calibration, licensing and correlated evidence; do not directly map arbitrary scores to criteria |
| P2 — dosage/SV/CNV | ClinGen dosage sensitivity; gnomAD-SV; validated CNV/SV pipeline | SV/CNV representation and QC → class-specific evidence | Specialized calling/representation and assay validation; outside small-SNV/indel release unless separately qualified |
| P2 — functional evidence | curated functional datasets, literature and lab assays | experimental result and controls → quality-assessed evidence | model system, controls, reproducibility and disease mechanism; evidence needs human curation |
| P2 — paid/restricted disease resources | OMIM or licensed laboratory knowledge bases | licensed API/export → disease/allele knowledge | contract/license and retention/redistribution constraints must be checked before caching or exposing data |
| P0 — report/interoperability structure | HL7 FHIR Genomics Reporting IG v3.0.0 (FHIR R4), optionally GA4GH Phenopackets for phenotype exchange | structured observations/report and references | validate resources against exact package/profiles; IG defines report data structures, not the entire lab approval workflow |

## 5. Methods and algorithms: permitted claims and guardrails

### Variant normalization and identity

The implementation must identify the sequence allele against a known reference; left alignment/parsimonious representation addresses equivalent indel descriptions in repetitive context. Multiallelic splitting is a transformation requiring correct allele-index field remapping. Preserve original representation and mapping. HGVS transcript descriptions are transcript-dependent; VRS identifiers provide a distinct computable representation identity layer. Never claim two variants match solely because a text string or rsID matches.

### Consequence annotation

Use Sequence Ontology consequence terms returned by the pinned annotator; retain transcript-level results. “Most severe” is a display convention or configured selection, not proof of biologically relevant transcript. MANE is a useful clinical harmonization reference, not permission to discard alternate disease-relevant transcripts.

### Population maximum credible frequency

Some interpretation specifications use disease-specific maximum credible allele-frequency reasoning. It requires disease prevalence/incidence, penetrance, genetic/locus heterogeneity, inheritance, allelic contribution and dataset ancestry/coverage assumptions. No universal “rare means pathogenic” cutoff is justified. Store the calculation inputs, derivation, version and reviewer approval; otherwise do not apply as a criterion.

### Phenotype similarity

Ontology-based similarity can use graph structure and information content, but its output depends on ontology, disease annotation release, corpus frequencies, term direction/negation and algorithm settings. Similarity aids prioritization. It is not a calibrated diagnosis probability unless an independently validated probabilistic model and applicable deployment population support that exact claim.

### ACMG/AMP criteria and combination

Criteria are evidence codes with prerequisites; criterion extraction and classification combination are separate. A rules engine needs explicit applicability and evidence provenance. ClinGen general recommendations and gene/disease-specific VCEP specifications can refine criteria. If a specification says a threshold or evidence type is inappropriate, the generic rule must not override it. Preserve conflicts; a VUS is not evidence of no disease, and a proposed P/LP category is not patient-level diagnosis or report authorization.

### Benchmarking

For technical callset benchmarking, identify truth sample, assay/platform compatibility, reference build, benchmark release, benchmark/confidence regions, included variant types, comparator and parameters. Report TP/FP/FN and precision/recall only for the evaluated scope, with confidence intervals where appropriate. GIAB benchmarks do not validate annotation truth, phenotype match, ACMG interpretation, clinical utility, wet-lab assay performance or sign-out.

## 6. Failure states and safe next actions

| Condition | Proper interpretation | Workflow response | Retry? |
|---|---|---|---|
| malformed VCF / incompatible header | invalid input | reject with file/line evidence; preserve source | No, unless corrected replacement is newly uploaded |
| unsupported SV, CNV, breakend, gVCF block | outside declared pipeline | explicit unsupported route/block and next supported process | Not by repeating same pipeline |
| assembly unclear / REF mismatch | scientific identity unresolved | block normalization and request correct assembly/reference/source | only after corrected/approved evidence |
| missing/unapproved reference or resource | dependency not ready | BLOCKED/WAIT_FOR_RESOURCE with exact resource and owner | yes when the same approved pin becomes available |
| provider timeout/429/5xx | transient external failure | bounded retry; preserve attempt and error; do not create zero evidence | Yes, bounded, honoring retry policy |
| invalid provider schema/counts | provider response unusable | typed provider failure; retain response digest safely | typically no blind retry; alert/qualify provider |
| partial valid annotations and one failed source | partial evidence state | persist completed valid source outputs, mark source unavailable, apply policy about review/block | only missing stage/source; avoid duplicate prior outputs |
| low/unknown technical QC | call may be unreliable | flag/review/block per assay SOP; do not alter pathogenicity label | no retry absent new input/tool issue |
| contradictory evidence | scientific conflict | preserve alternatives; require review or unclassified state | not infrastructure retry |
| DB write failed after compute | result not durable | do not report stage complete; retry persistence idempotently using same inputs/artifact | yes, after safe reconciliation |
| artifact stored but state not committed | partial external side effect | reconcile by stable idempotency key and digest; do not duplicate report | yes, idempotent |
| worker died before/after acknowledgment | execution uncertain | durable lease/recovery checks stage/run lineage, then safely re-drive | yes, once authoritative state checked |
| report rendered but not authorized | draft only | retain draft; do not make downloadable as final/signed | rendering may retry, authorization needs human action |
| signout/artifact mismatch | integrity/authorization failure | block delivery; preserve audit and escalate | only after controlled repair/reapproval |

The system of record should be the transactional database plus durable artifact store and recoverable dispatch pattern. A queue message alone is not state. A successful broker publish and DB commit are not automatically atomic; use a transactional outbox/equivalent or a durable reconciliation mechanism. Retrying must not duplicate evidence, audit events, signed reports, or child analyses.

## 7. Release-scope boundary for SIRALOOM

### Appropriate initial supported scope to prove

- Existing VCF input; germline rare-disease interpretation.
- SNVs and small indels (plus MNV only if actual annotation/classification and fixtures demonstrate support).
- Explicit and qualified GRCh37/GRCh38 only if each reference resource is pinned and validated.
- Reference-aware validation/normalization, transcript-level annotation, population evidence, versioned phenotype inputs, evidence provenance, supported inheritance logic, restricted ACMG/AMP/ClinGen criteria, human review, authorized report workflow, archival and reproducible reanalysis.
- Sample genotype support only to the degree multi-sample, phased/unphased, missing genotype, ploidy and FORMAT semantics are verified.

### Must be blocked or explicitly separate until validated

- FASTQ sequencing, alignment, variant calling, joint genotyping and assay-level QC.
- CNV/SV/breakend and complex rearrangement interpretation.
- Repeat expansions, mitochondrial variant analysis, mosaic/somatic analysis, pharmacogenomics and incidental/secondary findings unless specifically scoped and independently implemented/validated.
- Unsupported caller-specific semantics, unresolved assemblies, malformed sample mapping, absent references, and unqualified external services.

The source format may legally encode SVs while the product does not support SV interpretation. Syntactic acceptance must never imply analytical support. Unsupported records must be visible and safely routed/blocked rather than silently omitted from a “complete” analysis.

## 8. Standards, official resources and source register

Access dates for live pages: 2026-10-24. Resource releases and website contents change; an analysis must pin the data actually used. This register identifies source authority and intended use. It is not a substitute for reading licensed normative text or the laboratory's applicable regulations/SOPs.

| Source | Publisher/type and current finding used here | Direct source |
|---|---|---|
| ISO 15189:2022 | International standard, medical laboratory quality and competence; published edition 4 (2022-12). Full normative text is paid/copyrighted; this guide does not paraphrase clause-by-clause requirements or claim conformity | [ISO 15189:2022 catalogue/abstract](https://www.iso.org/standard/15189) |
| ACMG/AMP Richards et al. 2015 | Peer-reviewed joint consensus; five Mendelian variant categories and evidence framework; clinical laboratory scope | [PubMed record](https://pubmed.ncbi.nlm.nih.gov/25741868/), [open PMC article](https://pmc.ncbi.nlm.nih.gov/articles/pmid/25741868/) |
| ACMG Laboratory Standards | ACMG technical standards are professional/educational guidance, maintained and periodically revised; ACMG states voluntary adherence does not guarantee outcome | [ACMG Genetics Laboratory Standards](https://www.acmg.net/genetics-laboratory-standards/) |
| CAP NGS worksheets | College of American Pathologists education/checklist aids for assay design, validation, quality management, bioinformatics/IT, interpretation/reporting | [CAP NGS worksheets](https://www.cap.org/education/practice-hubs/next-generation-sequencing-ngs-worksheets/) |
| HTS VCF specifications | GA4GH Large Scale Genomics workstream format specifications; repository identifies VCFv4.5 as canonical and prior VCF versions separately | [HTS specifications](https://github.com/samtools/hts-specs), [VCF specification index](https://samtools.github.io/hts-specs/) |
| BCFtools | Official documentation for tool options including reference-aware normalization and multiallelic handling | [BCFtools manual](https://samtools.github.io/bcftools/bcftools.html) |
| Ensembl VEP | Official software/cache docs; cache version should correspond to VEP version; local cache supports offline operation and source-specific limitations | [VEP documentation](https://www.ensembl.org/info/docs/tools/vep/index.html), [cache/data source guide](https://www.ensembl.org/info/docs/tools/vep/script/vep_cache.html), [options including MANE](https://www.ensembl.org/info/docs/tools/vep/script/vep_options.html) |
| MANE | Joint NCBI/EMBL-EBI matched RefSeq/Ensembl transcripts; MANE Select and Plus Clinical definitions | [NCBI MANE](https://www.ncbi.nlm.nih.gov/refseq/MANE/) |
| ClinVar | NCBI archive of submitted clinical assertions; records and aggregation; review status and conflicts | [What is ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/intro/), [review status](https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/), [validation caveats](https://www.ncbi.nlm.nih.gov/clinvar/docs/validation/) |
| ClinGen SVI/VCEP | Versioned general and expert-panel specifications for ACMG/AMP application | [Variant classification guidance](https://clinicalgenome.org/tools/clingen-variant-classification-guidance/), [VCEP procedures/resources](https://www.clinicalgenome.org/tools/clingen-variant-curation-expert-panel-procedures-and-resources/), [CSpec Registry](https://cspec.genome.network/cspec/ui/svi/) |
| ClinGen gene–disease validity | Framework assessing evidence for/refuting gene–disease claim | [Gene-disease validity](https://clinicalgenome.org/curation-activities/gene-disease-validity/) |
| ClinGen dosage sensitivity | Gene dosage evidence process; relevant for CNV interpretation, not generic SNV classification | [Dosage sensitivity](https://clinicalgenome.org/curation-activities/dosage-sensitivity/), [methods](https://clinicalgenome.org/curation-activities/dosage-sensitivity/dosage-sensitivity-curation/) |
| gnomAD | Population variation resource; versioned releases and provider semantics; 2026-09 changelog says v4.1.2 corrected constraint ranks only, frequency unchanged from v4.1.1 | [gnomAD changelog](https://gnomad.broadinstitute.org/news/changelog/), [v4.1 release details](https://gnomad.broadinstitute.org/news/2024-04-gnomad-v4-1) |
| HPO | Ontology for phenotype terms; separate disease annotations and downloadable HPOA/summary products | [HPO portal](https://obophenotype.github.io/human-phenotype-ontology/), [HPO annotations](https://obophenotype.github.io/human-phenotype-ontology/annotations/introduction/), [release files](https://github.com/obophenotype/human-phenotype-ontology/releases) |
| NIST GIAB | Reference materials and versioned benchmark sets; benchmark scope and confident regions are product-specific; current NIST page lists HG002 v5.0q products and warns about usage instructions | [GIAB](https://www.nist.gov/programs-projects/genome-bottle), [GIAB FAQ](https://www.nist.gov/programs-projects/faqs-genome-bottle) |
| GA4GH VRS | Computational representation specification; distinct from VCF and HGVS strings | [GA4GH VRS product](https://www.ga4gh.org/product/variation-representation/), [VRS docs](https://vrs.ga4gh.org/) |
| HL7 FHIR Genomics Reporting | Current published IG is v3.0.0, FHIR R4; data structures only; it explicitly does not define request/create/approve/route/delivery/amend workflow | [IG v3.0.0 home](https://hl7.org/fhir/uv/genomics-reporting/), [general reporting](https://hl7.org/fhir/uv/genomics-reporting/general.html) |
| ClinGen functional evidence | SVI recommendations for PS3/BS3; evaluate mechanism, assay class, specific assay validity and variant evidence | [PS3/BS3 recommendations](https://clinicalgenome.org/docs/recommendations-for-application-of-the-functional-evidence-ps3-bs3-criterion-using-the-acmg-amp-sequence-variant-interpretation/) |
| ClinGen standardized evidence text | Versioned text guidance (version 3 dated Dec 2025 in source) for transparent criterion explanations; criteria remain VCEP-dependent | [Standardized text page](https://clinicalgenome.org/docs/standardized-text-for-clingen-variant-curation-expert-panels/) |

### Additional candidate resources: initial disposition

- **GenCC:** useful aggregation of gene–disease validity assertions. Preserve contributor and classification; do not assume a single harmonized truth. Qualify current data access/API and licenses before integration.
- **PanelApp:** curated gene panels with evidence/status and jurisdiction-specific context; useful for panel scope, not a variant classification. Pin panel version and gene confidence.
- **Orphanet:** disease nomenclature/prevalence/phenotype context; confirm current access and redistribution conditions.
- **OMIM:** valuable disease-gene and allelic context; access and content licenses can restrict bulk integration and redistribution. Do not scrape or cache without permission.
- **Monarch Initiative:** phenotype-disease/gene knowledge integration; verify data release, source provenance and mapping rules before using a ranking score.
- **SpliceAI / REVEL / conservation resources:** P2 predictor integrations until tool/resource versions, calibrated cutoffs, licensing, transcript identity, local compute and criterion policy are documented and validated.
- **ClinGen dosage / gnomAD-SV / specialized SV tools:** outside current small-variant interpretation until the product has a separate validated SV/CNV representation, caller input contract and truth benchmark.
- **Phenopackets:** potential phenotype/family data exchange model; does not replace a lab case/accession or report authorization workflow.

For candidates above, this document records discovery and scientific purpose, not a working integration or a blanket license grant. Before activation, create/update the repository's machine-readable resource contract with official endpoint/file schema, release, license, exact inputs/outputs, errors, checksum and qualification tests.


### Existing SIRALOOM adapter contracts observed in source

The following is a code inspection, not a claim that the production resource is installed. “Adapter implemented” and “laboratory qualified” are deliberately different columns. Exact configuration is drawn from current provider constructors/contracts and should be pinned in each analysis manifest.

| Provider / source path | Executable contract and request | Adapter output / status semantics | Important limits to validate |
|---|---|---|---|
| BCFtools normalization — `backend/app/domain/vcf_tools.py` | Local executable, reference FASTA and indexes, expected tool version, source VCF; production wrapper creates normalized/indexed output | Artifact and validation/command metadata; wrapper fails on tool/reference mismatch | Confirm actual installed version/checksum, exact arguments, REF check, symbolic handling, indexes, multiallelic remapping, VCF fixtures, cleanup and durability |
| VEP — `backend/app/adapters/annotation/vep.py`; registry qualification in `backend/app/domain/resource_qualification.py`; manifest generator `scripts/generate_vep_cache_manifest.py` | Local/FILE contract pins absolute `toolchain.vep_binary`, `cache_dir` and `cache_manifest`; VEP release, cache version, species and GRCh37/GRCh38 assembly; `vep_binary_sha256`, `cache_manifest_sha256` and `cache_artifact_sha256`; optional FASTA. Manifest schema `siraloom.vep-cache-manifest.v1` records cache release/species/assembly, source artifact SHA-256 and every relative file path, byte size and SHA-256. Generate from the installed cache with the script described below; keep manifest outside cache tree. | Qualification and provider startup verify the manifest digest, source artifact binding, exact cache file set/content, and binary digest before checking VEP's version and loading the cache offline with `--show_cache_info`. Annotation runs offline (`--offline --cache --format vcf --json`) and explicitly requests `--canonical`, `--symbol`, and `--transcript_version`; it requests `--mane` only for GRCh38 and `--hgvs --hgvsg` only when the execution contract supplies FASTA. These optional fields are not enabled by default; the effective options are persisted in annotation provenance and cannot be overridden through `extra_args`. Response records are allele-matched; every transcript consequence is retained. Display selection requires a unique MANE Select, else a unique canonical transcript; ambiguity stays unresolved. | This checks byte identity and technical availability, not annotation accuracy. The laboratory must independently approve that the installed cache tree was derived from the registered source artifact and that its release/assembly are appropriate. Full cache hashing may be I/O-intensive; no laboratory-scale performance measurement or known-answer annotation benchmark has been run. The provider does not download/install resources or claim scientific qualification. |
| GeneBe — `backend/app/adapters/annotation/genebe.py` | Contracted HTTP endpoint and API credentials; list of `chr,pos,ref,alt`; genome query parameter; bounded batch and configured timeout/retry | Provider response normalized and provenance/fingerprint stored; HTTP 408/429/5xx classified transiently by adapter | Public remote provider transmits variant-level genomic data; trial-only policy and privacy/network approval must be enforced; service release semantics, terms, response schema and rate/timeout qualification; not suitable for private lab data unless explicitly approved |
| gnomAD GraphQL — `backend/app/adapters/population/gnomad.py` | Contracted GraphQL endpoint + dataset selector; canonical `chrom:pos:ref:alt` and build; query requests joint/exome/genome AC, AN, homozygote count and population rows | Population observations with request fingerprint, response digest/time, dataset selector, build, provider and execution scope; typed unavailable/not-found/error handling; frequency requires valid positive AN | Public API is documented in code as targeted not bulk; exact API/dataset release semantics and rate behavior; API may expose queried variant but avoid patient identifiers; dataset coverage and allele matching qualification |
| gnomAD/local population VCF — same module | Local tabix VCF plus `.tbi/.csi` and a governed INFO-field mapping/population labels | Exact-locus allele observation with counts/frequency and resource provenance | Verify release, build, tabix index, contig policy, Number=A fields, missing AN/AF, duplicated records and AC/AN/AF consistency; production scale/storage qualification |
| Secondary/local population VCF — `backend/app/adapters/population/secondary.py` | Local tabix VCF; explicit provider ID from allowed set; pinned dataset version; INFO mappings for AF or AC+AN; population label/code; tabix binary and contig policy | Exact position/ref/alt match, selects allele-indexed array by ALT index, returns one observation or no hit | Source-specific field semantics and checksums must be qualified. Adapter now rejects negative/inconsistent AC/AN and invalid AF; it withholds AF unless AN is positive and checks a supplied AF against AC/AN within the source text precision. This is regression-tested software behavior, not qualification of any particular population dataset |
| HPO OBO — `backend/app/adapters/phenotype/hpo_obo.py` | Local pinned OBO file, expected SHA-256 and release date; execution contract with local artifact and checksum/release | Parses supported HPO OBO format, verifies ontology/release/digest, resolves current/alternate/obsolete IDs, builds `is_a` ancestry only | No public network lookup; other OBO relations intentionally are not treated as `is_a`; test against approved exact release and obsolete/ambiguous terms; does not itself implement a clinically validated similarity model |
| HPOA — `backend/app/adapters/phenotype/hpoa.py` | Local compressed/plain TSV; SHA-256; HPOA date release and matching HPO ontology release | Disease ID/name, HPO term, qualifier/negation, evidence, reference, onset, frequency, sex, modifiers, aspect and biocuration; query by disease | HPOA is not the ontology; verify the exact public HPOA artifact format/version/license and ontology compatibility; adapter supplies associations but does not assert gene–disease validity or calculate a patient diagnosis |
| ClinVar VCV XML — `backend/app/adapters/evidence/clinvar.py` | Local-only, staged `ClinVarVCVRelease_*.xml.gz`; resource/version/qualification/contract hashes; GRCh37/38; derived index root | Builds deterministic SQLite index from authoritative XML and queries exact allele; preserves record type/accession/version, VCV/RCV linkage, assertion, condition, submitter, review status, assertion method and source-record digest | Verify real XML release extraction/parser against official data; VCV aggregates may not resolve condition-specific conflicts; local index is acceleration, not authoritative source; preserve artifact license/retention and rebuild behavior |
| ClinGen CSpec — `backend/app/adapters/clingen/cspec_provider.py` + `cspec.py` | Governed HTTP(S) API endpoint, timeout; retrieve by exact specification ID/version or resolve current using exactly one governed HGNC gene or MONDO disease ID | Normalized versioned specification snapshot with raw/provenance; adapter retrieves specification but explicitly does not classify | Current resolution can drift unless the resulting version is pinned in analysis; network/API response and specification applicability/approval must be checked before execution |
| ClinGen Gene-Disease Validity — `backend/app/adapters/clingen/gene_disease_validity.py` | Local/file official CSV/TSV; explicit delimiter; query by gene symbol | Assertion preserves HGNC/MONDO, disease, MOI, SOP, classification, report/date/expert panel, payload and row hash | Symbol aliases/case and multiple disease rows need careful mapping; local file release/checksum/official source and download license must be pinned; it is contextual gene–disease evidence, not variant pathogenicity |
| ClinGen Variant Pathogenicity — `backend/app/adapters/clingen/variant_pathogenicity.py` | Governed ERepo API or local qualified data; query requires CAID, ClinVar Variation ID, or gene; HGVS supports matching in the local route | Curated assertion records with identifiers, classifications and source records | Verify current ERepo API contract, returned full classification documents, identity match and curation status; never map an assertion automatically to an ACMG criterion without review/specification |

#### Generate and approve a VEP cache integrity manifest

After installing a cache from the laboratory-approved archive, independently verify the archive checksum and extraction procedure. Then generate an inventory manifest outside the cache tree (replace the example paths and digest with the laboratory's actual values):

```sh
.venv/bin/python scripts/generate_vep_cache_manifest.py \
  --cache-dir /lab/resources/vep/cache \
  --cache-version 115 \
  --species homo_sapiens \
  --assembly GRCh38 \
  --source-artifact-sha256 '64-character-approved-archive-sha256' \
  --output /lab/resources/vep/cache-115-GRCh38.manifest.json
```

The printed digest is the manifest SHA-256. Record that value and the archive SHA-256 in the governed VEP execution contract as `cache_manifest_sha256` and `cache_artifact_sha256`; pin `vep_binary_sha256` from the laboratory-approved executable. The manifest generator inventories installed bytes but does not prove that the tree came from the claimed archive, assess annotation accuracy, or qualify the cache for clinical use. The application rehashes every cache file at preflight, so measure this I/O cost against the laboratory's actual cache before activation.

**Confirmed defect and correction in this work:** the secondary tabix provider previously computed `AC/AN` whenever AN was nonzero, which allowed a negative denominator to yield an invalid AF; it also passed through a source AF without checking count consistency or positive AN. Downstream `qualified_allele_frequency` filtered some displayed values but did not prevent invalid raw observations from being persisted. The adapter now rejects invalid counts/frequencies and inconsistencies, withholds AF for missing/zero AN, and checks legitimate rounded AF against AC/AN at the precision represented in the source VCF. The focused regression result is recorded in the engineering ledger. Dataset/build/index qualification remains separate.

## 9. Readiness questions that must be answered with evidence

For each deployed laboratory profile, a reviewer should be able to answer “yes, with a linked record” to:

1. Is the user authenticated, the lab membership active and this exact case/object authorized at the API, worker and download boundary?
2. Does this VCF belong to the intended specimen/sample, and are the original bytes retained and checksummed?
3. What exact assembly and reference checksum were used? Was REF checked and was any record excluded?
4. Which variant classes and VCF semantics are qualified? How are unsupported records shown to the laboratory?
5. Which assay policy evaluated QC, and what evidence was missing/not assessable?
6. Which annotator, transcript release, cache, plugins and configuration produced each consequence?
7. Which exact population and clinical resources supplied each observation/assertion, and what does missing mean for each provider?
8. Which phenotype terms were submitted, normalized, negated/absent, mapped and unresolved, against which ontology/annotation release?
9. Which disease mechanism and inheritance assumptions apply? Which family genotypes/phase are known versus unknown?
10. Which classification specification and criteria were used, with evidence IDs and conflicts? Which criteria were outside support?
11. Who reviewed and authorized this exact report version and analysis? Can signed bytes and lineage be checked?
12. Can a crash at each stage recover without claiming success, losing valid outputs, or duplicating a report/decision?
13. Can the lab restore its database and artifacts from backup and demonstrate tenant isolation after restoration?
14. Can the scientific output be reproduced from pinned inputs/resources, and has the claimed variant scope been benchmarked independently?

Any “no,” “unknown,” or “not tested” must have a status and consequence. A deployment should be described as a laboratory evaluation candidate only for the capabilities actually evidenced; do not use “production-ready,” “clinically validated,” ISO-accredited, or regulatory-compliant as a software-only conclusion.

## 10. Current research limitations and next evidence work

- The research covers a broad germline workflow and primary source landscape, not every jurisdiction's legal requirements, every laboratory SOP, every disease-specific specification, or every commercial license. Those require the target laboratory's jurisdiction, assay and approved resource contracts.
- The full normative ISO 15189 text is not freely accessible through the public abstract; this document does not assert clause compliance.
- A resource's official page or current release is not the same as local installation, checksum verification, technical qualification, approval, or execution.
- The code-path references identify current implementation entry points but the detailed historical end-to-end matrix has older sections. A route-by-route refresh and executable end-to-end test evidence remain needed.
- Live Firebase/browser identity, actual two-laboratory deployment isolation, lab-owned object storage, real report delivery/sign-out and backup restore require configured lab/test infrastructure.
- Independent GIAB benchmarking requires an approved test dataset, compatible callset/test method, exact benchmark package and comparison tool; none of these results are asserted by this research document.
- HPO similarity, candidate ranking, every ACMG criterion, all disease-specific specifications, predictor calibration and clinical validity are not established by the existence of their adapters or schemas.

**Research outcome:** This is a substantial workflow and resource reference for the declared VCF-in, germline small-variant interpretation boundary. It is not the end-to-end completion of Phase A, scientific validation, laboratory qualification, or deployment readiness. The next engineering work should reconcile the existing traceability matrix with current code and turn each P0 workflow row into a tested requirement with real artifacts and observed failure/recovery evidence.

## 11. Original-to-normalized allele lineage

The official [BCFtools 1.19 `norm` manual](https://raw.githubusercontent.com/samtools/bcftools/1.19/doc/bcftools.txt) documents `--old-rec-tag` as a source-record INFO annotation containing source CHROM, POS, REF, ALT and the used source ALT index. SIRALOOM declares this reserved field as `Number=.`/`Type=String` before execution; variable cardinality is necessary because a multiallelic source ALT string itself contains commas. Since BCFtools may omit `--old-rec-tag` when a biallelic row is unchanged, SIRALOOM inserts its source mapping on biallelic rows before normalization. Multiallelic rows are left untagged until BCFtools splits them, so child rows receive their own source ALT index. Existing collisions are rejected. A controlled replay can preserve a previously emitted SIRALOOM mapping only when explicitly enabled and after validating its header and per-record mapping.

After the actual pinned BCFtools run, `iter_normalized_vcf` decodes the original representation and ALT index into `CanonicalVariant`, and normalization partition metadata stores an analysis-scoped mapping from canonical variant ID to source record. The normalized artifact is versioned separately (`4.0`, artifact identity v4) so an older artifact without source mapping cannot be reused under the new contract. The mapping refers to the persisted sequence-routed input record; for GVCF routing, the original uploaded artifact and routed artifact lineage remain linked in normalized artifact metadata. It does not claim a mapping for records routed outside the supported small-variant stream.

**Evidence/status:** actual BCFtools 1.19 synthetic tests verify multiallelic ALT indices, ordinary biallelic mapping, strict VCF validation, streaming decode, partition persistence, malformed mapping rejection and idempotent re-normalization. This is source lineage software evidence, not independent truth-set concordance or clinical qualification.
