# SIRALOOM VCF Intake and Normalization — Master Execution Contract

**Document ID:** SIRALOOM-VCF-MEC-001  
**Version:** 1.1  
**Status:** AUTHORITATIVE EXECUTION CONTROL — all acceptance gates are mandatory  
**Owner:** SIRALOOM Product, Platform and Bioinformatics Engineering  
**Applies to:** VCF intake, validation, reference-controlled normalization, qualification, artifact publication and provenance  
**Baseline date:** 2026-11-03  
**Current implementation vehicle at baseline:** PR #282, feature/vcf-normalization-capability-governance  
**Recorded baseline head:** 7b8abebf95d07c9eb6ce1ec00c6c5fe25e31d9c8  
**CI run requiring revalidation:** #3202, run ID 41627304151  
**This document does not declare the stage complete.**

**Mandatory operational supplement:** [VCF Laboratory Operations, Error Handling and Performance Specification](./VCF_INTAKE_NORMALIZATION_LAB_OPERATIONS_ERROR_PERFORMANCE_SPECIFICATION.md). Its requirements and gates G17–G23 are part of this contract.

---

## 1. Mission — do not reinterpret

Deliver a production-grade, laboratory-governed VCF intake and normalization stage for SIRALOOM. The stage must accept supported VCF inputs, establish their identity and integrity, validate them against an explicitly selected VCF specification and reference assembly, normalize supported small variants deterministically using an exact laboratory-approved executable, verify the resulting artifact, and publish it with complete reproducible provenance.

This is a clinical laboratory workflow component. It is not merely a file-upload feature, a convenience wrapper around BCFtools, or a demonstration that a few fixtures pass.

**Required outcome:** a trustworthy, traceable, recoverable transformation from an immutable submitted VCF to a separately identified normalized VCF.

No agent may narrow, reinterpret, or silently relax this mission.

## 2. Non-negotiable operating rules

1. **Evidence over claims.** A requirement is complete only when implementation, tests, execution results and retained evidence are linked. Code presence, a green unit-test suite, or a successful mock is not sufficient.
2. **No fabricated execution.** Never describe a test as run unless the executable was actually invoked against the stated input and the resulting logs/artifacts were inspected.
3. **No silent substitution.** Never silently change assembly, reference package, VCF specification, normalizer, executable version, parameters or resource because the requested one is unavailable.
4. **No latest-version resolution.** Runtime must use an exact immutable resource selection and verify that exact selection. No global “latest” lookup.
5. **No source overwrite.** Preserve the submitted source file and its original bytes. Normalized output is a distinct artifact with a durable relationship to its source.
6. **Fail closed for unsafe ambiguity.** Unknown formats, malformed files, assembly ambiguity, reference mismatch, unsupported variant types, unknown provider, unqualified release or incomplete provenance must not enter clinical downstream processing.
7. **Resource outages are operational states.** A temporarily unavailable scientific resource should produce a visible blocked/queued/retryable state with a reason where safe—not corrupt data, silently substitute, or misclassify a scientific failure as a transient outage.
8. **Deterministic and idempotent.** Replaying the same immutable input with the same locked resources and parameters must have defined, testable behavior and must not create conflicting published outputs.
9. **No evidence loss.** Qualification inputs, checksums, tool identities, commands, stdout/stderr, exit codes, output hashes, test reports and failure artifacts must be retained as inspectable evidence.
10. **No false completion.** Do not mark the VCF stage or a sub-gate complete while any mandatory acceptance criterion is unverified, skipped without approved rationale, or failing.
11. **Architecture preservation.** Extend existing SIRALOOM architecture and contracts. Do not create parallel ingestion/normalization pathways, duplicate resource registries, bypass governance or refactor unrelated completed modules.
12. **Main is protected.** Work through the current approved feature branch/PR process. Do not merge PR #282 or push unrelated changes to main without explicit user authorization.
13. **Every handoff starts with repository reality.** Re-fetch current branch/head, PR, workflow status, changed files and relevant code before editing. This document is the goal and control plane, not proof that the repository still matches the recorded baseline.
14. **No scope creep.** Current execution scope is SNV and small INDEL on GRCh37 and GRCh38. WES/WGS are intake contexts; they do not mean SIRALOOM performs FASTQ alignment or variant calling.

## 3. Product boundary and explicit exclusions

### 3.1 In scope

- WES/WGS case and file metadata intake relevant to VCF processing.
- VCF receipt, immutable source preservation, file identity and integrity.
- Plain-text VCF, ordinary gzip-compressed VCF and BGZF-compressed VCF handling, with correct distinctions.
- VCF structural and semantic validation, including header, records, samples, alleles, genotypes and specification-version compatibility.
- Explicit reference assembly and immutable reference-package selection for GRCh37 and GRCh38.
- SNV and small INDEL eligibility, normalization and post-normalization verification.
- Exact normalizer resource governance, qualification, approval, execution and provenance.
- Index validation/creation where required by the established contract; correct CSI/TBI and BGZF semantics.
- Atomic artifact publication, state transitions, audit events, retry/replay and recovery.
- Backend, worker, API and frontend traceability required to expose stage status, resource selection, validation findings, execution history and artifact lineage.
- Production-container execution and evidence preservation.

### 3.2 Explicitly out of scope for current execution

- FASTQ alignment, read mapping, base recalibration or variant calling.
- CNV, structural variants (SV), mitochondrial variants (MT), repeat expansions and other non-SNV/small-INDEL pipelines.
- Silent conversion of gVCF reference blocks or symbolic alleles into ordinary small-variant records.
- Clinical interpretation, phenotype ranking, ACMG classification or sign-out as part of the normalizer itself. These are downstream stages and must consume only validated, published outputs through their defined contracts.

Out-of-scope records must be identified and handled according to explicit policy. They must not be silently discarded, rewritten as supported variants, or allowed to contaminate the SNV/INDEL output.

## 4. Required end-to-end stage sequence

Map each step to the actual existing service, domain model, task, API, UI and tests before changing code. Preserve the existing architecture.

### VCF-01 — Receipt and immutable source preservation

- Receive the uploaded file into controlled storage.
- Record tenant, case, sample association, uploader/actor, timestamp, original filename as untrusted metadata, declared assembly/specification if provided, declared file type, byte size and storage identity.
- Compute SHA-256 over the exact received bytes; preserve byte count and content identity.
- Preserve original bytes unchanged and make the source artifact immutable after successful receipt.
- Treat filename and extension as hints only; determine actual format from content.
- Prevent path traversal, archive/path injection, decompression bombs, unbounded resource use and unsafe content-type assumptions.
- Reject or quarantine incomplete uploads; do not create a clinically usable artifact from a partial transfer.
- Record receipt and validation states distinctly.

**Evidence:** source hash/size, storage object identity/version, receipt event, negative tests for truncated/hostile inputs, immutable-source regression.

### VCF-02 — Compression and container integrity

Support and distinguish:
- Uncompressed VCF text.
- Ordinary gzip-compressed VCF.
- BGZF-compressed VCF.

Requirements:
- Detect compression from bytes, not filename.
- Validate complete stream integrity, decompression completion, CRC/trailer and truncation behavior using correct library/tooling.
- Do not treat ordinary gzip as BGZF.
- Do not treat BGZF as ordinary gzip merely because it is gzip-compatible.
- Only permit indexed random access when the compression/index combination supports it.
- If a workflow requires BGZF, perform conversion as a separately recorded transformation; never silently relabel or mutate the source.
- Bound decompressed size, record count, CPU, memory and wall-clock time under documented operational limits.

**Evidence:** real plain/gzip/BGZF files, corrupt/truncated streams, false extensions, oversized-input protections and positive/negative index compatibility tests.

### VCF-03 — VCF structural and semantic validation

Validate at minimum:
- Header begins with a valid VCF fileformat declaration supported by compatibility policy.
- Header metadata syntax and required column header structure.
- Fixed columns, field counts and ordering.
- CHROM, POS, ID, REF, ALT, QUAL, FILTER and INFO parsing.
- FORMAT/sample columns, sample cardinality and genotype syntax where present.
- INFO/FORMAT declarations, Number and Type compatibility, duplicate/conflicting declarations and undeclared-field policy.
- Allele syntax, symbolic alleles, breakends and spanning-deletion representations.
- Missing values and missing fields without converting missingness into numeric zero or a false biological assertion.
- Record ordering and duplicate policy.
- Multi-allelic record handling and allele-index semantics.
- VCF version-specific constructs and constraints.
- Site-only VCF and multi-sample VCF behavior.
- Empty/header-only files and zero-record files under explicit policy.
- Malformed text/encoding behavior under explicit policy.
- Reference allele validation as a distinct, reference-dependent validation step.

A parser accepting a file does not prove normative conformance. Maintain a requirement-level matrix mapping each applicable specification clause to implementation behavior, tests, result and evidence. A smoke fixture is not full conformance.

### VCF-04 — Specification compatibility and normative coverage

- Define supported VCF versions explicitly, including VCFv4.0 through VCFv4.5 as required by the current qualification objective.
- Distinguish normative specification versions from legacy compatibility targets. The current PR description records VCFv4.0 as a legacy parser smoke target and VCFv4.1–4.5 as the normative VCF documents currently indexed; verify this against authoritative specification sources and document it.
- Pin authoritative specification URLs, source revisions/download hashes where available, and retrieval dates.
- Extract requirements into atomic, reviewable clauses. Preserve clause identifiers and exact source references.
- For each clause record applicability, requirement statement, implementation location, positive test, negative/boundary test, evidence location, status, reviewer and rationale.
- Cover VCFv4.0, v4.1, v4.2, v4.3, v4.4 and v4.5 separately. Do not infer one version's conformance from another.
- Version-gated features must be accepted/rejected according to declared version and policy.
- Unsupported clauses must remain visibly unsupported/unqualified; do not mark them passed because fixtures happen to parse.

**Gate:** No claim of complete VCF normative coverage until every applicable clause is dispositioned and all mandatory clauses have passing evidence or an explicitly approved, documented exclusion.

### VCF-05 — Reference assembly and package identity

For each execution, require an explicit assembly selection: GRCh37 or GRCh38. Never infer it solely from contig names, file naming, user geography or a VCF header comment.

Reference package identity must include:
- Assembly and sequence naming convention.
- Source/provider and release.
- Exact FASTA, FAI and required auxiliary index identities.
- Per-file SHA-256; official source checksum (e.g. MD5) where published.
- Contig dictionary/sequence identifiers and lengths.
- Package manifest/version and qualification status.
- Alias mapping, decoy/alternate contig policy and supported contig scope.
- Exact reference used by the normalizer and by REF validation.

Validate that FASTA, FAI, GZI (where applicable), sequence dictionary and any other required index belong to the same exact reference bytes. A matching filename or assembly label is not proof of matching content.

Reference mismatch must be a deterministic validation failure with actionable evidence. Never switch assembly or reference package to make a file pass.

### VCF-06 — Scope and eligibility classification

- Classify records as supported SNV, supported small INDEL, or out-of-scope/unsupported according to explicit, tested rules.
- Define maximum allele length and complex-allele policy from approved product/scientific requirements; do not invent thresholds in implementation.
- Explicitly decide handling of symbolic ALT, *, breakends, <NON_REF>, gVCF blocks, spanning deletions, mixed SNV/INDEL multiallelic records and noncanonical contigs.
- Distinguish file-level rejection from record-level exclusion/quarantine. Define whether any unsupported record blocks the file or can be preserved in a separate report; do not silently drop records.
- Preserve source record identity and exact exclusion reason.
- Do not process CNV/SV/MT/repeat expansion as SNV/INDEL.

### VCF-07 — Normalizer resource governance and executable qualification

- Resource lifecycle must preserve candidate → qualification → approval/activation semantics already implemented.
- An unqualified release must never be selected for production execution.
- Approval is laboratory/organization-controlled and scoped to explicit assembly, file/variant scope, tool release, build identity and qualification evidence.
- Resolve exact resource IDs and exact versions; verify executable path, version output, binary checksum and associated HTSlib identity at execution.
- Record exact command and parameters. Avoid shell injection; pass argument arrays through safe process execution.
- No fallback to a different version or provider on missing executable, checksum mismatch or resource outage.
- Candidate discovery and qualification may run without granting production approval.
- Keep provider adapters isolated behind existing domain contracts; do not bypass the resource registry.
- The BCFtools adapter must use the existing reference-aware normalization implementation and the selected executable, not a second independent normalization algorithm.
- GATK is a separate adapter; do not claim it is implemented or qualified unless separately delivered and tested.

#### Required BCFtools release matrix at the current baseline

The current qualification work has six target releases:

| Release | Acquisition/build path recorded at baseline |
|---|---|
| 1.23.1 | Conda-installed release |
| 1.23.2 | Source-built from pinned source |
| 1.23.3 | Source-built from pinned source |
| 1.24 | Conda-installed release |
| 1.24.1 | Source-built from pinned source |
| 1.25 | Conda-installed release |

Before execution, verify the matrix against the actual repository manifest and current approved scope. Do not silently substitute another release. For every release, capture:
- BCFtools exact version and binary SHA-256.
- HTSlib exact version/commit and library/binary identity and SHA-256.
- Source commit/tag and source provenance for source builds.
- Build environment, compiler/toolchain and build commands.
- Dependency/submodule commit identities.
- Runtime linkage and executable resolution.
- Qualification result per assembly and dataset.

For source builds, acquire complete, immutable source trees. Initialize and verify pinned submodules (including htscodecs where applicable), build HTSlib correctly before linking BCFtools when required by the upstream build procedure, and verify the resulting binary. A successful checkout is not a successful build. Do not patch around a broken build without identifying the exact upstream/build-system cause.

### VCF-08 — Reference-aware normalization

The approved normalization policy must explicitly define and test:
- REF allele validation against the exact selected reference.
- Left alignment of indels in repetitive sequence contexts.
- Parsimonious trimming of common prefix/suffix where applicable.
- Multiallelic handling: retain or split only according to approved policy that correctly transforms GT and allele-specific INFO/FORMAT annotations.
- Genotype and ploidy preservation.
- INFO/FORMAT field preservation and semantics after transformations.
- Record ordering and contig ordering.
- Duplicate record behavior.
- Symbolic/out-of-scope allele behavior.
- Header and metadata preservation/rewriting rules.
- Missing values, phase, phasing separators and allele-index remapping.
- No change to biological meaning other than the explicitly authorized normalization transformation.

Never assume splitting multiallelic records is harmless. Allele-specific fields (including Number=A, Number=R and Number=G) and genotype allele indices must be transformed correctly or the record must be rejected/retained under approved policy.

Normalization must be deterministic for the same source, reference, executable, policy and parameters. Exact command, arguments, environment/resource identities and exit status must be captured.

### VCF-09 — Post-normalization validation and concordance

After normalization:
- Re-parse the entire output using the declared VCF specification policy.
- Validate every REF allele against the exact reference.
- Validate sort order, record syntax, sample/header consistency, INFO/FORMAT declarations and allele/genotype semantics.
- Verify normalized output compression/index integrity where applicable.
- Compare source and normalized records with a scientifically correct equivalence method that accounts for allowed representation changes.
- Prove no unintended record loss, duplication, sample loss, genotype change, allele change or annotation corruption.
- Account for explicitly excluded records and provide exact reasons/counts.
- Verify output hashes and sizes after finalization.
- Do not equate byte-for-byte inequality with biological discordance; do not equate matching record counts with concordance.
- Any unexplained discordance blocks publication.

### VCF-10 — Atomic publication, provenance and audit

- Publish only after all mandatory pre-publication validations pass.
- Use temporary/staging outputs and atomic promotion/commit semantics; incomplete output must never appear as a completed normalized artifact.
- Store source and normalized artifacts separately, linked through immutable identifiers.
- Persist source digest, output digest, reference package identity, VCF specification, normalizer provider/resource ID, exact version, executable checksum, HTSlib identity, exact command/parameters, timestamps, actor/worker, job/run IDs, validation outcomes and evidence references.
- Record state transitions and reason codes in an append-only/auditable manner consistent with existing architecture.
- Make retries safe; do not overwrite a previously published artifact or erase historical execution records.
- Ensure tenant and case authorization applies to human and worker/system operations.
- Provide a reproducible provenance record sufficient for an independent reviewer to reconstruct what ran and why.

### VCF-11 — Worker reliability and recovery

Test real workflow behavior for:
- Worker loss before execution, during execution, after tool completion but before persistence, during artifact upload and during final publication.
- Task retry, duplicate delivery and replay.
- Lease/lock expiry and stale worker handling.
- Idempotency keys and unique constraints.
- Partial output cleanup/quarantine.
- Recovery from temporary storage, database, resource registry and object-store outages.
- Resource becoming unavailable between preflight and execution.
- Resource qualification/approval changing between preflight and execution.
- Tenant context and authorization for worker/system tasks.
- Parent/child execution lineage and reproducibility comparison.
- No duplicate published artifact, orphaned state, false success or lost audit event.

A unit test of a helper is not proof of end-to-end worker recovery. At least one real integration test must exercise the actual worker, database, queue and storage boundaries used by the production architecture.

### VCF-12 — Production runtime and frontend traceability

- Execute the real workflow inside the production backend container/image, not only on the CI host.
- Verify non-root execution, least privilege, read-only application filesystem where appropriate, controlled writable volumes, resource limits, signal handling and process cleanup.
- Verify the selected BCFtools/HTSlib executable is present and exactly the qualified build.
- Confirm production image and CI qualification use the same locked dependencies and configuration.
- Frontend must expose meaningful stage state, selected assembly/reference, selected normalization resource/version, validation outcomes, progress, retryable/blocked reason, failure reason, artifact lineage and audit history according to existing authorization.
- UI must not show complete until backend publication and verification are complete.
- Do not expose sensitive file contents, secrets, filesystem paths or cross-tenant metadata.
- Accessibility, error clarity and state consistency are mandatory.

## 5. Required real-data qualification

### 5.1 Public reference datasets

At the recorded baseline, qualification targets real NIST GIAB HG002 chromosome 1 data for both assemblies:
- GRCh38: HG002 VCF plus its matching GRCh38 reference package.
- GRCh37: HG002 VCF plus the selected Ensembl release-75 chromosome 1 reference package.

This is **full chromosome 1 qualification**, not whole-genome qualification. Reports and user-facing statements must use that exact scope.

Before every qualification run:
1. Resolve and record authoritative public source URLs.
2. Verify official MD5 checksums where the source publishes them.
3. Independently calculate local SHA-256 for every downloaded input and reference component.
4. Verify FASTA/FAI/GZI/dictionary relationships and exact assembly identity.
5. Record dataset accession/release, source, retrieval timestamp, file sizes and checksum outcomes.
6. Preserve acquisition logs and manifests.
7. Fail acquisition if checksums or resource relationships do not match; do not continue using corrupted or mismatched files.

Do not invent a source URL, MD5, SHA-256, release or qualification result. Retrieve it from the authoritative source and retain evidence.

### 5.2 Required execution matrix

Run **all six exact BCFtools releases** against **both GRCh38 and GRCh37** using real HG002 chromosome 1 data. This means twelve independently recorded release × assembly qualification cells.

Each cell must capture:
- Exact input and reference hashes.
- Exact BCFtools/HTSlib identities and binary hashes.
- Exact command and parameters.
- Process exit code and complete stdout/stderr.
- Start/end timestamps and runtime.
- Output artifact and index hashes.
- Post-normalization validation.
- Source/output concordance and record accounting.
- Test report and explicit PASS/FAIL/BLOCKED status.

A release that passes one assembly does not pass the other. A release that builds but does not execute on both assemblies is not qualified. A CI job that stops early must leave unexecuted cells marked NOT RUN, not PASS.

### 5.3 Qualification limitations

GIAB data is a high-quality benchmark resource, not a substitute for complete clinical laboratory validation across all sample types, variant contexts, instruments, callers, populations and operational conditions. State exactly what this qualification demonstrates and what it does not.

## 6. Test and verification strategy

Tests must be layered and mapped to requirements.

| Layer | Required evidence |
|---|---|
| Unit | Parsers, validators, classification rules, checksum logic, resource selection, command construction, state transitions |
| Property/fuzz | Parser robustness, malformed records, compression edge cases, bounded resource use, invariants |
| Contract | API/domain schemas, resource lifecycle, artifact/provenance contracts |
| Integration | PostgreSQL, queue/worker, storage, resource registry, real executable invocation |
| Real-data | HG002 chromosome 1 GRCh37 and GRCh38, all six releases |
| Production-container | Same qualified binaries and data path inside production image |
| Reliability | Worker loss, retries, replay, atomic publication and idempotency |
| Frontend | Stage state, errors, resource/assembly visibility, authorization and no false completion |
| Regression | Full backend, frontend, migration, security and CI suites |

Minimum negative and boundary cases include:
- Invalid/missing VCF version, unsupported version and version-gated feature mismatch.
- Malformed headers, columns, INFO/FORMAT declarations, genotype syntax and allele representation.
- Plain gzip mislabeled as BGZF and BGZF mislabeled as gzip.
- Truncated stream, corrupt CRC/trailer, corrupt BGZF block and invalid index.
- TBI/CSI validation, including compressed CSI representation; do not assume CSI bytes begin with raw uncompressed magic on disk.
- Empty/header-only VCF and sites-only VCF.
- Single- and multi-sample records; haploid/diploid and missing genotypes; phased/unphased calls.
- Multi-allelic SNV/INDEL, Number=A/R/G annotation remapping.
- Symbolic ALT, <NON_REF>, *, breakend, gVCF blocks and out-of-scope record policy.
- Wrong REF allele, wrong assembly, contig aliases and unknown contigs.
- Repetitive-region indels, left-alignment and trimming.
- Duplicate records and unsorted records.
- Missing/unqualified provider, changed executable checksum, missing executable, mismatched HTSlib and resource approval revocation.
- Tool nonzero exit, timeout, OOM, worker termination and storage/database outage.
- Replay, duplicate task delivery and crash at every publication boundary.
- Tenant isolation and worker authorization.

All tests must be deterministic, independently runnable where practical, and produce actionable diagnostics. Avoid brittle shell text checks when a behavioral test can verify the contract more directly.

## 7. Evidence package — mandatory deliverable

Create a machine-readable and human-readable qualification package. Use existing repository conventions where available; do not invent a parallel evidence system.

At minimum retain:
1. Run manifest with commit SHA, workflow/run/job IDs and timestamps.
2. Dataset acquisition manifest with exact URLs, official MD5, local SHA-256, sizes and retrieval dates.
3. Reference package manifest including FASTA, FAI, GZI/dictionary hashes and contig metadata.
4. Tool manifest for all six releases including BCFtools, HTSlib, source commit/tag, build environment and binary checksums.
5. Twelve-cell release × assembly qualification matrix.
6. Exact commands/parameters, exit codes, stdout/stderr and environment summary.
7. Input/output VCF and index hashes.
8. Validation reports and source/output concordance reports.
9. VCF normative clause matrix for v4.0–v4.5.
10. Test reports for unit, integration, reliability, production-container and full regression suites.
11. Failure logs and remediation references; never overwrite failure evidence with a later successful run.
12. A reviewed acceptance report with known limitations and explicit gate disposition.

Evidence must be durable, discoverable from the PR and retained workflow artifacts, and linked from the stage acceptance report. Temporary files may be cleaned only after required evidence has been preserved and verified.

## 8. Completion gates — all mandatory

A gate is PASS only when its evidence is present, reviewed and linked. Use only PASS, FAIL, BLOCKED, NOT RUN or NOT APPLICABLE with written rationale. “Mostly done”, “works locally” and “CI green” are not valid statuses.

| Gate | Acceptance condition |
|---|---|
| G0 Architecture | Existing contracts and dependencies audited; no duplicate path or unauthorized redesign |
| G1 Intake | Immutable source receipt, identity, hashes, secure storage and negative tests |
| G2 Compression/index | Plain/gzip/BGZF semantics, integrity and CSI/TBI behavior proven |
| G3 VCF parser | Structural and semantic validation across declared versions and file shapes |
| G4 Normative coverage | Clause-level VCFv4.0–4.5 matrix dispositioned with evidence |
| G5 Reference | GRCh37/38 exact package identity, checksum and FASTA/index coherence proven |
| G6 Eligibility | SNV/small-INDEL scope and all out-of-scope policies tested |
| G7 Resource governance | Exact version, qualification, approval, no fallback and executable integrity proven |
| G8 Normalization | Approved normalization semantics, genotype/annotation preservation and deterministic behavior proven |
| G9 Post-validation | Full output validation, record accounting and biological concordance proven |
| G10 Real-data qualification | All 12 BCFtools × assembly cells pass on real HG002 chromosome 1 data |
| G11 Production runtime | Real execution in production container with correct binary/resource identity |
| G12 Reliability | Worker loss/retry/replay/idempotency/atomic publication proven end-to-end |
| G13 Security/tenancy | Authorization, isolation, input hardening and safe process execution verified |
| G14 Frontend traceability | User-visible state and provenance match backend truth; no false completion |
| G15 Regression/CI | Full required CI green on exact final PR head; no ignored or unexplained failures |
| G16 Evidence/review | Complete evidence package retained and independently reviewable |

**Stage completion rule:** Every applicable gate G0–G16 must be PASS. A gate may be NOT APPLICABLE only with explicit scientific/product rationale and owner approval. BLOCKED, NOT RUN or FAIL means the stage is not complete.

Passing these gates establishes the defined SIRALOOM stage qualification. It does not, by itself, authorize a clinical laboratory to claim ISO 15189 accreditation or replace each laboratory's own validation/verification and quality-system obligations.

## 9. Engineering execution order

Do not jump to downstream work while a prerequisite is unresolved. Reorder only when repository evidence proves a dependency requires it, and record the reason.

1. **E0 — Re-establish repository truth:** inspect PR #282, current head, diff, CI, failed jobs, architecture docs, current code, manifests and existing evidence. Confirm no unreviewed concurrent change.
2. **E1 — Baseline and gap matrix:** map every G0–G16 gate and VCF-01–VCF-12 requirement to existing implementation, tests and evidence. Mark actual status; no optimistic inference.
3. **E2 — Fix qualification infrastructure:** reproducible public-data acquisition, checksums, reference/index coherence, pinned source builds, complete HTSlib/submodule dependencies, reproducible binary verification.
4. **E3 — Real-data execution:** run and preserve all six releases on both assemblies. Diagnose failures at the correct layer; do not call build failures normalization failures.
5. **E4 — VCF specification and parser coverage:** complete version-specific clause extraction, requirement mapping, fixtures, parser tests and gaps.
6. **E5 — Compression/index and intake completeness:** exercise plain/gzip/BGZF, malformed streams, CSI/TBI and real file variants.
7. **E6 — Normalization correctness:** prove reference-aware left alignment, trimming, multiallelic/genotype/annotation behavior and concordance.
8. **E7 — Workflow reliability and provenance:** real worker/database/queue/storage crash/retry/replay, tenant context and atomic publication.
9. **E8 — Production container:** real qualification execution inside production image, binary parity and runtime security.
10. **E9 — Frontend and operational traceability:** ensure the UI faithfully exposes backend truth and laboratory governance.
11. **E10 — Final regression and independent evidence review:** rerun full required suites on final exact head, inspect all artifacts, close every gate, publish acceptance report.
12. **E11 — User review and merge decision:** present evidence-backed outcome. Merge only with explicit authorization.

## 10. CI failure triage protocol

For every failed run:
1. Identify exact workflow run ID, commit SHA, job ID, step and first causal error.
2. Classify failure: source acquisition, checksum, reference/index, build/toolchain, executable resolution, application logic, scientific output, test assertion, infrastructure, permissions, timeout or unrelated CI.
3. Read full relevant logs and inspect artifacts before editing.
4. Reproduce the failure at the narrowest faithful layer; preserve the failing log.
5. State whether the failure invalidates scientific evidence, blocks execution only, or is unrelated.
6. Fix the root cause, not the assertion or evidence collection that exposed it.
7. Add a regression test for the root cause.
8. Run focused tests, then relevant integration/real-data tests, then full CI.
9. Verify the new run is on the exact current PR head and inspect all jobs.
10. Never report fixed until the failure is absent in a completed run and the new evidence passes.

A green CI status on an earlier commit does not validate a later commit. A skipped, cancelled, queued or timed-out job is not a pass.

## 11. Agent continuity and handoff protocol

This section is mandatory for every agent, model, developer or session that touches this stage.

### 11.1 Before doing work

The agent must:
- Read this entire contract.
- Read the current PR description and relevant architecture/implementation specifications.
- Fetch current PR head SHA and branch state.
- Inspect latest CI run and all jobs/steps/logs.
- Inspect current working tree/diff and recent commits.
- Read existing stage status ledger and evidence manifests.
- Confirm the exact next incomplete task and its prerequisites.

Do not ask the user to repeat information already recorded here or in repository evidence. Do not assume the baseline SHA/run remains current.

### 11.2 Before making a change

Write a short execution plan containing:
- Current phase and gate.
- Exact task and why it is next.
- Dependencies.
- Files/modules expected to change.
- Scientific and architectural risk.
- Focused tests and required real-data/CI verification.
- Evidence that will be produced.
- Explicit non-goals.

Keep changes narrow and reviewable. Avoid mixing unrelated fixes.

### 11.3 After every task or interruption

Update the stage status ledger in the repository with:
- Timestamp and agent/session identifier.
- Branch, PR and exact commit SHA.
- Task completed and files changed.
- Commands/tools actually executed.
- Tests actually run with exact results.
- CI run/job IDs and status.
- Real datasets/resources actually used and their hashes.
- Evidence artifact paths/links.
- Failures, root causes, unresolved risks and blocked dependencies.
- Next exact task and acceptance test.

If context or usage limits are approaching, stop at a safe boundary, commit/push only a coherent verified change, update the ledger and leave a precise handoff. Do not start a large task that cannot be completed or safely checkpointed.

### 11.4 Mandatory handoff message template

Every outgoing agent must leave this report:

**Mission:** SIRALOOM VCF Intake and Normalization stage; do not change scope.  
**Contract:** docs/implementation/VCF_INTAKE_NORMALIZATION_STAGE_EXECUTION_CONTRACT.md  
**Current PR/branch:** exact URL and branch  
**Current head:** full commit SHA  
**Current gate/task:** exact ID  
**Completed in this session:** only verified work  
**Tests and evidence:** exact commands, counts, run IDs, artifact links  
**Failures:** exact root cause and whether fixed/reproduced  
**Not completed:** explicit list  
**Risks/blockers:** exact dependency and owner/action  
**Next action:** one precise task with files and acceptance criteria  
**Do not:** list prohibited actions or known traps

A new agent must resume from the ledger and current GitHub state—not from an informal chat summary.

## 12. Current baseline snapshot — revalidate before acting

This is a historical snapshot captured 2026-11-03, not a live status claim.

- Repository: SayedaRehmat/SIRALOOM.
- Open PR: [#282 — Govern VCF normalization engines through laboratory-approved resources](https://github.com/SayedaRehmat/SIRALOOM/pull/282).
- Branch: feature/vcf-normalization-capability-governance.
- Recorded head: 7b8abebf95d07c9eb6ce1ec00c6c5fe25e31d9c8.
- Latest recorded workflow: [run #3202](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/41627304151). Its final outcome was not verified when this document was drafted. Re-fetch it; do not assume pass or failure.
- Previous run #3201: backend regression reported 2,373 passed and 46 skipped; frontend and PostgreSQL/Celery worker-loss integration passed. Real-data BCFtools qualification failed during source build because the HTSlib htscodecs submodule source was absent. This was a source-build/acquisition failure, not proof of a normalization algorithm defect.
- Subsequent commit 7b8abeb pinned BCFtools and HTSlib source commits and initialized/verified the htscodecs submodule. Whether this fully fixes the build must be established from run #3202 logs; do not infer success from the patch.
- Earlier CSI regression work corrected the assumption that on-disk CSI begins with raw CSI magic; CSI is BGZF-compressed and requires compression-aware validation. Regression tests were included and passed in run #3201.
- Recorded real-data target is full chromosome 1 HG002 for GRCh37 and GRCh38, not whole genome.
- VCFv4.0–4.5 clause-level normative coverage remains required; candidate extraction and smoke fixtures are not full conformance.
- Current PR description states GATK is a separate adapter and is not implemented by PR #282.
- PR #282 has not been authorized for merge. Keep it open until all acceptance gates and user review are complete.

## 13. Decision and change control

- This contract defines the stage goal and mandatory acceptance standard.
- Existing approved architecture specifications and ADRs remain authoritative for system design. If this contract appears to conflict with an approved architecture decision, stop and document the conflict; do not silently override either document.
- Scientific policy decisions (for example, multiallelic splitting, unsupported record handling, reference aliases, contig scope and normalization parameters) require documented domain-owner approval and tests.
- Any proposed relaxation of a gate requires explicit user approval and a recorded decision with impact and residual risk. Agents cannot waive requirements on their own.
- Changes to this contract require a version increment, change rationale, affected gates, migration/compatibility implications and user approval.
- Do not edit completed modules or change public contracts merely to make a test pass. Demonstrate a genuine defect and preserve backward compatibility where required.

## 14. Definition of success

The VCF stage is complete only when SIRALOOM can take a real supported VCF, preserve and identify the original bytes, validate the file and assembly under a declared specification, execute a specifically approved normalizer release against the exact approved reference, prove the normalized output is valid and biologically concordant under the approved transformation policy, publish it atomically, recover safely from failures, expose truthful traceability to authorized lab users, and reproduce the result from retained evidence.

The result must be independently inspectable by another engineer and bioinformatics reviewer without relying on the memory of the agent that implemented it.

**No shortcuts. No silent substitutions. No unsupported success claims. No stage completion without evidence.**


## 15. Additional laboratory operations requirements (version 1.1)

The following requirements are mandatory and are defined in full in the companion operational specification:

[VCF_INTAKE_NORMALIZATION_LAB_OPERATIONS_ERROR_PERFORMANCE_SPECIFICATION.md](./VCF_INTAKE_NORMALIZATION_LAB_OPERATIONS_ERROR_PERFORMANCE_SPECIFICATION.md)

The companion specification expands the stage with:
- Producer metadata and sample-manifest reconciliation.
- Explicit separation of file/representation QC, variant-call QC and upstream sequencing/assay QC.
- Versioned laboratory policy and producer profiles.
- Stable error codes, structured error envelopes, dispositions and safe retry rules.
- Specific intake, compression, index, header, record, sample, version, reference, scope, normalizer, post-validation, capacity, storage, database, worker, policy, security and internal error classes.
- Performance workload classes, phase timing, resource limits, capacity controls and measured service objectives.
- Safe performance optimization, profiling and scientific-equivalence requirements.
- Structured logs, metrics, traces, operator troubleshooting, alerting and incident handling.
- Data retention, backup/restore, tenant isolation, encryption, secure temporary storage and software supply-chain controls.
- Standards/interoperability boundaries, including VCF, HTSlib/BCFtools, GATK, GA4GH VRS, ISO 15189, CLSI MM09 and CDC/APHL guidance.

The additional acceptance gates G17–G23 are mandatory and extend, rather than replace, G0–G16:

| Gate | Acceptance condition |
|---|---|
| G17 Producer/sample interoperability | Producer metadata, sample manifest reconciliation, multisample/sites-only profiles and profile versioning tested |
| G18 Error taxonomy and recovery | Stable codes, dispositions, safe retry matrix, user/operator diagnostics and regression tests |
| G19 Performance and capacity | Representative workload benchmarks, phase timing, resource limits, throughput objectives and regression tests |
| G20 Observability/troubleshooting | Structured logs/metrics/traces, runbooks, root-cause visibility and alert scenarios verified |
| G21 QC provenance | File QC, variant-call QC and upstream assay QC distinguished; no unsupported assay-QC claims |
| G22 Data lifecycle/security | Retention, encryption, least privilege, tenant isolation, secure temp handling, backup/restore and evidence access verified |
| G23 Change/incident control | Resource/policy change impact, rollback/deactivation, affected-run discovery and incident audit tested |

The same completion rule applies: every applicable gate must be PASS with inspectable evidence or have an explicitly approved NOT APPLICABLE disposition. Documentation alone does not close a gate.

## 16. Contract change history

- **1.0 (2026-11-03):** Initial VCF intake and normalization master execution contract.
- **1.1 (2026-11-03):** Added mandatory laboratory operations, producer/sample interoperability, error taxonomy, recovery, performance/capacity, observability, QC provenance, data lifecycle/security and change/incident requirements through the companion specification; added gates G17–G23.
