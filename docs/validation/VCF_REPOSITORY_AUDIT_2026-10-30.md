# SIRALOOM VCF Stage Repository Audit — 2026-11-01

## Scope and evidence boundary

This document records a read-only review of the current GitHub implementation, relevant pull requests, VCF parsing/normalization code, regression tests, and the VCF intake contract. It is a repository and software-correctness audit, not laboratory assay qualification. No local WSL execution is claimed.

Repository: `SayedaRehmat/SIRALOOM`  
Audited main commit: `dea24dbe15cfcf050df129776ade3034b577e934`  
Audit date: 2026-11-01

## Supported format versions versus tool versions

- The declared parser policy recognizes VCFv4.0 through VCFv4.5 in `backend/app/domain/vcf_validation.py`.
- The normalization toolchain is pinned independently to BCFtools/HTSlib 1.24. File-format version and executable version are separate compatibility axes.
- VCFv4.4/v4.5 leading genotype phasing separators and VCFv4.5 local-allele cardinalities (`LA`, `LR`, `LG`, `P`, with `LAA`) have explicit validator/parser handling.
- Recognition of a version is not a claim that every optional feature, caller-specific extension, or FORMAT field has clinical semantics in SIRALOOM.
- Unknown/future major versions remain rejected until an explicit compatibility change and conformance corpus are reviewed.
- A laboratory release still requires positive and negative fixtures for every version/caller/build combination actually used. One VCFv4.5 fixture does not qualify VCFv4.0–4.5 as a family.

## Repository and pull-request reconciliation snapshot

- PR #222 is merged. It established the VCFv4.0–4.5 declaration policy, VCFv4.5 local-allele validation, explicit multisample selection, sites-only handling, and the pinned BCFtools/HTSlib toolchain.
- PR #225 is merged. It added per-contig CSI index statistics versus sequential BGZF record-count concordance.
- PR #226 is merged. It reconciles source-record counts with exclusive routing dispositions and distinguishes source-record counts from per-ALT exclusion-manifest entries.
- PR #228 is merged. It adds source-record identity and source-to-normalized-child ALT lineage reconciliation.
- PR #229 is merged at `9e44ea7badcff1fe55aab1602ff9d264acf72f19`. It attests the reference FASTA and required index artifact identities and detects mutation during attestation/normalization. Hash identity alone does not prove that FAI/GZI contents are consistent with the FASTA or prove biological assembly identity.
- PR #230 is merged at `5aaad7e0ff737ca1077a620f937ce0330534a232`. It extends CSI validation beyond record counts: per-contig indexed BCFtools query streams are compared by SHA-256 with sequential BGZF record streams. Query output is streamed to temporary files. This is stronger than count-only concordance; malformed, stale, corrupt, and real-world index qualification still require a broader fixture corpus.
- PR #232 is merged at `9f48595601c18262c44acd39fe81cf822b770361`. It preserves routed source GT and ALT-count provenance through BCFtools multiallelic normalization, retains normalized GT separately, calculates per-ALT dosage/state, preserves raw-source ALT lineage, and excludes only proven non-carriers. Its pre-merge GitHub Actions run passed backend, PostgreSQL integration, and frontend jobs.
- PR #233 is merged at `f44af5816d823859bc4400d18186c8e14ad24e27`. It adds VCFv4.5 reserved base-modification FORMAT recognition and GT/allele-sequence-aware Number=M validation, including implicit reserved aliases. Because BCFtools 1.24 does not project Number=M values to per-ALT children, these fields remain in the immutable uploaded source VCF and are omitted from the normalized SNV/INDEL artifact. Their names and source-only policy are recorded in normalization, artifact, stage, and audit metadata; the case dossier exposes the disclosure. The normalization contract and artifact identities were advanced to version 6.0. GitHub Actions run `41196521167` passed backend, PostgreSQL integration, frontend, container, and production Compose checks. Vercel preview deployment was blocked by the account's daily deployment quota; no production deployment is claimed.
- PR #234 is merged at `9b69dbca46601cc8fa7e7012a1d8c38a80f06ba8`. It validates VCFv4.5 sample-specific reference blocks, including reserved `FORMAT/LEN`, per-sample reference-block lengths, and computed/declared `INFO/END` consistency. This closes the earlier audit finding that LEN was unimplemented; it does not add gVCF reference-confidence interpretation or joint genotyping.
- PR #235 is merged at `76b1c81e4a36fc492d0f0ecb8dd3cb040e85547d`. It attests the upload toolchain and clarifies validation/source-record counts.
- PR #236 is merged at `c0de824185bd0502ed202a281aae3a0b3627bba5`. It routes mitochondrial, CNV and repeat-expansion records to preserved out-of-scope artifacts instead of treating them as ordinary SNV/INDELs.
- PR #238 is merged at `56ce76dfe12691041c8b8ab04dcdcaddbb29c7ba`. It qualifies normalization replay after durable commit; this is one recovery boundary, not proof of every-stage crash/replay.
- PR #239 is closed but not merged. Its upload-recovery work was superseded by merged PR #246; do not count #239 as shipped code.
- PR #246 is merged at `0aeb64d82f618bb8f311e9fefc8aff7d59208024`. It makes artifact uploads safely retryable.
- PR #250 is merged at `bd3bab207692dec52ae302c92914d202f65c9f03`. It stages uploads on the configured scratch volume.
- PR #251 is merged at `0cbfbb30042c610b3876ec8375efa94fb37f16be`. It fixes reportability so preserved unsupported variant classes do not block an otherwise complete in-scope SNV/INDEL sign-out; unsupported classes remain explicitly disclosed as not analysed.
- PR #252 is merged at `40be1c3be19e5fba89b61f970bad9646b3671c08`. It makes mixed VCFv4.5 variant/reference-block routing sample-aware: a missing GT is allowed through the SNV/INDEL route only when that exact sample is covered by a preceding validated reference block; the GT remains missing, while unexplained missing GTs remain unresolved. Its complete GitHub Actions suite and the fresh main-branch CI run passed backend, PostgreSQL/Celery integration, frontend, and production container checks.
- PR #253 is merged at `dea24dbe15cfcf050df129776ade3034b577e934`. It adds a privacy-conscious lab VCF processing scale benchmark harness, per-stage wall/CPU/throughput and process/child memory metrics, input/reference integrity hashes, a real pinned-BCFtools end-to-end fixture, and a runbook aligned to GA4GH VCF, ISO 15189 and CLSI guidance. Its full PR CI passed. The harness is not a WES/WGS benchmark result until run on representative lab inputs and reviewed against preapproved criteria.
- PR #245 remains open and must not be merged wholesale into the VCF mainline without correction. Its `reportability.py` and `VCF_INTAKE_COMPATIBILITY.md` changes make CNV/SV/mitochondrial/repeat artifacts unconditional reportability blockers, directly contradicting the merged PR #251 and the frozen first-product contract that signs out the supported SNV/INDEL result while clearly disclosing unsupported classes. Its upload-idempotency changes overlap the already merged PR #246. The PR also contains useful but unmerged VCF work: extra GRCh37/GRCh38 ClinVar reference known-answer cases and a real Celery prefork worker-loss test. The latter invokes raw `bcftools norm` directly rather than the production normalization wrapper and does not verify the full CSI/index/source-lineage contract; it should be split and strengthened before adoption. The separate SQLite post-commit replay test is complementary but overlaps existing PR #238 coverage.

- PR #223 and PR #231 are closed as superseded. PR #232 and #233 remain the merged genotype-provenance and VCFv4.5 Number=M implementations; #234 and #252 add sample-specific reference-block validation and routing.
- PR #224 is this audit document; this revision updates its evidence through main commit `dea24dbe`.
- PR #221 concerns PP3/BP4 predictor-calibration provenance and is scientifically adjacent, but is not a VCF parser implementation.
- PR #220 defines the broader laboratory workflow and release gates. It is requirements/architecture documentation, not proof that every stage is implemented or qualified.
- Branch search is paginated and historical branches may remain. This audit does not claim every branch or historical PR has been reconciled. Branch names are not evidence of implementation; compare commit ancestry, inspect diffs, and run relevant tests before recovering work.

## Verified implementation observations

### Current strengths

1. Strict VCF validation checks the declared version, header/record structure, ordering, genotype allele indices, and implemented version-specific local-allele rules.
2. Multisample input requires explicit sample selection for patient-level interpretation. Sites-only files remain site-level artifacts and must not become patient-specific genotype evidence.
3. Routing separates or manifests reference-only, telomere, GVCF, symbolic/breakend, spanning-deletion, and unsupported records rather than silently treating them as ordinary SNVs/INDELs.
4. Reference-aware normalization uses a pinned BCFtools executable, checks REF against the selected FASTA, splits multiallelic records, records source mapping, sorts, creates CSI, stages outputs before publication, and attempts rollback if publishing the VCF/index pair fails.
5. Source-record routing embeds a source record index, source-record SHA-256, raw ALT count, and routed-to-raw ALT index mapping.
6. The normalization path captures `SIRALOOM_SOURCE_GT` and `SIRALOOM_SOURCE_ALT_COUNT` on the routed sequence input after GVCF wildcard trimming and before per-ALT splitting. `SIRALOOM_ORIG` maps normalized children to routed source records/ALT indexes; `SIRALOOM_SOURCE` maps those routed ALT indexes back to the immutable uploaded record.
7. The genotype parser preserves source GT separately from normalized biallelic GT and records reference, selected-ALT, other-ALT, and missing dosages. A non-selected ALT is never rewritten as reference. If another ALT is present, a conventional biallelic projected GT is withheld.
8. Candidate iteration excludes an ALT as a known non-carrier only when selected-ALT dosage is zero and no allele is missing. Partial calls, no-calls, invalid mappings, and source/normalized ploidy mismatches remain unresolved.
9. Normalization artifact identity/version is 6.0 and partition metadata schema remains 4. Version 6.0 separates the source-only VCFv4.5 Number=M normalization policy from earlier normalized artifacts and prevents silent reuse of version 5.0 output.
10. VCFv4.5 base-modification fields are validated using sample GT and source allele sequences, including reserved aliases without explicit FORMAT declarations. The immutable source VCF remains authoritative for those values; they are not propagated into the normalized per-ALT small-variant artifact because the pinned splitter does not safely project their cardinality.
11. Existing tests cover left alignment, REF mismatch, tool-version pinning, failure-safe output publication, routing, multiallelic FORMAT cardinality, per-ALT genotype projection, missing/partial calls, leading phase indicators, source lineage, ploidy mismatch, VCFv4.5 Number=M cardinality, and source-only normalization behavior.
12. VCFv4.5 sample-specific reference blocks now validate reserved FORMAT/LEN, sample-specific block spans, LAA requirements and END consistency. The router tracks active block coverage per sample and permits a missing GT at a mixed variant site only when the sample is covered by a preceding validated block; it preserves that GT as missing. Unexplained missing GTs remain unresolved.
13. The lab scale benchmark now exercises validation, reference checks, routing, normalization, CSI/index and source-child reconciliation, and selected-sample iteration. It records per-stage timings/throughput, Python and child-process CPU/RSS, input/reference/output hashes, and counts without persisting sample identifiers in the report. A real pinned-BCFtools synthetic integration test validates the harness mechanics; representative WES/WGS lab runs remain outstanding.

## Remaining implementation and qualification gaps

1. **VCF feature conformance:** Build a positive/negative corpus for VCFv4.0–4.5. Cover version-specific GT syntax, INFO/FORMAT Number and Type cardinalities, escaping, missing values, symbolic records, local-allele fields, compression, malformed headers, and caller-specific extensions. Separate parser recognition from features that downstream stages can safely interpret.
2. **BCF input boundary:** BCF is not an advertised input format in the current VCF product scope. This is a deliberate format boundary, not an unfinished VCF parser feature. Do not silently treat BCF as text VCF; add a separate governed adapter only after an explicit product/architecture decision.
3. **gVCF analytical scope and interval/index qualification:** VCFv4.5 `FORMAT/LEN`, per-sample `<*>` reference-block lengths, computed `INFO/END`, and END consistency are now implemented and validated (PR #234). PR #252 also makes mixed-site routing aware of which samples are covered by preceding validated blocks. These controls preserve correct missing-genotype semantics; they do not interpret reference-confidence blocks as patient-level reference evidence, perform joint genotyping, or establish gVCF analytical support. Remaining work is real CSI/index-query boundary fixtures for sample-specific LEN/END spans and a separate, explicitly governed reference-confidence workflow if that becomes product scope.
4. **End-to-end record accounting:** Extend reconciliation across immutable upload, routed sequence stream, GVCF/structural/review streams, normalized children, and exclusion manifest. Include mixed records, repeated/duplicate alleles, empty routed streams, and all disposition counts. Keep source-record counts distinct from ALT-child counts.
5. **Source-to-child semantics:** Add known-answer tests for duplicate ALT strings, multiple concrete ALTs mixed with wildcard alleles, normalization-induced coordinate changes, INFO/FORMAT Number=A/R/G fields, phase/ploidy edge cases, and every supported caller representation. Verify every normalized child maps exactly once to the correct raw source record and ALT index.
6. **Reference package qualification:** Prove FASTA/FAI/GZI consistency, trusted assembly accession/build identity, contig dictionary/alias policy, boundary behavior, and known-answer SNV/indel REF checks for GRCh37 and GRCh38. Artifact hashes are necessary but not sufficient.
7. **Index qualification:** Add real indexed-query fixtures for missing, stale, corrupt, mismatched, empty, and partially written CSI indexes, including records at contig boundaries and duplicate positions. Confirm the indexed-query digest comparison behaves correctly with actual pinned BCFtools 1.24, not only mocked subprocesses.
8. **Failure, replay, and scale:** Upload retryability (PR #246), scratch-volume staging (PR #250), and normalization replay after durable commit (PR #238) now have implementation/test coverage at defined boundaries. Remaining qualification includes truncated/corrupt BGZF, parser/tool timeout, disk-full, worker loss at every VCF stage, concurrent normalization/retries, large WES/WGS files, and interruption across artifact publication and downstream handoff. Verify retries do not advertise mismatched artifact pairs or duplicate durable outputs.
9. **Sample identity propagation:** Prove the explicitly mapped sample identity remains fixed through routing, normalization, annotation, population/evidence, inheritance/segregation, review, and report rendering. A correct parser alone does not establish downstream sample isolation.
10. **Laboratory release governance:** Persist caller/version/build, assay and specimen mapping, exact tool/resource versions, fixture corpus, acceptance thresholds, qualification evidence, and laboratory authorization. Software CI is not analytical validation of an assay or clinical service.

## Next implementation order

1. Complete the positive/negative VCFv4.0–4.5 feature corpus and caller/version/build compatibility matrix; distinguish parser recognition from validated caller profiles.
2. Split/review the useful VCF-specific tests from PR #245 only after removing its conflicting reportability changes, deduplicating upload idempotency, and upgrading the worker-loss test to exercise the production normalization/CSI/source-lineage path.
2. Add real BCFtools/CSI indexed-query fixtures for sample-specific VCFv4.5 LEN/END spans, stale/corrupt/mismatched indexes, contig boundaries and duplicate positions.
3. Complete end-to-end source/upload/routed/normalized/exclusion accounting, including duplicate ALT strings, mixed record classes, empty streams and per-ALT genotype edge cases.
4. Complete FASTA/FAI/GZI consistency checks and trusted GRCh37/GRCh38 known-answer reference qualification.
5. Verify genotype provenance and sample identity across all downstream consumers, especially inheritance/segregation, review and report generation.
6. Execute the GIAB HG001/GRCh38 known-answer benchmark with independently pinned input/truth/confident-region/reference assets.
7. Execute `scripts/validation/run_vcf_scale_benchmark.py` against representative WES and WGS inputs per intended caller/version/build on the target worker profile; measure CPU, memory, scratch/persistent storage, throughput and concurrency against preapproved laboratory thresholds.
8. Complete failure/replay qualification across upload, validation, normalization, publication and downstream handoff, including disk-full, process loss and concurrent retries.
9. Run full repository CI and publish evidence. Keep software verification distinct from laboratory assay validation, clinical validity, and authorized clinical sign-out. BCF is not an advertised input format in the current VCF product scope; do not add it without a separate product/architecture decision.

## Governance observations

- At the time of this audit, the GitHub `main` branch was not protected and no repository ruleset was returned. Required backend, PostgreSQL integration, and frontend checks are therefore not enforced by branch protection. Establish release-branch protection and required checks before production release.
- PR #233 and later PR previews encountered the Vercel account's daily deployment quota. PR #252's GitHub Actions checks and main-branch workflow for commit `40be1c3` passed backend, PostgreSQL/Celery integration, frontend, and production container checks. PR #253's full PR CI passed before merge; its fresh main-branch workflow for commit `dea24dbe` is pending at this audit snapshot. The Vercel preview/production deployment is not established by those checks; re-attempt only after the quota resets and verify the actual deployed commit.
- The prior audit found no main-branch protection/ruleset response. Recheck branch protection and required checks before a controlled laboratory release.

## Non-claims

This audit does not certify clinical validity, analytical validity, an upstream assay, or production laboratory qualification. A valid VCF is not proof of assay validity, and a missing/partial genotype is not evidence of a reference genotype or negative clinical result. Test results are reported only when observed in GitHub Actions. Local WSL execution was not available to this audit process.
