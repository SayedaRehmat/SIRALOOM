# Stage 1 VCF laboratory qualification matrix runner

## Purpose

`run_vcf_qualification_matrix.py` turns the Stage 1 qualification ledger into an executable, controlled matrix. It does not replace the existing VCF scale benchmark. Instead, it executes that production-path benchmark once for each predeclared laboratory cell and retains the cell identity, immutable input/reference hashes, observed benchmark status, and evaluations against criteria approved before execution.

The runner deliberately stops at **REVIEW_REQUIRED**. A criterion being met is an observed result, not clinical validation, analytical acceptance, accreditation, or release authorization.

## Qualification cell definition

Each matrix cell must identify:

- assay: `WES` or `WGS`;
- exact laboratory-approved caller name;
- exact caller version;
- exact GRCh37 or GRCh38 build;
- immutable input VCF path and SHA-256;
- exact reference FASTA path and SHA-256;
- the specimen-mapped VCF sample identifier;
- an optional normalization timeout.

The `.fai` must be adjacent to the declared reference FASTA because the underlying production benchmark requires the exact FASTA/index pair. The matrix runner verifies the actual VCF and FASTA SHA-256 values while loading the manifest and repeats those checks immediately before each benchmark cell. The FAI is checked for presence here; its content hash and reference-artifact integrity are recorded and checked by the underlying scale benchmark.

Do not reuse an example manifest for execution. Copy it into a controlled laboratory workspace, replace every example value with the actual controlled record, set `status` to `CONFIGURED`, and retain the resulting manifest as part of the validation evidence package.

## Acceptance policy

The manifest must contain a laboratory-approved policy identifier, approver, effective date, and numeric criteria. Thresholds are intentionally not supplied by SIRALOOM: performance limits depend on intended use, worker resources, concurrency, caller distribution, and the laboratory's quality system.

Criteria use a dotted JSON metric path into the benchmark report, for example:

`runtime.stages.vcf_validation.wall_seconds`

Supported operators are `<=`, `<`, `>=`, `>`, and `==`.

A missing metric becomes `NOT_EVALUABLE`; it is never converted to a pass or zero. An observed value outside the criterion is retained as `OBSERVED_OUTSIDE_CRITERION` for review.

## Controlled execution

From the repository root:

```bash
python scripts/validation/run_vcf_qualification_matrix.py \
  --manifest /secure/validation/vcf-stage1-matrix.json \
  --output-dir /secure/validation-runs/vcf-stage1-matrix-001
```

The matrix runner passes the selected sample identifier to the existing benchmark through the environment rather than command-line arguments. It checks that the identifier is absent from retained benchmark JSON before accepting the cell evidence. Raw VCF content and sample names are not copied into the matrix result.

The matrix output directory and each cell directory are created with owner-only permissions (mode `0700`). Use a dedicated, access-controlled filesystem and retain its access-control/backup policy with the laboratory record. Each cell gets its own directory containing the existing benchmark evidence. The matrix-level artifact is:

`qualification-matrix.json`

A configuration or orchestration failure produces:

`qualification-matrix.failure.json`

The matrix output records only exception classes for orchestration failures, not exception messages, to reduce accidental persistence of sensitive operational text.

## Required matrix design

For a laboratory intended use covering both exome and genome analysis, define at least one controlled cell for every approved caller/version/build combination:

| Assay | Build | Caller/version | Required evidence |
|---|---|---|---|
| WES | GRCh37 | Exact approved caller/version | Executed benchmark + review |
| WES | GRCh38 | Exact approved caller/version | Executed benchmark + review |
| WGS | GRCh37 | Exact approved caller/version | Executed benchmark + review |
| WGS | GRCh38 | Exact approved caller/version | Executed benchmark + review |

Add separate cells for additional caller versions, alternate approved workflows, upper-percentile workload specimens, and variant-class stress workloads. Do not collapse different caller versions into one cell merely because they emit VCF.

## Review packet

For each executed cell, the laboratory-controlled record should link:

1. the approved policy ID and criteria version;
2. the matrix manifest SHA-256;
3. input VCF SHA-256;
4. reference FASTA/FAI identity and hashes;
5. exact caller/version/build;
6. SIRALOOM repository commit and deployment image digest;
7. worker CPU/memory/scratch/storage profile;
8. benchmark JSON and normalized output/index hashes;
9. observed wall/CPU/memory/disk and reconciliation results;
10. failure/recovery evidence where applicable;
11. reviewer, date, decision, limitations, and authorization.

The matrix runner is therefore evidence-generation infrastructure, not a clinical release gate by itself.
