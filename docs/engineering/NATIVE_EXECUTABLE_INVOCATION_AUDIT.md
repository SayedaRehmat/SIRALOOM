# Native Executable Invocation Audit

**Audit date:** 2026-11-06  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Baseline:** `main` at `840a4487cc7e61111a1347d321fdddd402679496`  
**Architecture record:** PR #295, branch `architecture/universal-execution-audit-20261106`

## Executive result

The application currently invokes at least two native scientific executables in production workflow paths:

1. **BCFtools** — invoked synchronously by the API during VCF intake and index validation, and asynchronously by the analysis worker during multiallelic preparation and reference-aware normalization/sort/index.
2. **Ensembl VEP** — invoked locally by the analysis worker through a governed local/offline binary and cache contract.

This finding is important: removing BCFtools from the API image today would break VCF intake and uploaded-index validation. The API is not yet tool-neutral.

Separate qualification/benchmark scripts also invoke BCFtools and hap.py. Those are engineering/validation tools, not normal case-processing API endpoints.

This audit is based on the production call paths and high-likelihood executable entry points inspected on the audited ref. It is an invocation inventory, not a proof that every optional script, external deployment wrapper or operator-supplied plugin in the entire repository has been exhaustively enumerated. The next code change should add automated source-level inventory checks and runtime boundary tests so future executable additions cannot silently bypass the contract.

## Production invocation inventory

### 1. BCFtools — synchronous API VCF intake

**Entry point**
- `POST /cases/{case_id}/artifacts`
- `backend/app/api/v1/artifacts.py`, upload handler calls `_validate_vcf_for_upload(staged)`.
- `_validate_vcf_for_upload` calls `backend.app.domain.ingestion.validate_vcf(path)`.

**Native invocation**
- `backend/app/domain/ingestion.py::_bcftools_validate`
- Resolves `settings.bcftools_executable` using `shutil.which`.
- Runs `bcftools --version` and parses both BCFtools and HTSlib versions.
- Requires exact equality with `settings.bcftools_version` and `settings.htslib_version`.
- Runs `bcftools view --no-version -Ov -o /dev/null <staged-vcf>` to structurally parse the uploaded VCF.
- Then the application performs its own strict VCF parsing and specimen/sample/build checks.

**Execution boundary**
- API process, synchronous inside the upload HTTP request.
- Uses API-local scratch staging under `settings.worker_scratch_root`.
- It is not dispatched to Celery before validation.

**Inputs / outputs**
- Input: staged uploaded VCF (plain or compressed), selected GRCh37/GRCh38, optional specimen/sample mapping.
- Output: validation result and metadata including detected/expected BCFtools version, HTSlib version and BCFtools profile ID; accepted/invalid status is persisted with the artifact.
- This validation does not perform reference-aware normalization and does not consume a FASTA.

**Failure / retry**
- Missing binary, version-attestation failure, launch failure or timeout becomes `VCFValidationUnavailable`; API helper maps it to HTTP 503 with `retryable: true`.
- A syntactically rejected VCF becomes a validation error/result rather than a transient tool-unavailable condition.
- There is no durable Celery retry for this operation: the client must retry the HTTP upload. Upload idempotency support exists, but this remains a request-bound operation.
- The VCF is not accepted when the required executable cannot be attested.

**Toolchain / resource requirement**
- Uses the API container's globally configured BCFtools/HTSlib profile from `backend/app/config.py` (default 1.25 profile).
- It does not select the analysis-specific profile at this point.
- Requires the API image to contain the executable and its linked libraries.

### 2. BCFtools — synchronous API uploaded-index validation

**Entry point**
- Same `POST /cases/{case_id}/artifacts` endpoint when the uploaded artifact is TBI or CSI and has a paired primary VCF.
- `backend/app/api/v1/artifacts.py` stages the paired VCF and index, then calls `validate_index(...)`.

**Native invocation**
- `backend/app/domain/ingestion.py::validate_index` delegates to `validate_vcf_index_concordance` in `backend/app/domain/vcf_tools.py`.
- `vcf_tools.py` probes `bcftools --version`.
- `_validate_vcf_index_record_counts` runs:
  - `bcftools index --stats <vcf>`
  - `bcftools view --no-header --regions-overlap 0 --regions <contig> <vcf>` for each contig.
- Indexed record counts and SHA-256 digests are compared against a sequential BGZF scan.

**Execution boundary**
- API process, synchronous inside the index-upload HTTP request.
- The primary VCF is materialized/staged locally before validation.

**Inputs / outputs**
- Input: exact paired BGZF VCF plus one TBI or CSI index.
- Output: index type and concordance evidence, persisted as artifact validation metadata.
- Does not require a reference FASTA; it verifies index-to-file concordance, not reference identity.

**Failure / retry**
- Missing executable, timeout or version mismatch is surfaced as validation unavailable and mapped to HTTP 503 with `retryable: true`.
- Index/query disagreement is a validation failure, not a transient retry.
- No durable Celery retry; the caller must retry the request after a transient infrastructure failure.

**Toolchain / resource requirement**
- API container's global BCFtools/HTSlib profile, currently the default profile.
- This is another reason the API image cannot yet be made tool-neutral.

### 3. BCFtools — worker multiallelic splitting

**Entry point**
- Analysis workflow in `backend/app/workflows/variant.py`.
- The normalization path calls `split_multiallelic_vcf` from `backend/app/domain/vcf_tools.py` when multiallelic records need to be split.

**Native invocation**
- `bcftools norm --no-version -m -any -N -Ov --multi-overlaps . -o <output> <input>`.

**Execution boundary**
- Celery analysis worker, not the API request process.
- Input artifacts are materialized from laboratory storage to worker-local filesystem paths before scientific tools run.

**Inputs / outputs**
- Input: routed sequence VCF.
- Output: biallelic VCF with conservative genotype/overlap handling; provenance records tool, version and profile.
- This step intentionally does not perform reference-aware left alignment; the subsequent normalization stage does that using the selected reference package.

**Failure / retry**
- Missing executable or non-zero command result raises `VCFToolError`.
- The normalization resource execution is recorded FAILED when this step fails.
- Celery's analysis task retries only errors translated to `TransientWorkflowError`; ordinary `VCFToolError` is not automatically a transient retry by the task wrapper. Worker-loss redelivery/recovery is a separate mechanism and must not be confused with application-level retry.
- This is a gap for future generic executor error classification: executable unavailable, temporary disk failure, timeout, invalid input and reference mismatch need distinct retry policies.

**Toolchain / resource requirement**
- Worker profile is checked against the analysis's persisted BCFtools/HTSlib profile before the task claims execution.
- The worker's BCFtools executable and HTSlib are pinned by its image/profile.
- No FASTA is used in this splitting command.

### 4. BCFtools — worker reference-aware normalization, sorting and CSI indexing

**Entry point**
- `backend/app/workflows/variant.py`, normalization stage, calls `normalize_vcf_with_bcftools(...)`.
- The selected reference package is resolved for the analysis build and its FASTA is materialized locally.

**Native invocations**
- `bcftools --version` — verify exact BCFtools and HTSlib pair.
- `bcftools view --no-version -A -Oz` — prepare GVCF wildcard handling.
- `bcftools norm --no-version -f <reference.fa> -c e -m -any --multi-overlaps . --old-rec-tag SIRALOOM_ORIG -Oz` (with governed handling when source mapping already exists).
- `bcftools sort -Oz`.
- Conditional `bcftools view --no-version -Oz` for source-only FORMAT field preservation.
- `bcftools index --csi --force`.
- `bcftools index --stats` and per-contig indexed `bcftools view` queries for post-build index concordance.

**Execution boundary**
- Celery analysis worker.
- The command sequence runs in a private temporary directory on the destination filesystem. Existing output/index files are preserved until all transformations and index validation pass; publication uses atomic replacement with rollback handling.
- Worker task checks that the analysis profile matches the worker profile before execution.

**Inputs / outputs**
- Inputs: routed sequence VCF, selected reference FASTA and index, analysis build (GRCh37/GRCh38), profile-specific source-only FORMAT policy.
- Outputs: sorted BGZF normalized VCF, CSI index, reference identity, version/profile provenance, command metadata, index concordance and source-child reconciliation evidence.
- Reference identity is checked before and after normalization; reference mismatch fails closed.

**Failure / retry**
- Each command has an explicit timeout and checks its exit code and expected output.
- Failures raise `VCFToolError`; the resource execution is durably marked FAILED and the stage fails.
- As above, ordinary `VCFToolError` is not automatically retried by `run_analysis_task`; only explicit `TransientWorkflowError` is passed to Celery retry. Worker loss is recovered through the separate interrupted-execution/redelivery path.
- This must be preserved and generalized, not weakened during executor refactoring.

**Toolchain / resource requirement**
- Exact analysis-persisted BCFtools profile and matching HTSlib.
- Exact selected reference package and FASTA; build compatibility is required.
- Worker scratch space must be large enough for prepared, normalized, sorted and temporary outputs.

### 5. Ensembl VEP — worker-local offline annotation

**Entry point**
- Annotation stage in `backend/app/workflows/variant.py` constructs the VEP provider from the governed resource execution contract.
- Provider implementation: `backend/app/adapters/annotation/vep.py::VEPProvider`.

**Native invocations**
- `<vep_binary> --version` for runtime version attestation.
- `<vep_binary> --offline --cache ... --show_cache_info` for offline cache verification.
- `<vep_binary> --offline --cache --format vcf --json ... --input_file <input.vcf> --output_file <output.json> ...` for annotation.

**Execution boundary**
- Celery analysis worker; local process invocation through Python `subprocess`.
- VEP is launched in its own process group; timeout kills the process group to avoid orphaned child processes.
- It is not an Ensembl REST request in this provider implementation.

**Inputs / outputs**
- Input: batch of variants converted to a temporary VCF, explicit GRCh37/GRCh38 assembly.
- Output: governed JSON annotation records and response digest/checkpoint.
- Resource contract requires absolute binary/cache/manifest paths, exact VEP version, cache version, assembly, binary SHA-256 and cache manifest/tree provenance. Optional FASTA is used for HGVS/HGVSG options.
- Cache/assembly pairing is checked before annotation.

**Failure / retry**
- Timeout is retryable; exit codes 137/143 are retryable; missing executable and most non-zero errors are non-retryable.
- Workflow catches retryable VEP provider errors, records the failed execution, checkpoints the batch as RETRYING and raises `TransientWorkflowError`.
- Celery retries the analysis task with bounded retries (task wrapper maximum 3, subject to the workflow error's own max retry value).
- Non-retryable provider errors mark the batch failed.

**Toolchain / resource requirement**
- VEP is independently pinned through the governed resource execution contract, not through the BCFtools profile registry.
- Requires local binary, local offline cache, cache manifest, matching assembly, sufficient temporary disk and any declared FASTA.
- This is evidence that the existing platform already has a second executable-tool contract, but it is implemented separately from the BCFtools profile model.

## Qualification / engineering executables (not normal case API execution)

| Script | Executables | Purpose | Scope |
|---|---|---|---|
| `scripts/validation/run_giab_benchmark.py` | BCFtools, hap.py | Prepare/normalize query, select sample, run truth-set concordance | Explicit benchmark invocation; versions pinned by benchmark manifest |
| `scripts/validation/run_giab_concordance.py` | hap.py | Run controlled GIAB small-variant concordance | Explicit benchmark invocation; validates runtime version and captures runinfo |
| `scripts/validation/run_vcf_scale_benchmark.py` | Calls BCFtools normalization implementation | VCF scale/performance qualification | Explicit benchmark, not an API endpoint |
| `scripts/validation/run_vcf_qualification_matrix.py` | subprocess-driven qualification runner | VCF qualification matrix | Explicit CI/operator qualification |
| `scripts/build_bcftools_from_profile.sh` | HTSlib/BCFtools build tools and produced BCFtools utilities | Reproducible source build, version pairing and binary checks | Image build time, not runtime analysis |

The GIAB scripts are not a replacement for a production caller integration. The hap.py comparison evaluates a caller-produced query VCF against a truth set; it does not itself generate the query callset.

## Toolchain configuration and service-boundary finding

- `backend/app/config.py` exposes deployment-level `bcftools_executable`, `bcftools_version`, `htslib_version` and `bcftools_profile_id`.
- `backend/app/infrastructure/queue/celery_app.py::run_analysis_task` validates the persisted analysis profile against the worker's configured profile before claiming execution. A mismatched worker rejects/requeues the task.
- `docker/backend.Dockerfile` installs the default BCFtools/HTSlib lock and sets the default profile/queue.
- `docker-compose.production.yml` uses the default backend image for API/default worker and has separate optional worker services for alternative source-built BCFtools profiles.
- `docker/backend-bcftools-source.Dockerfile` is the separate source-built worker image for alternate profiles.

Therefore:
1. The API image currently needs BCFtools for synchronous intake and index validation.
2. The default worker is not isolated from the API in the same way as the alternate workers.
3. VEP already has a separate binary/cache contract but not a common generic executable-profile abstraction.
4. BCFtools upload validation uses deployment-global settings, while analysis execution uses the analysis-persisted profile. The two identities must be recorded distinctly and must not be misrepresented as the same tool execution.
5. Removing BCFtools from the API image requires first moving API-side validation behind a durable execution boundary or introducing a narrowly scoped, independently qualified validation service. Simply deleting the binary is not safe.

## Gaps and recommended implementation order

### N1 — Build an enforceable executable inventory
- Add a source-level CI check that inventories executable invocation sites (subprocess APIs, shell execution, executable path resolution) in production code.
- Require every invocation to declare tool identity, version/provenance source, owning service, timeout, retry classification and input/output contract.
- Maintain an explicit allowlist with code owners for new invocations.
- Ensure benchmark/build scripts are categorized separately from production runtime.

### N2 — Unify executable tool contracts
- Generalize the existing BCFtools profile and VEP execution contract into a versioned executable profile interface.
- Keep BCFtools and VEP adapters separate behind the common contract; do not force their different resource requirements into one misleading flat schema.
- Include binary/image digest, exact version, dependencies, platform/architecture, capabilities, cache/resource identity, reference compatibility, security state and qualification evidence.

### N3 — Move API-side VCF validation out of the API process
- Preserve current fail-closed validation semantics and HTTP response contracts.
- Design a durable intake validation task/service with upload idempotency, artifact state transitions, tenant isolation, retry/recovery and explicit pending/invalid/validated states.
- Alternatively, if synchronous response semantics must remain, isolate validation in a dedicated service/image with a strict request/result contract. Do not keep scientific executables in the general API image by accident.
- Move both VCF structural validation and uploaded-index concordance consistently; do not migrate only one.

### N4 — Isolate the default BCFtools worker
- Build a dedicated 1.25 worker image with the same source/lock/provenance discipline as alternate profiles.
- Make API image tool-neutral only after N3 is complete and tested.
- Keep queue/profile fencing and analysis snapshot behaviour intact.

### N5 — Add end-to-end regression tests
- API container has no BCFtools/VEP binary after separation.
- Upload validation still rejects malformed VCFs and returns the correct retryable state on tool unavailability.
- Index validation preserves exact VCF/index concordance behaviour.
- Worker dispatch selects only the exact analysis profile.
- BCFtools and VEP worker profiles cannot consume one another's jobs.
- Worker loss, timeout, OOM/termination, retry exhaustion and artifact publication replay preserve idempotency and provenance.
- Reanalysis reproduces the selected tool profile and reference/resource identities.

## Explicit non-goals for this audit

- No tool versions were upgraded.
- No production execution behaviour was changed.
- No profile was reclassified as qualified.
- No claim is made that Kubernetes, Slurm/HPC, ARM64, offline installation or clinical validation is complete.
- No claim is made that the GIAB benchmark has run successfully on a suitably provisioned runner or produced concordance metrics.

## Decision

The first implementation PR should not remove BCFtools from the API image. It should add the executable-invocation inventory/ownership contract and then design the durable intake validation boundary. Once both VCF and index validation are no longer API-process dependencies, split the API image from the default BCFtools 1.25 worker. Generalize BCFtools and VEP behind the common executable contract in a separate, compatibility-preserving change.
