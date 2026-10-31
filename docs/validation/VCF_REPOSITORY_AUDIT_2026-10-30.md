# SIRALOOM VCF Stage Repository Audit — 2026-10-31

## Scope and evidence boundary

This document records a read-only review of the current GitHub implementation, relevant pull requests, VCF parsing/normalization code, regression tests, and the VCF intake contract. It is a repository and software-correctness audit, not laboratory assay qualification. No local WSL execution is claimed.

Repository: `SayedaRehmat/SIRALOOM`  
Audited main commit: `f44af5816d823859bc4400d18186c8e14ad24e27`  
Audit date: 2026-10-31

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
- PR #223 and PR #231 are closed as superseded. PR #232 and PR #233 are the current merged mainline implementations for genotype provenance and VCFv4.5 Number=M handling.
- PR #224 is this audit document.
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

## Remaining implementation and qualification gaps

1. **VCF feature conformance:** Build a positive/negative corpus for VCFv4.0–4.5. Cover version-specific GT syntax, INFO/FORMAT Number and Type cardinalities, escaping, missing values, symbolic records, local-allele fields, compression, malformed headers, and caller-specific extensions. Separate parser recognition from features that downstream stages can safely interpret.
2. **BCF input:** The current intake contract does not establish first-class binary BCF intake. Add an explicit BCF adapter/format contract only after defining sample selection, validation, provenance, and artifact behavior; do not silently treat BCF as text VCF.
3. **gVCF and VCFv4.5 reference-block semantics:** Current routing deliberately avoids treating reference-confidence blocks as ordinary variant calls. A separate reference-confidence/joint-genotyping workflow and its qualification are required before claiming gVCF analytical support. In addition, the current validator/tooling does not implement the VCFv4.5 reserved `FORMAT/LEN` field (Number=1, Integer), which records the length of a `<*>` reference block per sample. VCFv4.5 defines `INFO/END`, when present, as a computed maximum over the REF end, symbolic-SV `SVLEN` ends, and per-sample `FORMAT/LEN` ends; this value contributes to BCF `rlen` and indexed querying. Add strict LEN validation, sample-specific block-end calculation, END consistency checks, and real CSI boundary/query fixtures before claiming VCFv4.5 gVCF interval or index correctness. See the [VCFv4.5 specification: END semantics](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex#L2918-L2929) and [reserved FORMAT/LEN definition](https://github.com/samtools/hts-specs/blob/master/VCFv4.5.tex#L2994-L3005).
4. **End-to-end record accounting:** Extend reconciliation across immutable upload, routed sequence stream, GVCF/structural/review streams, normalized children, and exclusion manifest. Include mixed records, repeated/duplicate alleles, empty routed streams, and all disposition counts. Keep source-record counts distinct from ALT-child counts.
5. **Source-to-child semantics:** Add known-answer tests for duplicate ALT strings, multiple concrete ALTs mixed with wildcard alleles, normalization-induced coordinate changes, INFO/FORMAT Number=A/R/G fields, phase/ploidy edge cases, and every supported caller representation. Verify every normalized child maps exactly once to the correct raw source record and ALT index.
6. **Reference package qualification:** Prove FASTA/FAI/GZI consistency, trusted assembly accession/build identity, contig dictionary/alias policy, boundary behavior, and known-answer SNV/indel REF checks for GRCh37 and GRCh38. Artifact hashes are necessary but not sufficient.
7. **Index qualification:** Add real indexed-query fixtures for missing, stale, corrupt, mismatched, empty, and partially written CSI indexes, including records at contig boundaries and duplicate positions. Confirm the indexed-query digest comparison behaves correctly with actual pinned BCFtools 1.24, not only mocked subprocesses.
8. **Failure, replay, and scale:** Qualify truncated/corrupt BGZF, parser/tool timeout, disk-full, worker crash/replay, concurrent normalization, large WES/WGS files, and interruption between VCF/index publication. Verify retries do not advertise mismatched artifact pairs or duplicate durable outputs.
9. **Sample identity propagation:** Prove the explicitly mapped sample identity remains fixed through routing, normalization, annotation, population/evidence, inheritance/segregation, review, and report rendering. A correct parser alone does not establish downstream sample isolation.
10. **Laboratory release governance:** Persist caller/version/build, assay and specimen mapping, exact tool/resource versions, fixture corpus, acceptance thresholds, qualification evidence, and laboratory authorization. Software CI is not analytical validation of an assay or clinical service.

## Next implementation order

1. Implement and qualify VCFv4.5 `FORMAT/LEN` and computed `END` semantics for `<*>` reference blocks, including per-sample lengths and CSI indexed-query boundaries.
2. Complete the VCF version/feature conformance corpus for the versions and caller profiles SIRALOOM claims to recognize.
3. Complete end-to-end source/routed/normalized/exclusion accounting, including mixed record classes and duplicate ALT edge cases.
4. Add real BCFtools/CSI indexed-query fixtures for stale, corrupt, mismatched, and boundary indexes.
5. Complete FASTA/FAI/GZI consistency checks and trusted GRCh37/GRCh38 known-answer reference qualification.
6. Verify genotype provenance and sample identity across all downstream consumers, especially inheritance/segregation and report generation.
7. Qualify failure/replay and WES/WGS scale behavior with real pinned resources and storage.
8. Implement a governed BCF intake contract only if it is part of the approved product scope; keep gVCF reference-confidence processing as a separate workflow.
9. Run full repository CI and publish evidence. Keep software verification distinct from laboratory assay validation, clinical validity, and authorized clinical sign-out.

## Governance observations

- At the time of this audit, the GitHub `main` branch was not protected and no repository ruleset was returned. Required backend, PostgreSQL integration, and frontend checks are therefore not enforced by branch protection. Establish release-branch protection and required checks before production release.
- PR #233's Vercel preview deployment was rejected because the account's daily deployment quota had been exceeded. GitHub Actions backend, PostgreSQL integration, frontend, container, and Compose checks passed; however, no Vercel preview or production deployment is claimed. Re-attempt deployment only after the quota resets and verify the actual deployed commit.

## Non-claims

This audit does not certify clinical validity, analytical validity, an upstream assay, or production laboratory qualification. A valid VCF is not proof of assay validity, and a missing/partial genotype is not evidence of a reference genotype or negative clinical result. Test results are reported only when observed in GitHub Actions. Local WSL execution was not available to this audit process.
