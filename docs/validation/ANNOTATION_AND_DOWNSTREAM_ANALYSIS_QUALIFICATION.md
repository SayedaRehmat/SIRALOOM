# Annotation and downstream genomic analysis: qualification plan

**Status snapshot:** 2026-11-07  
**Baseline:** `main` at `226dd645d5ac4047e3478fd67b6b550af9633b55`  
**Implementation increment:** PR #302, `feature/annotation-downstream-clinical-foundation`  
**Scope:** Germline small-variant interpretation from a laboratory-supplied, validated and normalized VCF. This is not a sequencing, alignment, variant-calling, or clinical sign-out system.

> This document is an engineering and scientific qualification plan. Source implementation, unit tests, CI, a benchmark run, scientific review, and laboratory validation are separate evidence states. Nothing here establishes accreditation, regulatory authorization, or fitness for clinical use.

## 1. Governing design rules

1. Preserve the frozen SIRALOOM architecture. Extend existing adapters, domain services, resource governance, workflow stages, provenance, and audit records; do not introduce parallel provider registries or a second workflow engine.
2. A provider response is an observation, not a clinical conclusion. Annotation, population observations, database assertions, phenotype matches, inheritance evidence, ACMG criteria, variant classification, candidate relevance, reportability, and sign-out are distinct data products.
3. Every scientific resource is organization-governed and bound to an exact release/version, source, assembly where relevant, checksum or publisher release identity, qualification, license/access decision, and execution record. Discovery is not activation. No automatic latest-version lookup or silent fallback.
4. Preserve the original provider response and its digest. Normalize into a versioned domain contract without discarding fields needed for later review.
5. Missing data, a negative observation, a no-match result, a provider outage, an unsupported variant, and an indeterminate result are different states. Never coerce one into another.
6. Automated outputs remain proposals. Unsupported rules, unresolved transcript selection, incomplete evidence, conflicting assertions, and ambiguous pedigree state must remain visible and route to review.
7. A technically successful run is not a clinically validated method. Each automated analysis method requires a defined intended use, a source-backed method, curated truth/known-answer cases, acceptance criteria fixed before execution, independent scientific review, and laboratory approval.

## 2. Current implementation baseline

The following is a source-level inventory, not a statement that the entire workflow is verified.

| Area | Existing code / contract | Current observed status | Required qualification |
|---|---|---|---|
| VEP annotation | `backend/app/adapters/annotation/vep.py`; `tests/test_vep_provider.py` | Offline local VEP adapter, GRCh37/38, pinned binary/cache manifest, cache/runtime checks, MANE/Canonical display-transcript policy | Real pinned cache and FASTA execution on known-answer variants for both assemblies; transcript and non-transcript consequence completeness; full worker execution path |
| Annotation normalization | `backend/app/adapters/annotation/normalizer.py` | VEP scalar fields and transcript consequences normalized; PR #302 extends lossless consequence context | Versioned schema compatibility, schema validation, downstream consumer audit |
| GeneBe | `backend/app/adapters/annotation/genebe.py`; `backend/app/domain/resource_capabilities.py` | Trial/evaluation provider only; not a laboratory execution provider | Keep trial boundary enforced; no fallback from VEP to GeneBe |
| Population | `backend/app/adapters/population/gnomad.py`; local tabix provider | GraphQL and local population implementations; nullable AC/AN semantics | Release-specific, assembly-specific, ancestry/cohort-specific qualification; real indexed data tests; denominator and coverage policy |
| ClinVar | `backend/app/adapters/evidence/clinvar.py` | Pinned local VCV XML plus derived SQLite index; assertion identities and provenance | Archived release corpus; VCV/RCV/SCV and condition semantics; conflict/review-status regression |
| HPO | `backend/app/adapters/phenotype/hpo_obo.py` | Local checksum/release-pinned ontology reader and term resolution | Full ontology graph validation and phenotype matching benchmark |
| HPOA | `backend/app/adapters/phenotype/hpoa.py` | Local pinned disease-phenotype annotation reader retaining source fields | Disease/condition mapping, negative annotations, frequency, onset, sex, evidence and license semantics in ranking |
| Phenotype matching | `backend/app/phenotype.py` | Exact overlap and patient-to-disease descendant matching | Validated semantic similarity/differential-diagnosis method; explicit missing/negative/frequency semantics |
| Pedigree/inheritance | `backend/app/inheritance.py` | Data-sufficiency check; compatibility returns `REQUIRES_REVIEW` | Disease-mechanism-aware inheritance, phase, segregation, parental and ploidy evidence |
| Evidence construction | `backend/app/evidence/engine.py` | Traceable evidence facts, deliberately separate from final classification | Evidence coverage, duplicate/double-counting controls, evidence-quality and source conflict cases |
| ACMG/ClinGen | `backend/app/acmg/`; `docs/validation/acmg-status.md` | Versioned specifications and selected automated evaluators; documented six-criterion scope (PM2, BA1, BS1, PP3, BP4, PVS1); PVS1 conservative/incomplete | Criterion-specific method qualification and golden cases; no generic substitute for unsupported rules |
| Candidate prioritization | `backend/app/phenotype.py`, evidence and workflow consumers | No complete validated disease-level candidate ranking method established by this audit | Separate phenotype/disease relevance ranking from pathogenicity classification and reportability |
| Reporting/sign-out | Existing review/reportability/report stages | Human gates exist | Confirm every clinical claim and evidence reference is reproducible from immutable analysis inputs/resources |

The workflow manifest `workflows/variant/v1.yaml` currently lists GeneBe as the annotation provider, while laboratory resource profiles prefer VEP and the capability policy restricts GeneBe to trial use. Reconcile this manifest with the authoritative runtime profile/contract; it must not be allowed to misrepresent the laboratory execution provider.

The standard WES/WGS profiles currently make HPO, HPOA, gene-disease validity and ClinVar optional. That is acceptable only if the result explicitly reports which phenotype and disease-prioritization capabilities were unavailable. A phenotype-driven rare-disease analysis must not present a complete ranking when its required phenotype/disease resources were not selected and qualified.

## 3. Annotation requirements

### 3.1 Input and allele identity

- Consume only the immutable normalized artifact produced by the approved normalization profile and exact reference package.
- Preserve build, chromosome, one-based position, REF, ALT, normalized allele identity, source record/ALT lineage, sample genotype and specimen identity.
- Require a one-to-one reconciliation between submitted normalized alleles and provider results. Missing, duplicate, extra, or allele-mismatched provider records are execution errors, not partial success.
- Enforce one-to-one reconciliation by identity and cardinality: reject duplicate normalized input alleles, duplicate provider records, unexpected provider alleles and missing provider alleles. Set equality alone is insufficient because it hides duplicate outputs.
- Require the VEP runtime to report the exact assembly and reference FASTA identity. The current adapter only adds `--hgvs` and `--hgvsg` when a FASTA path is configured; Ensembl documents FASTA as required for HGVS generation in offline/cache mode. A run without the governed FASTA must explicitly report HGVS as unavailable and cannot claim the complete HGVS annotation capability.
- The current adapter enables `--mane` only on GRCh38. MANE Select transcripts are defined as exact matched Ensembl/RefSeq pairs on GRCh38; GRCh37 mapping data exists but requires explicit mapping and validation. Do not describe GRCh37 canonical fallback as MANE-equivalent. Record transcript policy and assembly-specific availability in every annotation result.
- Preserve multi-allelic decomposition lineage and ensure every annotation is associated with the correct ALT allele.
- Keep unsupported structural/CNV/SV/MT/repeat classes on their existing reportability-blocked route; do not infer that VEP's ability to describe an annotation makes an unsupported assay class qualified.

### 3.2 Transcript and consequence annotation

- Record the exact VEP release, matching cache release, cache artifact identity, assembly, FASTA identity, executable digest, command/options, and response digest.
- Run in offline/local cache mode for sensitive laboratory data. Ensembl explicitly recommends matching cache and VEP releases; a mismatch can cause incompatibility. Public database use can transmit queried coordinates, so offline mode is the laboratory default.
- Preserve all transcript consequences, not just one display transcript. Preserve selected-transcript rationale separately from the full transcript set.
- Apply the approved transcript policy (for example MANE Select when available on the relevant assembly, then a uniquely qualifying canonical transcript). Do not select the first transcript or resolve ambiguity silently.
- Preserve transcript ID/version, gene ID, transcript biotype, consequence terms, canonical/MANE flags, HGVS c./p. where generated, protein/coding positions, amino-acid/codon changes, exon/intron, strand, flags and relevant predictor fields.
- Preserve variant-level most-severe consequence, intergenic, regulatory, motif and other supported non-transcript consequences, variant class, assembly name and colocated identifiers.
- A missing HGVS string is not proof that the variant has no effect. A missing transcript consequence is not equivalent to a benign consequence.
- Keep VEP-colocated identifiers as annotation context. They are not substitutes for ClinVar assertions or an independently governed clinical database.
- Store the original provider response and normalized output separately, with schema version and deterministic request/response fingerprints.

### 3.3 Population frequency

- Use an exact gnomAD dataset/release selector and record whether exome, genome, joint, and ancestry-level observations were queried.
- Preserve AC, AN, homozygote count, population identifier, dataset, assembly, quality/filter state, source record, and request/response provenance.
- AF may be calculated only when AC is a valid non-negative count, AN is a valid positive count, and AC does not exceed AN. Missing/zero/non-positive AN means AF is unavailable, not zero.
- Distinguish exact variant not found, no observation, unavailable dataset/population, provider error, and a measured zero count.
- Never treat a broad continental ancestry group as a validated GCC/Middle Eastern reference population. A laboratory-specific cohort must have its own consent, sampling, QC, ancestry, release, and qualification policy.
- For recessive disease interpretation, population evidence must be evaluated using the applicable disease-specific maximum credible frequency and the relevant ancestry/cohort denominator. No universal threshold is safe for every disease.

### 3.4 Clinical database evidence

- Use archived ClinVar releases for reproducible analyses. NCBI publishes weekly updates but archives the monthly first-Thursday release.
- Prefer complete VCV XML for variant-level assertions and RCV XML for variant-condition pairs when condition-specific interpretation is required. Summary VCF/TSV sources have narrower coverage.
- Preserve VCV, RCV and SCV accessions/versions; classification; condition; submitter; assertion method; review status; citations; source release and source digest.
- Distinguish expert-panel/practice-guideline assertions from single-submitter, no-criteria, conflicting, and no-classification records.
- Conflicting ClinVar submissions are not a pathogenic or benign consensus. Preserve the individual assertions and conflict state; do not flatten them into one label.
- ClinVar classifications are external assertions, not independent ACMG criteria and not a substitute for current case-specific review.

## 4. Phenotype and disease prioritization requirements

### 4.1 Patient phenotype semantics

- Keep patient observations separate from disease-cohort HPOA annotations.
- Preserve the patient observation subject (proband or named relative), state, onset, severity, modifiers, laterality, source and time.
- PRESENT, ABSENT, EXCLUDED, UNKNOWN and NOT_ASSESSED must remain distinct. UNKNOWN/NOT_ASSESSED are not negative findings.
- Resolve submitted HPO IDs against the exact approved ontology release. Preserve the submitted term and resolution state; obsolete or ambiguous terms must not be silently replaced.
- Use the HPO ontology as a directed acyclic graph with the supported `is_a` ancestry semantics; do not assume all ontology relationships are equivalent.

### 4.2 Disease phenotype semantics

- Preserve disease/condition identifier, source, HPO term, NOT qualifier, reference, evidence code, onset, frequency, sex, modifier, aspect and biocuration.
- Disease feature frequency describes a disease cohort, not the patient's episode frequency.
- Keep a zero-of-small-cohort observation (for example 0/3) distinct from an expert NOT annotation. The evidence strength is different.
- Respect age-of-onset, sex-specific features and phenotype aspects. Use the Phenotypic Abnormality aspect for symptom similarity unless a separately validated method explicitly handles other aspects.
- Do not assume the HPOA disease annotations are exhaustive.
- Keep gene-disease pairs separate: one gene can cause multiple disorders with different inheritance mechanisms and phenotypic spectra.

### 4.3 Ranking method

- Do not convert simple overlap counts into a clinical probability or diagnosis.
- Select and document a published, maintainable phenotype prioritization method before automating a score. Record algorithm/version, ontology and disease-annotation versions, parameters, missingness behavior, input snapshot, score components, and deterministic output.
- Validate against curated, independently reviewed rare-disease cases including overlapping phenotypes, incomplete phenotypes, age-dependent findings, negative findings, small-cohort frequency annotations, and diseases with multiple gene associations.
- Present interpretable components (matched specific terms, ancestor relationships, excluded/negative conflicts, disease feature frequency, onset/sex compatibility, missing data) rather than an unexplained scalar.
- Candidate relevance is not variant pathogenicity. Keep disease match, gene-disease validity, variant consequence, genotype/inheritance compatibility, and ACMG classification as separate axes.
- If the selected method or its required resource is unavailable, return an explicit incomplete/review state and do not claim a full phenotype-driven ranking.

**External algorithm candidate — Exomiser (evaluation only, not adopted).** Exomiser is a relevant comparator because its official project documents VCF/HPO-driven variant and gene prioritisation using phenotype, frequency, pathogenicity and inheritance. However, the software is licensed AGPL-3.0, its workflow includes its own Jannovar annotation and external data resources, and its documentation describes large versioned data packages. dbNSFP's academic branch is CC BY-NC-ND 4.0 and is explicitly non-commercial; its commercial branch requires a paid license and excludes some upstream scores unless separately licensed. Therefore SIRALOOM must not embed, redistribute, or deploy Exomiser/data packages as a production dependency without a legal and resource-license review. If assessed, it should initially be an isolated, version-pinned comparator in a qualification environment, with no authority to overwrite SIRALOOM annotation or clinical decisions.

## 5. Inheritance, pedigree and consanguinity requirements

- Use only explicit pedigree relationships, subject-attributed genotypes, sample/specimen linkage, sex/ploidy context, phase and parental/relative observations.
- Preserve genotype allele indices and phasing separators from VCF. Do not infer trans phase from two heterozygous variants alone.
- Compound-heterozygous candidate status requires a validated phase/segregation basis or must remain unresolved.
- De novo evidence requires the relevant parental genotypes and identity/relationship and confirmation policy. Absence from an untested parent is not de novo evidence.
- Evaluate inheritance against the specific gene-disease pair, mechanism, penetrance, expressivity and disease-specific exceptions. A gene's generic inheritance label is insufficient when it is associated with multiple disorders.
- Apply sex chromosome and mitochondrial rules only when the assay, ploidy model, variant class and resource profile are qualified for them.
- Consanguinity is an explicit clinical/pedigree attribute. Do not infer it solely from homozygosity or a run of homozygosity. Homozygous rare variants may be prioritized as a hypothesis, not declared causal.
- Family-member phenotypes and genotypes must never be merged into the proband's observations.
- Segregation evidence must identify exactly which relatives and genotypes were used and must not double-count related observations.

## 6. ACMG/AMP and ClinGen evidence requirements

- Bind each assessment to the exact applicable ClinGen CSpec/gene-disease scope, specification version, release status, resource checksum, organization approval and criterion executor version.
- A specification import or parse is not sufficient for automated execution. Unsupported or ambiguous rules remain `REQUIRES_REVIEW`.
- Keep each criterion assessment separate, with applicability, direction, strength, evidence IDs, rationale, dependencies, executor identity, specification identity and provenance.
- Prevent reuse of the same underlying observation as independent evidence across criteria unless the governing specification explicitly permits it.
- Implement/qualify criteria individually against the current ClinGen guidance. Priority areas include:
  - PVS1: loss-of-function mechanism, transcript relevance, NMD, exon position, rescue/alternative transcripts and disease mechanism.
  - PM2/BA1/BS1: disease-specific thresholds, ancestry/population denominator, coverage and missingness.
  - PM3: in-trans evidence and recessive disease context.
  - PP1/BS4: segregation counts, relationship, penetrance and informative meioses.
  - PP4: phenotype specificity for the particular disorder, not generic HPO overlap.
  - PS2/PM6: verified versus assumed de novo evidence and parental testing context.
  - PP3/BP4: exact predictor/model version, transcript/context, calibration dataset and validated score intervals.
  - PS3/BS3: assay validity, controls, relevance to the disease mechanism and calibrated functional evidence.
- Do not infer pathogenicity from a VEP consequence label alone.
- Do not automatically apply a generic 2015 combination engine to a ClinGen specification that requires a different combination method. If the exact method is unsupported, preserve evidence and require review.
- External ClinVar or provider classifications are source assertions, not a replacement for SIRALOOM's evidence evaluation.
- Classification proposal, expert review, reportability decision, sign-out authorization and report release are separate workflow transitions.

## 7. Required verification corpus and acceptance evidence

| Corpus / test group | Required cases | Evidence to retain |
|---|---|---|
| VEP known-answer | GRCh37 and GRCh38; synonymous, missense, stop-gain, frameshift, splice donor/acceptor, in-frame indel, UTR, intronic, intergenic, regulatory | Input/reference/cache/tool digests, exact command, raw VEP JSON, normalized output, expected consequence/transcript |
| Transcript selection | MANE Select, unique canonical fallback, multiple MANE, multiple canonical, no preferred transcript, alternate/RefSeq transcript context | Deterministic selected transcript or explicit unresolved state |
| Allele reconciliation | Multiple ALT decomposed records, indels, left-normalized alleles, missing/duplicate/extra provider rows | Exact one-to-one input/output reconciliation |
| Annotation failures | Missing binary/cache/FASTA, checksum mismatch, version mismatch, timeout, malformed JSON, partial response, worker loss/replay | Durable failure state, no partial-success claim, idempotent replay and provenance |
| Population | AC=0 with AN>0, AN missing/zero, AC>AN, exact no-match, exome/genome, ancestry subpopulations, provider outage | Correct null/zero distinction, source and release identity |
| ClinVar | Pathogenic/benign/VUS, conflicting submissions, differing review stars, no criteria, multiple conditions, haplotype/genotype records | Preserved VCV/RCV/SCV identity and assertion conflict |
| HPO/HPOA | Current/alternate/obsolete HPO IDs; present/absent/excluded/unknown; NOT; 0/n and n/m frequencies; onset; sex; multiple disease pairs | Source-field preservation and correct matching semantics |
| Inheritance | AR homozygous, AR compound het in trans/in cis/unknown phase, AD, X-linked by ploidy, de novo with/without parental tests, unaffected relatives, consanguinity recorded/not recorded | Exact genotype/pedigree evidence and explicit supported/review state |
| ACMG criteria | Each automated criterion: positive, negative, borderline, missing, conflicting, wrong specification, wrong gene/disease scope, duplicate evidence, uncalibrated predictor | Criterion-specific expected decision and reviewer rationale |
| End-to-end | Real normalized VCF through annotation, population, phenotype/disease evidence, inheritance, ACMG, human review and reportability | Immutable input/resource snapshot, replay, audit, and reproducible final report |

Acceptance criteria must be authored and independently reviewed before executing the benchmark. Test fixtures should include public or otherwise lawfully usable, hash-pinned real data. Synthetic fixtures remain useful for boundary cases but cannot replace real-data qualification.

## 8. Dependency-ordered implementation plan

1. **A1 — Annotation payload contract:** preserve all VEP consequence classes and selected transcript context; retain backward-compatible fields; schema and malformed-response tests. PR #302 starts this milestone.
2. **A2 — VEP execution qualification:** migrate VEP execution through the shared scientific tool executor after the universal executor stack is integrated; qualify exact VEP/cache/FASTA combinations on both assemblies with real known-answer VCFs.
3. **A3 — Annotation resource profiles:** reconcile `workflows/variant/v1.yaml` with laboratory VEP profiles; explicitly represent required, optional, unavailable and incomplete annotation capabilities; prohibit GeneBe laboratory fallback.
4. **A4 — Population and ClinVar evidence qualification:** pinned local gnomAD and archived ClinVar releases, source completeness, real-data tests and provenance.
5. **A5 — Phenotype/disease matching method:** choose and document the algorithm; preserve HPO/HPOA semantics; add disease-level ranking with interpretable components and benchmark.
6. **A6 — Inheritance and segregation:** design disease-mechanism-aware genotype/pedigree contracts; implement only supported models and route incomplete phase/parental evidence to review.
7. **A7 — ACMG/ClinGen criterion qualification:** close the existing evaluator scope with criterion-specific source mapping, executors, evidence binding and independent golden cases.
8. **A8 — Case-level integration:** candidate ranking, reviewer adjudication, reportability, immutable provenance and reanalysis/change management regression.

## 9. Authoritative sources

- Ensembl VEP cache guidance: https://www.ensembl.org/info/docs/tools/vep/script/vep_cache.html
- Ensembl VEP options: https://www.ensembl.org/info/docs/tools/vep/script/vep_options.html
- Ensembl VEP source: https://github.com/Ensembl/ensembl-vep
- gnomAD GraphQL API documentation: https://github.com/broadinstitute/gnomad-browser/tree/main/graphql-api
- NCBI ClinVar downloads: https://www.ncbi.nlm.nih.gov/clinvar/docs/downloads/
- NCBI ClinVar FTP guide: https://www.ncbi.nlm.nih.gov/clinvar/docs/ftp_primer/
- NCBI ClinVar review status: https://www.ncbi.nlm.nih.gov/clinvar/docs/review_status/
- HPO annotation introduction: https://obophenotype.github.io/human-phenotype-ontology/annotations/introduction/
- HPO phenotype.hpoa format: https://obophenotype.github.io/human-phenotype-ontology/annotations/phenotype_hpoa/
- HPO frequency and negative annotation semantics: https://obophenotype.github.io/human-phenotype-ontology/annotations/frequency/
- ACMG/AMP 2015 sequence variant interpretation guideline: https://doi.org/10.1038/gim.2015.30
- ClinGen Variant Classification Guidance: https://clinicalgenome.org/tools/clingen-variant-classification-guidance/
- ClinGen Gene-Disease Validity SOP: https://www.clinicalgenome.org/docs/gene-disease-validity-standard-operating-procedure/

## 10. Completion language

Use the following status labels consistently:

- **IMPLEMENTED:** source code exists.
- **UNIT-TESTED:** focused tests passed on the recorded commit.
- **INTEGRATION-TESTED:** actual configured database/worker/artifact path passed.
- **REAL-DATA-QUALIFIED:** pinned public or lawfully available real datasets were executed and compared with predeclared known answers.
- **SCIENTIFICALLY-REVIEWED:** an appropriately qualified reviewer reviewed the method and discrepancies.
- **LAB-QUALIFIED/VALIDATED:** the responsible laboratory approved the intended use under its quality system.
- **NOT RUN / PARTIAL / BLOCKED / REQUIRES REVIEW:** evidence is incomplete or capability is unsupported.

A1 is implemented in PR #302 but remains **NOT VERIFIED** until its focused and full CI tests pass. All later milestones remain open until their stated evidence is produced.


## 11. A2 — VEP production execution qualification

**Status: BLOCKED ON SHARED EXECUTOR STACK; REAL-DATA QUALIFICATION NOT RUN.** This is an acceptance contract, not evidence of successful VEP execution.

### Dependency gate

The current dependency chain is represented by open draft PRs: #297 durable artifact-validation workers; #300 separation of tool-neutral API and scientific workers (based on #297); #301 universal scientific tool execution contract (based on #300); #302 annotation payload contract (currently based on main, not #301). Do not import an unmerged executor or duplicate its process lifecycle in the VEP adapter. After #297–#301 are integrated and their CI baseline is green, stack/rebase VEP integration on the qualified executor. The six VCF validator failures in the latest #302 CI run remain a separate blocker for the shared backend baseline and must be fixed in the VCF workstream.

### Shared executor audit findings

Inspection of the current #301 executor contract identified additional A2 requirements:

1. ScientificResourceBinding validates digest syntax and records a supplied digest, but does not resolve a governed resource path and hash the actual cache/FASTA/manifest bytes. A caller-supplied digest is not resource attestation.
2. ToolIdentity records platform but the inspected executor does not compare it with the running platform/architecture. Enforce this or bind execution to an immutable platform-specific image and attest its digest.
3. The request enforces timeout and bounded returned logs, but no CPU, memory, process-count or scratch-disk limits. These must be enforced by worker/container/cgroup policy.
4. Output hashes are computed after execution, but atomic publication and durable artifact registration/recovery must be guaranteed by the worker/artifact lifecycle.
5. The current VEP adapter launches subprocess.Popen directly. Remove this independent lifecycle when shared-executor integration is qualified; no nested subprocess fallback.

These are integration acceptance items, not reasons to bypass the shared executor.

### Governed tool and resource identity

Each organization-approved VEP profile must pin VEP release/version, executable path and SHA-256, version attestation command/output, platform/architecture, immutable runtime image digest (including Perl and VEP modules), cache release/species/assembly and verified content digest, reference FASTA identity/digest and required indexes, explicit annotation options, transcript-selection policy, qualification state and organization approval. Cache, species and assembly mismatch are hard preflight failures. No auto-download, auto-upgrade, online fallback, assembly switch or GeneBe fallback is permitted in a laboratory profile.

### Preflight requirements

Before execution: verify the immutable normalized VCF digest and assembly; resolve the organization-approved resource profile; verify executable regular-file identity, digest and version; verify the cache manifest and every referenced artifact (or a documented cryptographically verified immutable package digest); inspect actual cache metadata for release/species/assembly; verify FASTA digest and assembly against the normalization reference package; verify required indexes; reject symlinks/unapproved paths and any mismatch. Execute offline/cache-only in a controlled environment with no user-supplied shell fragments or ungoverned command overrides. A failed preflight must be typed, non-retryable and must not publish annotation output.

### Real known-answer corpus

Create a manifest-driven corpus with immutable public source URLs, source release/accession, publisher checksum where available, local SHA-256, license/terms review, assembly, input VCF digest, expected semantic output and transcript. GRCh37 and GRCh38 require separate assembly-specific records; do not transfer coordinates between assemblies. Both assemblies must cover synonymous, missense, stop-gained, frameshift insertion/deletion, splice donor/acceptor, in-frame insertion/deletion, UTR, intronic, intergenic and regulatory consequences where stable known-answer loci are available. Include multi-ALT and left-normalized indel records. Compare stable semantic fields (allele, assembly, consequence, complete transcript set, transcript/gene IDs and versions, HGVS where supported, MANE/canonical flags and consequence-specific fields), not JSON key order. Preserve raw provider output.

### Transcript-selection tests

On each assembly, verify unique MANE Select selection on GRCh38; unique eligible canonical fallback when no MANE exists; explicit ambiguity for multiple eligible candidates; explicit no-selection when none qualify; preservation of every transcript consequence independent of the display transcript; and preservation of transcript versions/cross-references. GRCh37 must not claim MANE equivalence without a separately versioned and qualified mapping resource. Expected selections must be declared before execution; selecting the first returned transcript is a failure.

### Reconciliation, provenance and recovery

Durably link each execution to organization/case/workflow, normalized input digest, tool profile and executable digest, runtime image/platform, cache and FASTA/reference digests, exact argv/options, timestamps/exit status, raw response digest/artifact, normalized artifact digest/schema, allele reconciliation counts, worker attempt/lease and publication state. Publish only after complete parse, schema validation, exact one-to-one allele reconciliation and output digest registration. Quarantine partial output. Inject worker termination before start, during VEP, after process exit but before validation, after validation but before publication, and after publication but before workflow acknowledgement. Replay must be idempotent, must not duplicate rows or overwrite immutable artifacts, and must prevent stale workers publishing after lease loss.

### Batch and resource qualification

Run increasing batch sizes on both assemblies and the approved runtime image. Record variant count, input/output bytes, wall time, peak RSS, CPU time, scratch use, throughput, retries and per-variant reconciliation. Include representative WES-scale and supported upper-bound WGS-scale workloads. Enforce CPU, memory, process and scratch limits at the container/cgroup boundary. Limit exhaustion must terminate the process group, classify the failure, clean temporary files safely and leave only transient failures retryable. No silent truncation or partial batch success.

### A2 completion gates

A2 is complete only when the shared executor and durable worker dependencies are integrated and CI-green; executable/cache/FASTA/index/image identities are verified from actual bytes and metadata; GRCh37/38 real known-answer suites pass; required consequence and transcript cases pass against predeclared expectations; exact reconciliation and raw/normalized provenance pass; crash/replay passes at every publication boundary; WES/WGS-scale runs pass within measured resource limits; focused, backend, PostgreSQL/Celery, frontend and production-container CI pass; and discrepancies/exclusions are reviewed. Scientific review and laboratory qualification remain separate approvals. Until then, VEP may be called implemented or unit-tested only where run evidence supports that status—not real-data-qualified, clinically validated or laboratory-qualified.
