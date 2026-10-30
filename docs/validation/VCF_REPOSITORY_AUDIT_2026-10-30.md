# SIRALOOM VCF Stage Repository Audit — 2026-10-30

## Scope and evidence boundary

This audit compares the current main implementation, the VCF intake contract, normalization/indexing code, relevant regression tests, and VCF-related branches surfaced by GitHub branch search. It is a code and repository-state audit, not laboratory assay qualification. It does not claim local WSL tests were run.

## Supported format versions versus tool versions

- The declared parser policy is VCFv4.0 through VCFv4.5 in backend/app/domain/vcf_validation.py.
- The independent normalization toolchain is pinned to BCFtools/HTSlib 1.24. These are separate version axes and must be recorded and tested separately.
- VCFv4.5 local-allele cardinalities are guarded in the strict validator; the supported-version contract explicitly says recognition is not a promise of clinical semantics for every optional extension.
- Future or unknown VCF versions must remain rejected until a reviewed compatibility change and conformance corpus are available.
- Release qualification needs positive and negative fixtures for each supported VCF version, including fields emitted by each laboratory's actual caller. A single VCFv4.5 fixture is insufficient evidence for the whole range.

## Repository/PR reconciliation snapshot

- PR #222 is merged to main at 6142932970f2206fae7be6ee095e79245745c31b. Its changes cover VCFv4.0–v4.5 declarations, VCFv4.5 local-allele validation, explicit multisample selection, sites-only routing, and BCFtools/HTSlib 1.24. CI for this main commit completed successfully.
- PR #223 (fix/vcf-per-alt-genotype-semantics) contains a focused fix for per-ALT projected genotype semantics. It must remain distinct from the broader VCF qualification gate; source genotype and source FORMAT evidence must not be overwritten by a projection.
- PR #221 concerns PP3/BP4 calibration provenance and is scientifically adjacent but not a VCF parser change.
- PR #220 defines the broader laboratory workflow and release gates; it is requirements documentation, not proof that every stage is implemented.
- Branch search surfaced a large set of audit, foundation, feature, and fix branches. The search response was paginated, so this file does not claim that every branch or historical PR has been reconciled. Branch names are not evidence of implemented behavior; compare commits and inspect diffs before recovering changes.
- fix/vcf-index-concordance was previously compared against main and had no unique changes at that time. Do not assume index concordance is implemented just because a branch with that name exists.
- test/vcf-multiallelic-genotype-remapping and foundation/canonical-vcf-index are divergent historical branches and must not be merged wholesale. Recover useful changes selectively after reviewing their diffs and tests.

## Verified implementation observations

### Strengths already present

1. Strict syntax validation checks version declarations, header/record structure, ordering, genotype allele indices, and version-specific local-allele rules.
2. Multisample input requires explicit sample selection for sample-level interpretation; sites-only files are routed as site-level artifacts, not patient-level calls.
3. The record router separates or manifests reference-only, telomere, GVCF, symbolic/breakend, and unsupported records rather than silently treating all rows as ordinary SNVs/indels.
4. Reference-aware normalization uses the pinned BCFtools executable, checks the requested reference allele, splits multiallelic records, records source mapping, sorts, builds CSI, stages output before publication, and attempts rollback if publication fails.
5. Existing tests cover left alignment, REF mismatch, tool-version pinning, failed normalization/indexing preserving existing outputs, record routing, and multiallelic FORMAT cardinality.

### Gaps requiring implementation and evidence before laboratory qualification

1. VCF version conformance corpus: verify all six supported versions with representative valid and invalid files, including version-specific GT syntax, INFO/FORMAT cardinalities, optional fields, escaping, and compressed representations. Keep caller-specific extensions explicit.
2. Index-to-artifact concordance: index creation success and a non-empty CSI file are not, by themselves, evidence that indexed queries return the same records as a sequential read of the exact published BGZF artifact. Add an independent post-index integrity check and regression tests for stale, corrupt, missing, or mismatched index artifacts.
3. Record reconciliation: persist counts and hashes across immutable source, routed streams, normalized output, and exclusion manifest; assert a complete, explainable reconciliation without double-counting split child alleles as original records.
4. Source-to-child allele mapping: validate that every split child points to the correct original record and 1-based ALT index, including duplicate alleles, normalization-induced coordinate changes, multi-ALT GT, and INFO/FORMAT Number=A/R/G fields. Never treat a per-ALT projected genotype as a replacement for source GT/AD/PL evidence.
5. Reference identity: bind the reference FASTA and index to a versioned, checksummed GRCh37/GRCh38 resource; validate contig aliases/lengths and known-answer reference alleles and indels. A header declaration is not sufficient proof of reference identity.
6. Failure and scale behavior: qualify truncated/corrupt BGZF, malformed CSI, timeout, disk-full, worker crash/replay, large WES/WGS inputs, and publication interrupted between VCF/index replacement. Verify that failures remain recoverable and never leave a mismatched artifact pair advertised as complete.
7. End-to-end sample identity: carry the explicitly mapped sample identity through routing, normalization, population/evidence stages, segregation, review, and report rendering; prove no other sample's genotype can enter the case.
8. Laboratory release controls: persist caller/version/build, exact resource/tool versions, fixture corpus, acceptance thresholds, run evidence, and lab authorization. Software CI alone does not qualify an assay or clinical service.

## Next implementation order

1. Complete the PR/branch reconciliation against current main, including paginated branch results and each open PR's head/base/CI.
2. Review and resolve PR #223 with CI evidence; do not merge while checks are pending or failures remain.
3. Implement index/artifact concordance and source/routed/normalized/exclusion count reconciliation with regression tests.
4. Expand the conformance corpus across VCFv4.0–VCFv4.5 and pinned BCFtools 1.24; keep VCF-format compatibility separate from executable-version pinning.
5. Run the full repository CI and publish the precise evidence. Then proceed to the reference-known-answer and end-to-end laboratory qualification gates.

## Non-claims

This audit does not certify clinical validity, analytic validity, a laboratory assay, or production qualification. No test result is reported here unless it was observed in GitHub Actions. Local WSL test execution was not available to this audit process.
