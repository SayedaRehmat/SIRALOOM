# SIRALOOM VCF Intake and Normalization — Laboratory Operations, Error Handling and Performance Specification

**Document ID:** SIRALOOM-VCF-OPS-001  
**Version:** 1.0  
**Status:** Mandatory technical supplement to SIRALOOM-VCF-MEC-001  
**Owner:** Platform Engineering and Bioinformatics Engineering  
**Baseline date:** 2026-11-03  
**Scope:** VCF intake, validation, reference selection, SNV/small-INDEL normalization, output validation and publication

---

## 1. Purpose and governing principles

A laboratory-grade VCF stage must be scientifically correct, operationally predictable, performant under declared workloads, diagnosable when something goes wrong, recoverable without data corruption, and auditable after the event.

This supplement makes the following mandatory:

- Every failure has a stable machine-readable code, severity, category, owner, disposition and user-safe explanation.
- Retry is permitted only when the failure is plausibly transient and replay is safe.
- Input/scientific integrity failures are never retried as if they were infrastructure outages.
- Performance is measured against representative workloads and explicit service objectives; it is not optimized by weakening validation.
- All expensive work is bounded by resource quotas, deadlines and cancellation behavior.
- Operators can distinguish queue delay, data transfer, parsing, reference access, normalization, compression, indexing, validation and publication time.
- A run is reproducible from immutable inputs, locked resources, exact commands and retained evidence.
- Performance optimizations must preserve the scientific output contract and pass equivalence/regression tests.

The platform supports laboratory workflows; it does not itself confer ISO 15189 accreditation or replace a laboratory's QMS, local verification, intended-use validation or regulatory obligations.

## 2. Additional laboratory capabilities that must be addressed

### 2.1 Producer and submission contract

Laboratories receive VCFs from multiple callers, sequencers, pipeline vendors and internal bioinformatics systems. The intake contract must therefore record and validate, where supplied:

- Producing organization and laboratory.
- Producer pipeline name, version, build/container identity and configuration fingerprint.
- Caller and annotation tool names/versions, where known.
- Original reference assembly, reference accession/package and contig naming convention.
- VCF version, compression format and index type.
- Sample identifiers and expected sample manifest.
- Whether the input is variant-only VCF, gVCF, cohort VCF or another declared profile.
- Whether records are germline or somatic, and relevant ploidy/sex-chromosome policy when the upstream workflow supplies this metadata.
- Declared quality/QC report references and their provenance.
- Transfer mechanism, source object identity, receipt time and checksum.

Unknown metadata must be represented as unknown, not guessed. A declared producer profile may select additional validation rules, but must never bypass baseline validation. A laboratory may register multiple producer profiles; each profile is versioned, approved and auditable.

### 2.2 Sample and case reconciliation

Before processing:
- Reconcile VCF sample columns with the case's authorized sample manifest.
- Detect missing, unexpected, duplicate or renamed sample identifiers.
- Enforce tenant and case association.
- Preserve exact sample-column order and identity.
- Explicitly handle single-sample, multisample, sites-only and cohort files.
- Never silently rename, reorder, merge or drop samples.
- Where a case expects one sample but the VCF contains multiple samples, block for policy resolution rather than guessing.
- Where identity confirmation is performed upstream, retain the upstream assertion and provenance; do not claim that VCF metadata alone proves biological identity.

### 2.3 QC context and limitations

The stage must distinguish:

1. **File and representation QC:** integrity, parseability, headers, records, sample structure, reference concordance and normalization correctness.
2. **Variant-call QC:** caller-provided QUAL/FILTER, genotype quality, depth, allele balance, callability and related fields.
3. **Sequencing/assay QC:** coverage, uniformity, contamination, mapping, duplication, sample identity and assay performance, generally generated upstream from reads or laboratory processes.

SIRALOOM's VCF-only stage can assess category 1 and inspect/preserve category 2 fields. It cannot independently recreate category 3 from a VCF. It must not claim that an input passed assay QC unless a qualified upstream QC report is supplied, validated against a producer profile and explicitly recorded. Missing upstream QC must be a visible metadata state or policy block, not an invented pass.

### 2.4 Laboratory policy profiles

Support organization-controlled, versioned policy profiles for:
- Accepted producer profiles and VCF versions.
- Allowed assembly/reference package and contig scope.
- Sample cardinality and expected sample IDs.
- Supported record classes and handling of mixed/out-of-scope files.
- Maximum input/decompressed size, record count, allele length and runtime/resource quotas.
- Required input metadata and upstream QC evidence.
- Normalizer resource and parameter selection.
- Output compression/index requirements.
- Retention and evidence access.
- Warnings that require review versus blocking errors.

Profiles must be immutable once used by a run. A profile change creates a new version; historical executions retain the old profile identity. Defaults must be explicit and versioned. No hidden organization override may weaken platform safety invariants.

### 2.5 Laboratory quality and change management

Provide operational support for:
- Controlled resource qualification and release.
- Change-impact assessment for tool, reference, parser, policy and container changes.
- Regression evidence before activation.
- Rollback/deactivation of a resource version without rewriting historical runs.
- Incident and deviation records with affected run/resource identification.
- Reanalysis impact discovery when a resource or policy is later found defective.
- Controlled retention, retrieval and export of evidence for laboratory review.
- Role-based separation between submitter, operator, reviewer, resource approver and administrator where supported by the established identity architecture.
- Audit events for manual overrides, retry, cancellation, release activation and result disposition.

## 3. Error taxonomy and required disposition model

### 3.1 Structured error envelope

Every error or warning must use a stable structured envelope, adapted to existing API/domain conventions rather than introducing a parallel error framework.

Required logical fields:
- Stable machine-readable error code.
- Category: INPUT, FORMAT, REFERENCE, SCIENTIFIC, POLICY, RESOURCE, EXECUTION, CAPACITY, STORAGE, DATABASE, SECURITY or INTERNAL.
- Severity: INFO, WARNING, ERROR or FATAL.
- Disposition: REJECT, QUARANTINE, BLOCK, RETRY, CANCELLED or REVIEW_REQUIRED.
- Retryable flag derived from classified cause and state.
- Stage and stage step.
- Concise user-safe message.
- Protected operator diagnostic detail with sensitive data redacted.
- Source artifact, case, run and attempt identifiers where available.
- Resource ID/version, reference package ID and policy version where relevant.
- Timestamp, correlation/trace ID and worker identity.
- Evidence references: logs, validation report, checksums or quarantined artifact.
- Remediation instruction and escalation owner.

Never return raw stack traces, secrets, internal filesystem paths, SQL, credentials or unredacted sample/genomic data in ordinary user-facing errors. Authorized operators may access protected diagnostic evidence.

### 3.2 Disposition semantics

| Disposition | Meaning | Required behavior |
|---|---|---|
| REJECT | Input is invalid or incompatible under declared contract | Stop processing; preserve source and findings; no normalized artifact |
| QUARANTINE | Integrity or safety concern requires isolation | Prevent downstream use; preserve evidence; require authorized disposition |
| BLOCK | Required policy/resource/metadata decision is missing | Keep run visible and resumable after blocker resolution; no silent fallback |
| RETRY | Transient failure with safe replay semantics | Bounded exponential backoff with jitter, attempt history and deadline |
| CANCELLED | Authorized user/system cancellation | Stop child processes, clean temporary data safely, retain audit history |
| REVIEW_REQUIRED | Technically processable but requires authorized human decision | Do not publish as approved/usable until disposition is recorded |

A warning does not become a pass. Warnings must be categorized and governed by a policy profile. Any warning affecting scientific interpretation or output eligibility must block or require review.

### 3.3 Minimum error catalogue

Implementation must map actual code paths and tests to these identifiers. Extend codes through reviewed change control.

| Code | Failure condition | Category | Disposition | Retry? | Required handling |
|---|---|---|---|---|---|
| VCF-IN-001 | Upload interrupted or byte count incomplete | INPUT | RETRY or REJECT | Transfer only | Resume/restart safely; never process partial bytes |
| VCF-IN-002 | Received bytes differ from declared checksum | INPUT | QUARANTINE | No | Preserve bytes and mismatch evidence; request verified retransmission |
| VCF-IN-003 | Input exceeds configured byte/decompressed-size limit | CAPACITY | REJECT or BLOCK | No, unless quota approved | Report measured/allowed limits; no partial success |
| VCF-IN-004 | Content does not match declared file type | FORMAT | REJECT | No | Report detected format safely; require corrected submission |
| VCF-IN-005 | Unsafe archive, path traversal or decompression-bomb pattern | SECURITY | QUARANTINE | No | Stop processing and create protected security evidence |
| VCF-CM-001 | Unsupported compression or malformed container | FORMAT | REJECT | No | Distinguish plain, ordinary gzip and BGZF |
| VCF-CM-002 | Truncated gzip/BGZF stream or CRC/trailer failure | FORMAT | QUARANTINE | No | Preserve source and require retransmission |
| VCF-CM-003 | Invalid BGZF block structure | FORMAT | REJECT | No | Do not treat ordinary gzip as BGZF |
| VCF-IDX-001 | Index missing when required by selected operation | FORMAT | BLOCK | Conditional | Create only if policy permits and source is valid/sorted; record transformation |
| VCF-IDX-002 | TBI/CSI invalid, stale or incompatible with data | FORMAT | REJECT or BLOCK | No blind retry | Verify index/data relationship; rebuild only as recorded transformation |
| VCF-HDR-001 | Missing/invalid fileformat declaration | FORMAT | REJECT | No | Report header and version detection |
| VCF-HDR-002 | Malformed/conflicting header or invalid INFO/FORMAT declaration | FORMAT | REJECT or REVIEW_REQUIRED | No | Apply versioned policy; do not silently rewrite |
| VCF-REC-001 | Malformed record columns, field count or coordinate | FORMAT | REJECT | No | Report line/record/coordinate |
| VCF-REC-002 | Invalid REF/ALT syntax or genotype/FORMAT value | FORMAT | REJECT | No | Report field and record identity |
| VCF-REC-003 | Invalid INFO/FORMAT Number or Type cardinality | FORMAT | REJECT | No | Report expected and observed cardinality |
| VCF-REC-004 | Unsorted records or duplicate records against policy | FORMAT | BLOCK or REJECT | No | Sorting only as explicit transformation; duplicates require policy |
| VCF-SMP-001 | VCF samples differ from expected case manifest | POLICY | BLOCK | After authorized correction | Never rename/drop samples silently |
| VCF-SMP-002 | Duplicate, missing or unexpected sample columns | FORMAT/POLICY | REJECT or BLOCK | No automatic retry | Preserve exact header and reconciliation report |
| VCF-VER-001 | Unsupported VCF version or invalid version-gated construct | FORMAT | REJECT | No | Report declared version and offending feature |
| VCF-REF-001 | Assembly/reference selection missing or ambiguous | REFERENCE | BLOCK | After explicit selection | Never infer assembly silently |
| VCF-REF-002 | REF allele does not match selected reference | SCIENTIFIC | REJECT | No | Report reference package, coordinate and expected/observed allele |
| VCF-REF-003 | FASTA/FAI/GZI/dictionary/package hashes inconsistent | REFERENCE | QUARANTINE | No | Mark package unusable; preserve manifest |
| VCF-REF-004 | Contig absent, alias unresolved or contig policy violated | REFERENCE | BLOCK or REJECT | Only after approved policy | Never silently rename contigs or switch reference |
| VCF-SCP-001 | Unsupported symbolic, SV, MT, repeat or gVCF representation | POLICY | BLOCK or REVIEW_REQUIRED | No | Preserve and classify; do not route into SNV/INDEL normalizer |
| VCF-SCP-002 | Mixed supported and unsupported records | POLICY | BLOCK or REVIEW_REQUIRED | No | Apply approved file/record policy with exact record accounting |
| VCF-NRM-001 | Normalizer not approved/qualified for requested scope | RESOURCE | BLOCK | After approval | No fallback |
| VCF-NRM-002 | Executable missing or checksum/version/HTSlib mismatch | RESOURCE | BLOCK/QUARANTINE | After controlled repair | Never execute unverified binary |
| VCF-NRM-003 | Normalizer exits nonzero or emits malformed output | EXECUTION | BLOCK | Conditional | Preserve command, exit, stdout/stderr and partial output |
| VCF-NRM-004 | Output differs beyond approved equivalence policy | SCIENTIFIC | QUARANTINE | No blind retry | Block publication and investigate |
| VCF-NRM-005 | Same locked inputs produce nondeterministic output | SCIENTIFIC | QUARANTINE | No | Preserve both outputs and environment manifests |
| VCF-VAL-001 | Post-normalization parser/REF/sort/index validation fails | SCIENTIFIC | QUARANTINE | No | No publication; preserve output and report |
| VCF-VAL-002 | Sample/genotype/allele-specific annotation changed unexpectedly | SCIENTIFIC | QUARANTINE | No | Compare source/output with allele-aware semantics |
| VCF-VAL-003 | Unexplained record loss, duplication or concordance mismatch | SCIENTIFIC | QUARANTINE | No | Require exact source-to-output accounting |
| VCF-RES-001 | Temporary/output storage exhausted | CAPACITY/STORAGE | RETRY after recovery | Bounded | Stop safely; never publish partial output |
| VCF-RES-002 | Memory limit/OOM termination | CAPACITY | BLOCK or conditional retry | Not blindly | Record peak memory/workload; prevent retry storm |
| VCF-RES-003 | Execution deadline exceeded | CAPACITY | BLOCK or conditional retry | Conditional | Record phase timing/resource use; no indefinite extension |
| VCF-IO-001 | Object storage/network transient failure | STORAGE | RETRY | Yes | Bounded retry and checksum verification |
| VCF-IO-002 | Storage permission or tenant access denied | SECURITY | BLOCK | No blind retry | Audit and investigate authorization |
| VCF-DB-001 | Database transient connection/serialization failure | DATABASE | RETRY | Yes | Retry transaction safely and idempotently |
| VCF-DB-002 | State/unique constraint conflict or stale worker write | DATABASE | BLOCK/reconcile | Conditional | Enforce ownership; never overwrite newer state |
| VCF-WRK-001 | Worker lost before/during/after tool execution | EXECUTION | RETRY/reconcile | Safe boundary only | Reconcile process/output; use lease and idempotency |
| VCF-WRK-002 | Duplicate task delivery or replay | EXECUTION | Existing run/no-op | Not a new execution | Enforce idempotency and unique publication |
| VCF-WRK-003 | Cancellation requested | EXECUTION | CANCELLED | No | Terminate child process group and record cleanup |
| VCF-POL-001 | Policy changed or approval revoked during run | POLICY | BLOCK | After fresh authorization | Revalidate policy/resource snapshot |
| VCF-SEC-001 | Unauthorized tenant/case/resource access | SECURITY | BLOCK | No | Deny, audit and alert |
| VCF-INT-001 | Unexpected exception or invariant violation | INTERNAL | BLOCK | No automatic loop | Protected diagnostics, correlation ID and defect/incident |

### 3.4 Retry policy

- Retry only classified transient failures: selected network/storage/database errors, worker loss and explicitly recoverable infrastructure interruptions.
- Use bounded exponential backoff with jitter, maximum attempts, overall deadline and per-error policy.
- Never retry malformed input, reference mismatch, unsupported scope, invalid checksum, unqualified resource, deterministic output mismatch or parser conformance failure.
- Recheck authorization, policy version, resource approval and resource checksum before resuming.
- Give each attempt a unique ID and immutable attempt record.
- Resume only from a verified safe checkpoint or restart the affected transformation from immutable source; never append to an uncertain partial VCF.
- Quarantine partial outputs or remove them only after evidence preservation.
- Exhausted retries transition to a visible operator-action state.
- Prevent retry storms with queue limits, circuit breakers and per-tenant fairness.

## 4. Performance engineering and throughput qualification

### 4.1 Performance is a qualified property

Do not invent universal seconds-per-GB targets. Establish service objectives from measured representative workloads and explicit laboratory operating envelopes. Benchmark the actual production container, storage class, reference package, tool versions and worker configuration.

Benchmark at least:
- Small single-sample VCF.
- Typical single-sample exome VCF.
- Large single-sample genome VCF.
- Multisample/cohort VCF.
- High-indel-density or annotation-heavy VCF.
- Highly compressed and poorly compressible inputs.
- Many-contig files and files with large INFO/FORMAT fields.
- Worst-case valid inputs within declared product limits.

Record exact file sizes, compressed/decompressed bytes, record count, sample count, allele distribution, contig distribution and metadata. Tiny synthetic fixtures are not sufficient performance evidence.

### 4.2 Required phase timing

Record monotonic start/end and duration for:
1. Upload/receipt.
2. Checksum calculation.
3. Compression detection and integrity scan.
4. Header and full-record parse/validation.
5. Sample reconciliation.
6. Reference preflight and index access.
7. Normalizer startup/resource verification.
8. Normalization.
9. Output compression/index creation.
10. Post-normalization validation.
11. Source/output concordance and record accounting.
12. Artifact upload/checksum verification.
13. Atomic publication/database commit.
14. Queue wait and total wall-clock time.

Expose phase timing to authorized operators. Distinguish queue wait from execution. Report bytes/sec and records/sec where meaningful, CPU time, peak RSS, temporary disk, I/O bytes and retry counts.

### 4.3 Resource and capacity controls

- Define per-job CPU, memory, temporary-disk, file-descriptor, process-count and wall-clock budgets.
- Define tenant-level concurrency and queued-work limits.
- Reserve capacity for system operations and prevent one large cohort from starving small cases.
- Use bounded queues and backpressure.
- Size concurrency from CPU, memory, storage bandwidth and measured process behavior, not CPU count alone.
- Prevent concurrent jobs from exhausting shared scratch space.
- Enforce quotas before expensive processing where possible.
- Record actual peak resource use against configured budgets.
- Handle termination signals and cancellation by terminating the complete child process group and preserving state.
- Use unique permission-restricted temporary directories per attempt.
- Perform disk-space preflight with a safety margin and recheck during long operations.

### 4.4 Safe optimization opportunities

Evaluate and benchmark without weakening validation:

- Stream between compatible stages to avoid redundant full-file materialization.
- Use BCF as an internal intermediate only when supported operations preserve output semantics, annotations, genotypes and provenance; preserve original input and required VCF output.
- Avoid unnecessary repeated decompression/recompression and repeated full scans; consolidate only when the same validation requirements are satisfied.
- Use BGZF block-aware streaming and appropriate buffer sizes.
- Use reference indexes and sequential access patterns correctly.
- Avoid loading entire VCFs into application memory; use bounded chunks and backpressure.
- Avoid N+1 database operations and per-record API calls; use bounded batch persistence.
- Use bulk object-store transfers and multipart upload where supported, followed by full checksum verification.
- Reuse immutable reference packages and verified local caches keyed by exact content digest.
- Cache only deterministic immutable artifacts with complete input/resource/policy identities in cache keys.
- Use region-level parallelism only after proving boundary-safe indel normalization, ordering, deduplication, headers, sample semantics and concordance.
- Benchmark compression level and thread count on production-like data.
- Do not assume BCFtools --threads parallelizes all variant processing; documented threading primarily affects compression/decompression.
- Profile parsing and validation code before replacing it with lower-level implementations.
- Preserve every validation check protecting scientific integrity; optimize implementation, not acceptance criteria.

### 4.5 Performance acceptance tests

For each workload class, retain:
- Dataset and input hash.
- Exact container image digest.
- CPU/memory/disk/network configuration.
- Tool/resource/reference/policy identities.
- Cold-cache and warm-cache results where relevant.
- Median, p95 and worst observed wall time.
- Throughput, CPU utilization, peak RSS, peak disk and I/O.
- Queue wait and per-stage timing.
- Output hash and scientific equivalence result.
- Failure/retry behavior under resource pressure.

Set service objectives only after baseline measurements and agreement with product/laboratory owners. Regression thresholds must account for measurement variance and hardware class. A performance change fails qualification if it changes scientific outputs, provenance, security or reliability.

## 5. Troubleshooting and observability

### 5.1 Required observability

Provide structured logs, metrics and distributed traces/correlation across API → queue → worker → external tool → storage → database → frontend state.

Minimum metrics:
- Upload success/failure and bytes received.
- Validation errors by stable code and producer profile.
- Files, records and samples processed.
- Compression type and decompression ratio.
- Per-phase duration and total wall time.
- Queue depth, wait time, worker utilization and concurrency.
- CPU, memory, disk, I/O and process exit codes.
- Tool/resource version and reference package identity.
- Normalization output count, excluded/out-of-scope count and concordance.
- Retry counts, worker losses, stale leases and idempotent replays.
- Storage/database dependency errors.
- Publication latency and incomplete/quarantined artifact counts.

Do not place PHI, direct identifiers, raw genotype data, full VCF lines or secrets in general telemetry labels. Use controlled IDs and protected evidence references.

### 5.2 Operator troubleshooting sequence

The operator view/runbook must answer:
1. Did the file arrive completely? What are size and SHA-256?
2. Does actual content match declared compression and format?
3. Did compression/index integrity pass?
4. Did parser and sample reconciliation pass?
5. Which VCF version and producer profile were applied?
6. Which exact assembly/reference package and hashes were selected?
7. Did REF and contig checks pass?
8. Was the normalizer approved, qualified and checksum-verified?
9. Did the process start? What command, exit code and duration?
10. Did it hit CPU, memory, disk, timeout or dependency limits?
11. Did post-validation and concordance pass?
12. Was output uploaded and checksum-verified?
13. Was atomic publication committed?
14. If retried, which attempt/checkpoint resumed and why was replay safe?

Link the first causal error and downstream consequences. Do not show a cascade of secondary errors without identifying root cause.

### 5.3 Alerts and incident handling

Alert on sustained queue growth, worker saturation, repeated resource failures, storage exhaustion, checksum mismatches, unexplained scientific discordance, publication inconsistencies and security events. Provide runbooks for detection, containment, evidence preservation, recovery and escalation.

For suspected scientific defects, quarantine affected outputs and identify runs using the same tool/reference/policy version. Support resource deactivation and impact analysis without rewriting historical records. Record incident timeline, scope, root cause, corrective action, verification and approval. Never automatically retry a suspected scientific or integrity defect.

## 6. Data lifecycle, continuity and security

- Define retention, archival, deletion and legal-hold policy for source VCFs, normalized VCFs, indexes, manifests, logs and evidence. Policies must be tenant- and jurisdiction-aware.
- Encrypt data in transit and at rest using approved controls; protect keys and secrets through managed services.
- Apply least-privilege access to source, normalized files, temporary storage, logs and evidence.
- Enforce tenant isolation at API, worker, storage and database layers.
- Define RPO/RTO for service and evidence recovery; test restore, not just backup creation.
- Define secure deletion for temporary and retention-expired data, subject to legal hold and immutable audit requirements.
- Ensure exported evidence includes a manifest and integrity hashes.
- Protect against malicious filenames, symlinks, decompression bombs, parser denial-of-service, shell injection, untrusted header content and unsafe temporary paths.
- Do not log secrets or expose genomic data in telemetry.
- Pin and scan container images and dependencies; retain SBOM/build provenance where supported.
- Verify signed/trusted release artifacts where available; record source commit, build recipe and resulting binary digest.

## 7. Interoperability and standards alignment

Review and pin authoritative sources in the repository:
- VCF specifications: https://github.com/samtools/hts-specs
- HTSlib and BCFtools: https://www.htslib.org/doc/ and https://samtools.github.io/bcftools/
- GATK ValidateVariants: https://gatk.broadinstitute.org/hc/en-us/articles/360036823891-ValidateVariants
- GA4GH Variation Representation Specification: https://vrs.ga4gh.org/ and https://www.ga4gh.org/product/variation-representation-specification-vrs/
- ISO 15189:2022 overview: https://committee.iso.org/standard/15189
- CLSI MM09, third edition: https://clsi.org/shop/standards/mm09/
- CDC/APHL NGS Quality Initiative: https://www.cdc.gov/lab-quality/php/pathway/pathway-to-testing.html
- ACGS bioinformatics pipeline software guidance: https://www.acgs.uk.com/media/10790/ngs_bioinformatics_bpg_final_version_2016.pdf
- GIAB/NIST benchmark resources: https://www.nist.gov/programs-projects/genome-bottle

Use VRS as a variant representation/interoperability framework, not as a reason to silently replace VCF normalization policy. Conventional VCF left-normalization and GA4GH VRS fully-justified allele normalization are related but not identical. If SIRALOOM adopts VRS identifiers/objects, implement that as a separately versioned representation layer while retaining source VCF and approved normalized VCF semantics.

A downstream vendor's accepted VCF profile is not a universal standard. For example, a vendor may require GT fields or reject NON_REF for its particular workflow. Such rules may inform a named interoperability profile but must not be misrepresented as universal VCF requirements.

Cross-tool validation should use independent parsers/validators where feasible. Differential validation must distinguish normative disagreement, parser differences and policy differences. A successful parse by one tool is not proof of universal conformance.

## 8. Additional acceptance gates

Add these gates to the master contract's G0–G16. Existing gates remain mandatory.

| Gate | Acceptance condition |
|---|---|
| G17 Producer/sample interoperability | Producer metadata, sample manifest reconciliation, multisample/sites-only profiles and profile versioning tested |
| G18 Error taxonomy and recovery | Stable codes, dispositions, safe retry matrix, user/operator diagnostics and regression tests |
| G19 Performance and capacity | Representative workload benchmarks, phase timing, resource limits, throughput objectives and regression tests |
| G20 Observability/troubleshooting | Structured logs/metrics/traces, runbooks, root-cause visibility and alert scenarios verified |
| G21 QC provenance | File QC, variant-call QC and upstream assay QC distinguished; no unsupported assay-QC claims |
| G22 Data lifecycle/security | Retention, encryption, least privilege, tenant isolation, secure temp handling, backup/restore and evidence access verified |
| G23 Change/incident control | Resource/policy change impact, rollback/deactivation, affected-run discovery and incident audit tested |

Each new gate requires implementation, tests, production-like execution and retained evidence. A policy document alone does not close a gate.

## 9. Implementation order

Do not interrupt the current E0/E1 repository truth audit to implement performance optimizations prematurely.

1. Map existing error/result/state models and exception handling to this catalogue.
2. Map worker retry, idempotency, timeout, cancellation, process cleanup and publication boundaries.
3. Map logging, metrics, tracing, run records and frontend diagnostics.
4. Map resource limits, upload limits, queue controls and tenant fairness.
5. Establish representative benchmark data and production-container baselines.
6. Add missing error handling and observability at existing architecture boundaries.
7. Optimize only after profiling identifies measured bottlenecks.
8. Add regression and failure-injection tests for each behavior.
9. Verify performance changes against scientific output equivalence and complete provenance.
10. Close G17–G23 only after implementation, tests, production-like execution and retained evidence pass.

## 10. Non-goals and safeguards

- Do not promise fixed runtime independent of file size, samples, storage and hardware.
- Do not optimize by skipping validation, reducing checksum coverage, weakening REF validation, dropping records or accepting ambiguous assemblies.
- Do not assume more threads always means faster execution.
- Do not split by genomic interval without proving safe boundary normalization and recombination.
- Do not turn vendor-specific input rules into universal platform rules.
- Do not treat VCF-only QC as full sequencing/assay QC.
- Do not claim accreditation from software tests alone.
- Do not add a second workflow engine, error framework, resource registry, telemetry stack or artifact-lineage model if an approved equivalent already exists. Extend the frozen architecture.

## 11. Completion rule

The VCF stage cannot be called laboratory-ready until master gates G0–G16 and additional gates G17–G23 are all PASS or have an explicitly approved NOT APPLICABLE disposition. Performance must be measured on representative workloads; error handling must be tested through real failure injection; operational recovery must be proven end-to-end.

The standard is not "it ran once." A laboratory must be able to submit supported data, understand exactly what happened, receive a scientifically validated result, recover safely from failures, reproduce execution and obtain evidence suitable for its own quality system.

## 12. Research basis and source-derived boundaries

These public sources support the operational additions. They do not replace full licensed standards or local regulatory advice.

1. ISO 15189:2022 defines requirements for medical laboratory quality and competence and applies to laboratory management systems and competence assessment: https://committee.iso.org/standard/15189
2. CLSI MM09, third edition (2023), provides recommendations for design, validation, implementation and continuing quality management of sequencing-based tests. Its published scope notes that detailed bioinformatics guidance is addressed in a future CLSI document; do not claim MM09 alone specifies every software engineering control: https://clsi.org/shop/standards/mm09/
3. CDC/APHL NGS Quality Initiative provides a validation/maintenance pathway aligned with Quality System Essentials and CLIA crosswalks, while stating it is not a stand-alone QMS: https://www.cdc.gov/lab-quality/php/pathway/pathway-to-testing.html
4. ACGS guidance addresses development and validation of software used in clinical genetics: https://www.acgs.uk.com/media/10790/ngs_bioinformatics_bpg_final_version_2016.pdf
5. GATK ValidateVariants demonstrates checks beyond basic parsing, including REF correctness, chromosome count checks and allele presence: https://gatk.broadinstitute.org/hc/en-us/articles/360036823891-ValidateVariants
6. GA4GH VRS addresses interoperable computable variant representation and normalization; fully-justified allele normalization must not be conflated with conventional VCF left-normalization: https://vrs.ga4gh.org/en/stable/conventions/normalization.html
7. BCFtools performance guidance recommends BCF/uncompressed BCF streams in compatible multi-command pipelines and warns that --threads primarily affects compression/decompression rather than all processing: https://samtools.github.io/bcftools/howtos/scaling.html
8. HTSlib/BCFtools indexing documentation defines CSI/TBI behavior and coordinate limits: https://www.htslib.org/doc/bcftools.html
9. VarSome Clinical submitted-VCF requirements illustrate workflow-specific consumer requirements such as explicit SNV/INDEL alleles and valid GT fields. These are vendor-specific, not universal VCF rules: https://docs.varsome.com/en/submitted-vcf-requirements
10. Illumina DRAGEN QC documentation illustrates distinct VCF, runtime and coverage metrics. SIRALOOM must distinguish upstream metrics from metrics calculable from VCF alone: https://support-docs.illumina.com/SW/DRAGEN_v38/Content/SW/DRAGEN/QCMetricsCoverageReports_fDG_dtSW.htm

Pin exact source versions/revisions and review dates in the repository's normative clause matrix. These links are research starting points, not proof that every clause has been mapped to implementation.
