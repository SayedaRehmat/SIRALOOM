# Germline SNV/indel VCF intake and normalization: workflow audit

**Status:** engineering/research design note; not a controlled laboratory SOP, standards interpretation, validation report, or authorization for clinical use.

**Repository baseline inspected:** `main` at `f9fbbdbae12e6c2ca59004573723e56b45a56eda` (2026-11-07). Reconcile this note against the exact head before making release decisions.

## Decision in brief

SIRALOOM's intended boundary—start from a caller-produced VCF and take the case through validation, reference-aware normalization, annotation, evidence, qualified human review, report and reanalysis—is a defensible first product. It is not a read-processing or variant-calling pipeline today: FASTQ, alignment, caller operation and caller QC are upstream inputs and responsibilities unless a separately governed upstream pipeline is added.

The repository already has substantial VCF parsing/routing, reference checks, BCFtools normalization, source-to-child lineage, durable artifact/workflow state, report gates and reanalysis contracts. The immediate release problem is **integration and evidence control**, not another broad feature sprint. `main` has a failing CI run, and the repository's Stage-1 qualification matrix explicitly says implementation is not laboratory qualification. Do not merge a PR simply because it is marked mergeable or its title sounds production-ready.

## Intended workflow and interfaces

A laboratory must define its intended use and caller/assay-specific acceptance criteria. There is no single universal production pipeline or universal set of numeric QC thresholds: WES, WGS, panels, sequencing platforms, callers, sample types, builds and laboratory SOPs differ. Preserve the selected lab's policy and provenance rather than inventing defaults.

| Stage | Inputs and required context | Successful output/state | Failure or non-success disposition / next action |
|---|---|---|---|
| 0. Case, order and accession | Organization/lab, accession, indication, assay/test and version, specimen(s), consent/policy where applicable, operator and timestamps | Durable case and specimen identities; intended assay/build/caller scope recorded | Identity, order or assay ambiguity: hold intake; resolve with authorized lab staff. Never infer a VCF sample's biological identity from its name alone. |
| 1. Artifact receipt | Original VCF/VCF.GZ/approved BCF, upload identity, declared sample(s), caller/pipeline and version, reference build, associated index if supplied | Immutable original bytes; byte size, checksum, upload actor/time and paired artifacts recorded; intake status `PENDING` until validation is complete | Upload/storage/checksum errors: operational failure/retry, not “invalid science.” Keep source bytes; make retry idempotent. |
| 2. Format and caller-profile validation | Exact file format version, headers, records, sample columns, selected qualified caller dialect/profile | Version/profile-specific validation result, warnings, counts and machine-readable diagnostics | Malformed or out-of-profile data: `INVALID`/`BLOCKED` with stable code and record location. A valid but unsupported feature must be preserved and routed, not silently dropped or mislabeled malformed. |
| 3. Sample/ploidy/build/reference binding | VCF sample names; explicit specimen-to-sample mapping; assembly and exact lab-approved reference package (FASTA, indexes, contig manifest/checksums); assay ploidy policy | Verified sample-to-specimen and reference identity snapshots bound to the analysis | Unknown/duplicate/mismatched samples, build, contig or REF allele: block analysis or require an explicit lab resolution. Do not infer identity, assembly, or ploidy from sex, names, contig labels, or a guessed default. |
| 4. VCF record routing and reconciliation | Validated original VCF and profile | Every source record accounted for exactly once: eligible sequence variant, reference-only/non-call, or typed unsupported/review route; counts and source identities reconcile | Any missing/duplicate/unclassified source record: fail closed. Keep excluded records and reasons available for case review and completeness checks. |
| 5. SNV/short-indel normalization | Eligible sequence alleles, exact reference and approved tool/profile, explicit multiallelic/MNV/genotype projection policy | Deterministic normalized artifact and index; exact tool, command/options, reference and output hashes; source record/ALT to child allele mapping; calls and phase preserved per sample | REF mismatch, unsupported remapping, ambiguous genotype, or output/index mismatch: do not publish partial output as successful; preserve inputs and emit a typed block/review state. Never repair REF implicitly. |
| 6. Annotation and downstream interpretation | Normalized variants, qualified annotation/evidence resources, versioned interpretation policy | Provenance-bound observations, reviewable evidence and proposed assessments | Resource absence is not zero frequency or benign evidence. Retry infrastructure failures; route scientific gaps to review. Caller quality and downstream annotation are separate facts. |
| 7. Human review, reportability, report/sign-out | Complete analysis and limitations/routed records, qualified reviewer/signatory and lab policy | Versioned approved interpretation, explicit reportability decision, immutable report and audit/provenance package | Missing review, unresolved unsupported records, stale decisions, failed QC or incomplete provenance: do not release/sign out. Reanalysis creates a new child analysis; never silently overwrite a signed result. |

### Sample modes

- **Single-sample VCF:** exactly one selected sample must map to the registered specimen. Sites-only VCFs cannot be treated as a patient's genotype callset. Preserve `0/0`, alternate, missing, phased and ploidy semantics; only variants eligible under the assay's validated reportable range proceed.
- **Multi-sample cohort/joint VCF:** retain all sample columns and order, validate every genotype against the declared columns, and persist explicit sample-to-specimen membership for the analysis. Do not arbitrarily choose the first sample, combine unrelated people into one case, or use cohort allele frequency in place of a population resource. A lab may create a governed one-sample derivative, but it must retain source hash, sample selection and transformation provenance.
- **Trio/family:** represent each family member as an explicit case-linked specimen/sample and retain per-sample GT, phase, missingness and caller evidence. Segregation is downstream evidence, not a caller verdict. Never infer parentage, de novo status, or biological sample identity from a pedigree label alone. Joint-called multi-sample VCF and per-sample gVCFs are distinct inputs/contracts.
- **Cohort joint calling:** caller-side joint genotyping is an upstream pipeline operation. If SIRALOOM later accepts gVCFs or performs calling/joint genotyping, treat that as a separately specified, versioned, qualified pipeline—not as an undocumented extension of ordinary VCF intake.

## Variant caller boundary

The caller consumes aligned reads (and a reference, plus caller-specific inputs/policies), estimates candidate alleles/genotypes and supporting metrics, and emits VCF or a reference-confidence gVCF. SIRALOOM does not recreate that inference from VCF. Intake must record caller name/version, caller pipeline version, assembly/reference identity, assay, filtering/calling mode and sample manifest to the extent supplied/required by the lab profile. A VCF's `PASS` is the caller's filter annotation; it is not proof that SIRALOOM's intake, lab assay QC, classification or reportability gates passed. Preserve caller fields and their original meanings; do not manufacture caller metrics.

## VCF version scope: what is relevant to this product

The official versioned HTS specifications are the normative source for each VCF version; support is not established by accepting a `##fileformat` string. For the common small-variant path, prioritize the constructs actually emitted by each qualified caller: record/header grammar, REF/ALT and multiallelic indices, GT/ploidy/phase, declared INFO/FORMAT types and cardinalities, missing values, FILTER semantics, contigs/build, and compression/index integrity. Test these per version and caller profile.

- VCFv4.0–4.3: support only the version-specific semantics claimed by the validator and the qualified producer(s). In particular, legacy definitions can differ from later versions; do not apply v4.5 reserved-field assumptions retroactively.
- VCFv4.4/4.5: new phase/local-allele/base-modification/SV features require explicit version-specific implementation and fixtures. These are not automatically necessary to interpret ordinary diploid SNV/indel calls, but files containing them must be correctly parsed, preserved and either handled under an approved policy or visibly routed. Do not claim full VCFv4.5 conformance because a subset of validator tests passes.
- gVCF: reference-confidence blocks and `<NON_REF>` are caller/joint-calling concepts, not ordinary small-variant records. Accepting a concrete variant from a mixed gVCF is safe only when the caller-specific contract proves the genotype and all required context. Otherwise preserve and route the record. A gVCF block is not a negative clinical result.
- VCF is not the clinical assay or caller validation. A format-conformant VCF may still contain inaccurate calls or caller-specific values outside the laboratory's qualified reportable range.

**Scope recommendation:** do not spend the first release on every VCF 4.0–4.5 clause or unsupported SV/repeat/base-modification interpretation. First identify the exact supported caller outputs, version(s), and caller modes from target laboratories. Fully qualify that subset; explicitly preserve and reject/route other valid features. Expand conformance only with a documented intended-use need and exact tests. Never remove valid-version support just because some historical clauses need more source research; mark unqualified clauses and fail/reroute only where the actual input feature requires them.

## Repository audit against that workflow

Evidence inspected at the baseline includes `backend/app/domain/vcf_validation.py`, `backend/app/domain/vcf_tools.py`, `backend/app/workflows/variant.py`, `backend/app/reporting/finalization.py`, `docs/SCIENTIFIC_LAB_WORKFLOW_SPECIFICATION_V1.md`, `docs/REANALYSIS_CHANGE_AWARE_CONTRACT.md`, `docs/PHASE1_RELEASE_STATUS.md`, `docs/PHASE1_ACCEPTANCE_MATRIX.md`, `docs/VARIANT_CLASS_SUPPORT.md`, `docs/VCF_STAGE1_LAB_QUALIFICATION_MATRIX.md`, and `.github/workflows/ci.yml`.

### Present foundations (implementation is not qualification)

- Strict version-aware parser advertises VCFv4.0–4.5, checks numerous structural/semantic details and exposes typed errors; `tests/test_vcf_validation.py` and version-focused VCF tests exist.
- `route_vcf_records` preserves source records into typed routes, creates per-record exclusion lineage and checks source-record/disposition reconciliation. The worker validates the chosen reference before normalizing eligible sequence variants.
- `normalize_vcf_with_bcftools` pins BCFtools/HTSlib, checks REF (`-c e`), splits multiallelics, sorts, creates CSI, reconciles output to source ALT lineage and stages outputs before publishing.
- Workflow/report infrastructure includes durable state, retry/recovery, artifact checksums, human review/reportability/sign-out gates and a change-aware reanalysis contract.
- CI includes backend, PostgreSQL/Redis/Celery integration, frontend build and container/configuration jobs.

### Gaps that block a production claim

1. **Current main is red.** Exact `main` SHA `f9fbbdbae12e6c2ca59004573723e56b45a56eda` failed backend CI: six known strict-VCF tests (five VCFv4.0 FORMAT, one VCFv4.5 Number=P) failed; frontend tests passed. A prior main push was reverted after adding an unreviewed container check. The fix is already drafted in PR #299, but its observed PostgreSQL job log includes a duplicate annotation identity error. Re-run and resolve both jobs on a branch based on the exact current main before merge.
2. **Do not pick arbitrary samples.** Current release docs state analysis is single-sample and require explicit sample-to-specimen mapping. Multi-sample cohort and trio/family must be first-class explicit modes before claiming support; the repo's own qualification matrix says biological identity/chain of custody is not established.
3. **Caller/assay matrix is not qualified.** The Stage-1 matrix marks WES/WGS × caller/version × build cells NOT-EVIDENCED. A parser/normalizer cannot establish caller accuracy, reportable range, assay QC thresholds or sample identity.
4. **No executed independent caller concordance evidence is shown by the inspected release docs.** The repo distinguishes input-processing benchmark from caller accuracy. Need a matched, pinned GIAB truth+confident-region benchmark and a real caller-produced query VCF; never compare a truth VCF to itself or claim an input-processing run is caller validation.
5. **Status docs conflict/stale.** `docs/VARIANT_CLASS_SUPPORT.md` identifies an older commit and says the validator allows only VCFv4.2/4.3, inconsistent with the inspected validator's VCFv4.0–4.5 allowlist. Other acceptance/release snapshots are historical and contradict current features. Reconcile documentation to one exact commit and label historical snapshots clearly before using them to decide support.
6. **No independent standards review yet for the broad VCF conformance branch.** PR #293 describes a 226-requirement ledger with many unmapped requirements, unresolved source questions, no independent standards reviews, no full CI on its current head and `NOT READY FOR LABORATORY QUALIFICATION`. This is a research workstream, not a mergeable production feature bundle.
7. **Deployment/clinical evidence is still absent.** Release docs identify missing live authenticated end-to-end testing, deployed tenant isolation, permitted production providers, backup/restore, target-lab failure recovery, independent scientific qualification and laboratory approval. These cannot be closed by merging code or passing CI alone.

## PR/merge disposition based on inspected evidence

This is a risk-based recommendation, not a complete review of every open PR. Check exact head/base and CI again immediately before acting.

| PR | Recommendation | Reason / prerequisite |
|---|---|---|
| #299 VCFv4.0 + v4.5 Number=P fix | **First narrow fix to rebase/verify. Do not merge yet.** | It directly targets the six baseline backend failures. Rebase on current main; focused and full backend must pass. Resolve/re-run PostgreSQL integration; require frontend/build checks on the rebased exact head. |
| #297 durable artifact validation | **Next candidate only after #299 is merged and #297 is rebased.** | Useful operational foundation; its own description says keep draft with red baseline backend. Re-run all checks on exact rebased head and review migration/outbox/worker semantics. |
| #280 or #284 GIAB work | **Qualification tooling, not a product-release claim. Keep separate and require executed artifacts/review.** | #280 is dirty and says benchmark jobs did not execute; #284 is a truth-input processing benchmark, explicitly not caller concordance. Neither alone proves analytical performance. |
| #276 VCF conformance test corpus | **Do not merge as a release proof.** | Test-only and draft; require pinned/version-specific source review and exact CI. Tests are useful only with an explicit supported caller/version scope. |
| #282 normalization capability governance | **Do not merge as part of the immediate build repair.** | Large (71 files, 522 commits), branch status unknown, tests/source acquisition not verified, broad registry/qualification scope. Break into reviewable slices and rebase against current main. |
| #293 standards ledger and its stacked dependents such as #317 | **Keep as draft research; do not merge now.** | #293 is dirty, not rebased, reports no full CI on current implementation and says NOT READY FOR LAB QUALIFICATION. #317 builds on it and cannot be considered independently ready. |

### Near-term sequence

1. Freeze unrelated feature merges. Protect `main` and make green required checks the merge gate.
2. Rebase #299 (or a new narrow fix branch) on current `main`; run focused VCF tests, full backend, PostgreSQL/Celery integration, frontend build and container checks on the exact head. Fix failures, not expectations, unless an authoritative version-specific interpretation proves a test wrong.
3. Merge only that small fix when all required checks are green. Then rebase and test #297; merge only if its tests and migration/outbox review pass.
4. Reconcile a single current support matrix: supported caller(s)/version(s), VCF version(s), sample mode, GRCh build, accepted small-variant classes, blocked/routed features and reportability implications.
5. Obtain target-lab caller outputs and approved reference assets; execute exact workflow acceptance and failure tests. Build a separate caller-validation benchmark with matched truth/confident BED and caller query, not just input-processing qualification.
6. Only after independent laboratory review and pre-approved acceptance criteria may an applicable matrix cell become QUALIFIED. Keep clinical-release status blocked until all lab/deployment quality gates are satisfied.

## Inputs, outputs, statuses and next action contract to build/verify

Suggested status semantics (map to existing typed state enums rather than adding parallel status models):

- `PENDING`: received/persisted, validation not complete; cannot start analysis.
- `VALIDATED`: syntax/selected profile checks passed; this alone does not mean normalized or clinically usable.
- `NORMALIZED`: supported record set passed reference-aware normalization, indexing and complete source/output reconciliation.
- `PARTIAL_REVIEW`: original file valid but contains preserved unsupported/unresolved records; no claim that those records were analyzed. Block a clinical report unless explicit lab policy resolves case completeness.
- `INVALID` / `BLOCKED`: malformed file, incompatible build/REF, or unsupported required operation; show code, file/record location, and corrective action.
- `RETRYING` / `RESOURCE_FAILURE`: infrastructure/resource issue, not a scientific finding. Keep artifact immutable and make retries idempotent.

Every terminal or review state should persist: input artifact/hash/size; VCF and caller profile; sample manifest and specimen mapping; assembly and reference bundle hashes; tool/profile/lock identity; validation warnings/errors; source-record disposition counts and per-record links; normalized VCF/index hashes; exact normalization policy/command; execution timestamps/attempts; and authorized human decisions. No generic `SUCCESS` should conceal partial or unsupported data.

## First acceptance gate (software only)

- Mainline exact-commit CI is green: focused versioned conformance, full backend, PostgreSQL/Redis/Celery integration, frontend build and deployment config.
- Supported sample modes are explicit. Single-sample mode rejects sites-only/multisample input or requires explicit one-sample derivation; family mode maps every VCF sample to a case specimen without dropping columns or silently choosing one.
- Input bytes remain immutable and checksum-verified; retries do not duplicate artifact, dispatch, analysis or report identities.
- Version-specific validator tests cover accepted caller output, GT/ploidy/missingness, multiallelic A/R/G remapping, phase, REF/build mismatch, BGZF/index mismatch, and valid-but-unsupported routes.
- Every source record/ALT has exactly one durable disposition; every normalized child traces to source; no REF repair; invalid output is never published as valid.
- Negative tests cover invalid/missing reference, corrupt/truncated compression, incorrect sample mapping, unsupported record, worker loss, storage/DB/queue failure and safe retry.

Passing this software gate still does **not** make a lab-qualified or clinically validated product. The controlled laboratory must execute the intended assay/caller/build matrix, define acceptance criteria before validation, review results, document limitations/deviations and approve changes under its quality system.

## Primary sources and scope cautions

- [SAM/HTS specification repository](https://github.com/samtools/hts-specs/) and its versioned VCFv4.0–4.5 documents: normative syntax/field semantics. Consult each version; do not treat a cross-version summary or parser allowlist as full conformance.
- [GATK germline short variant discovery Best Practices](https://gatk.broadinstitute.org/hc/en-us/articles/360035535912-Best-Practices-Workflow-for-Germline-Short-Variant-Discovery-SNPs-Indels-) and [joint-genotyping workflow](https://gatk.broadinstitute.org/hc/en-us/articles/360037226632-Joint-calling-germline-SNPs-and-indels-using-GenotypeGVCFs): one example of a caller-specific upstream workflow, not a universal mandate to use GATK or gVCF.
- [Krusche et al., GA4GH benchmarking best practices (2019)](https://doi.org/10.1038/s41587-019-0054-x), [GIAB](https://www.nist.gov/programs-projects/genome-bottle), [GA4GH benchmarking tools](https://github.com/ga4gh/benchmarking-tools), and [hap.py](https://github.com/Illumina/hap.py): benchmark design and comparison tools. Match sample, assembly, truth release and confident regions; report scope and limitations.
- [ACMG/AMP 2015 sequence-variant interpretation consensus](https://doi.org/10.1038/gim.2015.30), [ClinGen SVI](https://clinicalgenome.org/working-groups/sequence-variant-interpretation/), and [ACMG 2021 reevaluation/reanalysis points to consider](https://doi.org/10.1038/s41436-020-01046-1): interpretation and reevaluation guidance, not a VCF parser specification.
- [FDA germline NGS analytical-validation guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/considerations-design-development-and-analytical-validation-next-generation-sequencing-ngs-based): guidance for its stated scope/jurisdiction, not a universal replacement for the lab's regulatory/accreditation requirements. CAP/CLSI controlled checklists/standards may require licensed access; the lab must consult its current applicable editions.

Do not infer universal numerical QC thresholds, orthogonal-confirmation rules, exact reanalysis intervals, caller choice, or required VCF 4.0–4.5 coverage from these summaries. Those are intended-use-, assay-, jurisdiction- and policy-specific and need documented laboratory decisions.
