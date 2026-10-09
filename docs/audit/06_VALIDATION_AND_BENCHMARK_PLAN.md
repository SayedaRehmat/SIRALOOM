# Scientific and operational validation plan

## Objective

Demonstrate reproducible technical correctness and bounded behavior for the explicitly supported workflow. This is software validation and benchmark concordance, not independent clinical validation.

## Test layers

1. **Unit tests:** parsers, coordinate/allele handling, reference access, resource identity, eligibility rules, state transitions, report versioning.
2. **Integration tests:** PostgreSQL transactions/migrations, API authorization, artifact storage, dispatch outbox, worker execution, provider adapters and workflow persistence.
3. **End-to-end tests:** browser/API → artifact → worker → resource stages → review → report/export, with captured IDs/hashes.
4. **Scientific concordance:** compare normalized variants and annotation/evidence outputs against suitable independent references or expert-adjudicated expected results.
5. **Failure injection:** broker unavailable, provider timeout/429, worker loss, lease expiry, partial artifact write, disk pressure, stale resource, rejected release and missing required resource.
6. **Security/adversarial:** tenant isolation, role boundaries, malicious uploads, resource configuration, indirect object access and quota bypass.
7. **Operational drills:** backup restore, deployment rollback, migration upgrade, worker restart and monitoring/alert delivery.

## Dataset and fixture strategy

- Use public, appropriately licensed truth sets such as Genome in a Bottle (GIAB) HG001 for a defined small-variant region/build and documented benchmark version.
- Maintain tiny synthetic fixtures for edge cases not represented adequately in benchmark data: multiallelic INFO/FORMAT cardinality, left-shiftable indels, REF mismatch, contig aliases, symbolic alleles, breakends, GVCF blocks, phased/missing genotypes, malformed headers and compressed-input failures.
- Keep input hashes, license/usage terms, reference build/package checksum, expected outputs, tool versions and fixture provenance under version control.
- Do not use identifiable patient data in public CI or demonstrations.

## Metrics

- Validation: expected accept/reject and error-code concordance.
- Normalization: record-level concordance after applying the same declared policy; compare position/REF/ALT and genotype/INFO/FORMAT semantics, not just row counts.
- Annotation: transcript/consequence agreement by defined transcript policy and version; record provider differences explicitly.
- Evidence/ACMG: criterion-level agreement against expert-adjudicated cases, including direction, strength, eligibility, conflicts and review-required outcomes.
- Workflow: no lost dispatch, no duplicate logical result, no silent state completion, no mutation of historic outputs.
- Security: zero unauthorized cross-tenant reads/writes in the defined adversarial matrix.
- Operations: measured throughput, resource use, failure recovery time, queue age, restore success and artifact integrity.

Acceptance thresholds must be predeclared from intended use, reference method, risk analysis and expected discrepancy policy. Do not invent sensitivity/specificity or concordance values.

## Required release packet per benchmark run

- Git commit and deployment image digest.
- Dataset release/license and input SHA-256.
- Reference package ID/build/checksum.
- BCFtools/VEP/provider versions and exact command/config.
- Resource plan hash and organization-approved binding IDs (redacted where necessary).
- Raw expected/observed results and discrepancy adjudication.
- Test runner version, environment and timestamps.
- Failures, exclusions, limitations, reviewer and approval.
