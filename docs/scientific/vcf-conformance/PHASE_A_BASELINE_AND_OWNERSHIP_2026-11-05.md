# SIRALOOM VCF conformance — Phase A baseline and ownership boundary

**Audit date:** 2026-11-05  
**Repository baseline:** `f3f5ea122aa81fe43d5c8b8981f5d57decddacc9`  
**Work branch:** `research/vcf-conformance-phase-a-20261105`  
**Scope:** VCF specification research and clause-level conformance evidence. No toolchain or normalization implementation changes.

## Executive decision

The source and repository audit confirms that this workstream should **reuse** the existing VCF specification inventory and candidate extractor, not create a second parser, feature registry, or normative-language extractor.

The current state is:

- VCFv4.1–4.5 have an exact pinned HTS-specs commit and their five source blob identities were checked against GitHub's file-fetch metadata.
- VCFv4.0 has an identified historical core source and a separate 1000 Genomes structural-variation convention source, but the exact historical response bytes and SHA-256 values have not yet been archived and reviewed.
- PR #282 already contains a 510-line candidate inventory for VCFv4.1–4.5, a section/table inventory, a first-pass VCFv4.0 clause catalog, a version traceability matrix, and CI bootstrap acquisition steps. These are inputs to the next stage, not completed conformance.
- The 510 candidates are not 510 reviewed atomic requirements. Tables, grammar, definitions, footnotes, examples, and cross-references also require systematic review.
- No clinical laboratory qualification or full VCF-version conformance is established by this audit.

## 1. Repository and branch inspection

The uploaded Git bundle was verified and imported into an isolated local repository. No original user worktree was changed.

| Reference | Commit | Observation |
|---|---|---|
| `main` | `f3f5ea122aa81fe43d5c8b8981f5d57decddacc9` | Baseline commit dated 2026-11-05 12:03 +0500 |
| PR #282 | `1b5bee3f8ae40843d59dbd15142cf906e574ddf0` | Specification/capability governance foundation; 522 commits ahead and 7 behind main from merge base `64d56635...` in the supplied bundle |
| PR #292 | `b0c13fe796615eeada6c4eaecbd8d36b5b3b5459` | Four-file feature registry refinement stacked on #282 |
| PR #276 | `d76c055da32a680c490d276039a2be4f53585a91` | Version-gated test corpus |
| PR #275 | `b4ced6abe0b9611a4a8d600b750b3fe5a2b75d09` | Documentation/audit branch |

The repository's existing mainline audit `docs/validation/VCF_STANDARDS_TRACEABILITY_2026-11-01.md` explicitly records partial software conformance and states that laboratory qualification is not established.

## 2. Explicit ownership boundary

The following work is protected because it belongs to the other AI's active BCFtools/toolchain workstream. This branch must not modify, rebase, cherry-pick over, or merge those branches.

| Protected branch | Head in supplied bundle | Changed-file scope relative to bundled main |
|---|---|---|
| `feat/bcftools-toolchain-profiles-20261105` | `a6cc79d2eec2fad797cf2664f95159d1c53334d0` | 1 file: BCFtools build-lock workflow |
| `feat/bcftools-1.24.1-profile-and-analysis-routing` | `df91a33ed9cc5282242b9c2b9aa920d403a97f67` | 34 files, including CI, toolchain profiles, analysis routing, workflow, ingestion, and tests |
| `fix/vcf-toolchain-htslib-security-1-24-1` | `c44664bca7bb78ad2a6667a6a7f46d589c78b9e7` | 45 files, including CI, ingestion, reference/toolchain identity, VCF tools/validation, workflow, Docker, lockfiles, and tests |

Protected paths include (not exhaustive):

- `.github/workflows/**`
- `backend/app/domain/ingestion.py`
- `backend/app/domain/toolchain_profiles.py`
- `backend/app/domain/vcf_tools.py`
- `backend/app/domain/vcf_validation.py`
- `backend/app/workflows/variant.py`
- `backend/app/api/v1/analyses.py`
- `backend/app/application/analysis.py`
- `backend/app/domain/reanalysis.py`
- `backend/app/infrastructure/queue/celery_app.py`
- `docker/**`, `configs/bioinformatics/**`, `uv.lock`, and toolchain build scripts
- `tests/test_ingestion.py`, `tests/test_vcf_tools.py`, `tests/test_vcf_validation.py`, `tests/test_unsupported_vcf_worker_routing.py`, and toolchain/concordance tests
- `docs/VCF_STAGE1_LAB_QUALIFICATION_MATRIX.md`

PR #282 and #292 are also treated as pre-existing work to reuse and review, not as permission to duplicate their implementation. This new branch is isolated from those branches and contains only new files under `docs/scientific/vcf-conformance/`.

## 3. Specification source findings

### VCFv4.1–4.5

The GA4GH Large Scale Genomics HTS specifications repository lists VCFv4.1 through VCFv4.5. Its index identifies VCFv4.5 as the canonical VCF specification and the earlier documents as predecessors.

Pinned source revision:

`samtools/hts-specs@510c107ba89aa13113818c9e4fa3071283cb7f7b`

The following Git blob SHAs were returned by GitHub for the exact commit and match the values already recorded in PR #282's normative extractor:

| Version | Source file | Git blob SHA-1 |
|---|---|---|
| 4.1 | `VCFv4.1.tex` | `420cee83a66259600a70de36721763cc374df1e3` |
| 4.2 | `VCFv4.2.tex` | `70e595cdad351b3fb12e121850d7e6c8c5f67c88` |
| 4.3 | `VCFv4.3.tex` | `01671b89e21fc1bca414b639a4ea483194f127a9` |
| 4.4 | `VCFv4.4.tex` | `31cb66283ea40c3df51e488c5fffe826fd8dedaf` |
| 4.5 | `VCFv4.5.tex` | `307950e7eeafc33d524969ff906343f756adb7d7` |

These are Git blob SHA-1 identities, not SHA-256 digests of a locally archived source file. The source text should be retrieved by immutable commit URL and checked against these blob identities by the existing CI acquisition/extraction workflow. The audit did not independently retrieve a commit-signature verification field; PR #282's inventory records the commit as GitHub-signature-verified.

### VCFv4.0

The maintained HTS index does not list a VCFv4.0 document. The historical 1000 Genomes / International Genome Sample Resource page is therefore a **historical compatibility source**, not a current GA4GH-maintained versioned specification.

Keep two source records separate:

1. Core VCFv4.0 historical format description: `https://www.internationalgenome.org/wiki/Analysis/vcf4.0/`
2. 1000 Genomes VCFv4.0 structural-variation conventions: `https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/`

The second source describes 1000 Genomes project conventions/extensions. It must not be silently treated as universal VCFv4.0 core requirements.

PR #282 already adds CI capture of exact HTML response bytes, response headers, final URL, retrieval time, byte length, and SHA-256, plus a historical cohort VCF bootstrap runner. The recorded status remains `SOURCE_IDENTIFIED_RAW_BYTES_NOT_CAPTURED`; the workflow steps use non-blocking bootstrap behavior and the captured artifacts must be reviewed before a digest is pinned. No source digest or cohort qualification result is asserted here.

## 4. Existing implementation/research assets to reuse

The supplied PR #282 branch already contains:

- `backend/app/domain/vcf_spec_registry.py`
- `backend/app/domain/vcf_feature_compatibility.py`
- `backend/app/domain/vcf_normative_inventory.py`
- `backend/app/domain/vcf_conformance.py`
- `backend/app/domain/vcf_conformance_cases.json`
- `docs/implementation/VCF_NORMATIVE_SECTION_INVENTORY.json`
- `docs/implementation/VCF_NORMATIVE_CANDIDATE_EXTRACTION.md`
- `docs/implementation/VCF_VERSION_REQUIREMENT_TRACEABILITY_MATRIX.md`
- `docs/implementation/VCF40_HISTORICAL_SOURCE_AND_CLAUSE_CATALOG.md`
- `docs/qualification/vcf40-source-acquisition-status.json`
- `tests/test_vcf_normative_inventory.py`

The extractor reports 510 candidate lines across VCFv4.1–4.5 (38, 44, 82, 161, and 185 respectively). Its own documentation correctly labels them `EXTRACTED_UNREVIEWED`, `UNREVIEWED`, and `UNMAPPED`.

The existing traceability matrix also includes section-level coverage and a first-pass VCFv4.0 catalog. Its documented fixture-to-clause links cover 31 of 33 first-pass core catalog entries; that is not a complete VCFv4.0 clause inventory and fixture linkage is not execution evidence.

## 5. Execution check and limitations

A focused test attempt was made on the isolated PR #282 worktree:

`python -m pytest -q tests/test_vcf_normative_inventory.py`

Pytest did not reach test collection because the environment lacks the `celery` dependency imported by `tests/conftest.py`. This is an environment blocker, not a test failure and not a passing result. No repository code was changed to work around it.

No merge, rebase, push, CI edit, toolchain edit, BCFtools/HTSlib edit, parser edit, or normalization edit was performed.

## 6. Next implementation stage

The next deliverable is a **reviewed atomic requirement ledger**, not a second extractor or feature matrix.

### Ledger record fields

Each atomic requirement should carry:

- stable requirement ID (independent of version numbering);
- requirement domain and source class;
- exact source version, immutable revision, file/blob identity, section/table/footnote/grammar locator, and source excerpt hash;
- normative force (`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, `MAY`, or descriptive/non-normative);
- actor, precondition, required/prohibited/allowed behavior, exceptions, and observable pass condition;
- per-version applicability (`APPLICABLE`, `NOT_APPLICABLE`, `CHANGED`, `UNRESOLVED`);
- implementation disposition and exact code symbol (filled only after auditing the selected baseline);
- exact positive, negative, and boundary test IDs, or a documented reason why a test class is not applicable;
- test execution artifact, tool versions, input/output hashes, and result;
- independent reviewer, review date, decision, and unresolved issue reference.

### Clause discovery must go beyond modal-word extraction

For each version, review all relevant source structures:

1. normative modal statements;
2. grammar productions and lexical constraints;
3. field-definition tables and cardinality/type tables;
4. reserved INFO/FORMAT keys and their value semantics;
5. cross-referenced definitions and footnotes;
6. normative constraints embedded in examples and explanatory sections;
7. version change notes, used as discovery aids but not substituted for the target version's own source text.

Every candidate must be classified as normative, informative, producer convention, external specification, or SIRALOOM policy. Do not promote examples or recommendations into MUST requirements.

### Work order

1. Finish and review the exact-byte VCFv4.0 source-capture artifact; pin the reviewed source revision and SHA-256. Keep core and 1000G SV conventions separate.
2. Reuse PR #282's 510 candidate lines and section inventory; add missed table/grammar/footnote/definition-derived requirements.
3. Decompose requirements into stable atomic records and add a per-version applicability/delta matrix.
4. Independently review the clause ledger before marking any requirement `REVIEWED`.
5. Audit the production code and tests against the ledger only after the other AI's protected implementation changes have stabilized or an exact commit handoff is supplied.
6. Generate one report per VCF version and a cross-version delta report.
7. Only then implement missing non-overlapping conformance components and add version-specific execution evidence.

## 7. Completion gates

- **Source complete:** all six version sources and any distinct producer-convention sources have immutable, reviewable provenance.
- **Clause complete:** all normative requirements are atomically decomposed, version-scoped, and independently reviewed.
- **Traceability complete:** every applicable requirement maps to code, tests, evidence, or an explicit blocked/unsupported disposition.
- **Conformance tested:** version-specific positive, negative, boundary, and independent interoperability tests have executed.
- **Laboratory qualified:** the laboratory's intended-use, assay/caller/build matrix and quality-system approval are separately complete.

A source pin, parser pass, candidate count, green CI run, or format conformance report alone cannot establish clinical assay validation or laboratory qualification.


## 8. Candidate intake and source-structure inventory (2026-11-05)

The existing PR #282 extractor was reused without copying or changing its implementation. The pinned VCFv4.1–4.5 TeX sources were fetched at the exact recorded commit and candidate extraction was reproduced using the same VCF section roots and modal-language matching boundaries.

The reproduced counts match the extractor's expected counts exactly:

| Version | Candidate lines |
|---|---:|
| VCFv4.1 | 38 |
| VCFv4.2 | 44 |
| VCFv4.3 | 82 |
| VCFv4.4 | 161 |
| VCFv4.5 | 185 |
| **Total** | **510** |

All 510 candidate IDs are unique. The full source-line text, line number, source version, section path, and matched modal terms are retained in `normative-candidate-intake.v1.json`. Each candidate remains `UNREVIEWED` and `NOT_ASSESSED` for atomicity. A source line may contain zero, one, or multiple obligations; it is not itself an atomic requirement.

The existing section inventory was also reused to create `source-structure-review-queue.v1.json`. It indexes **229 headings and 61 table captions** across VCFv4.1–4.5. These are discovery targets, not normative clause counts. The queue explicitly includes grammar productions, field-definition tables, reserved-key definitions, enumerated values, footnotes, cross-references and example constraints because modal-word extraction cannot discover all requirements.

The existing VCFv4.0 historical catalog contains **33 unique core catalog IDs**. Its 1000 Genomes SV conventions remain a separate source class. The 33 first-pass entries are not represented as a complete historical requirement inventory; the source-byte capture and SHA-256 remain outstanding.

### Current accounting after intake

| Evidence class | Count | Status |
|---|---:|---|
| VCFv4.1–4.5 modal-language candidate lines | 510 | Reproduced and indexed; unreviewed |
| VCFv4.1–4.5 source headings | 229 | Indexed for structural review |
| VCFv4.1–4.5 table captions | 61 | Indexed for structural review |
| VCFv4.0 first-pass unique core catalog entries | 33 | Existing partial catalog; source snapshot pending |
| Atomic requirement records in seed ledger | 5 | Initial records; in review |
| Independently reviewed atomic requirements | 0 | Not yet started |
| Requirements mapped to production code | 0 | Not audited |
| Requirements with executed clause-specific tests | 0 | Not executed |

No count above is a conformance percentage or a claim of source completeness. In particular, 510 candidate lines plus 229 headings and 61 table captions are not additive requirement counts.

### Next concrete work

1. Review each candidate line in source context and split compound statements into atomic obligations while preserving qualifiers and exceptions.
2. Review all 229 heading scopes and 61 table-caption scopes, then enumerate their actual rows, grammar productions, footnotes, definitions and cross-references from the pinned source.
3. Add source-derived atomic requirements to the ledger with stable IDs and per-version applicability; record informative, producer-specific and non-normative material separately.
4. Complete a per-version delta review before any requirement is marked reviewed.
5. Independently review the ledger; only then audit implementation and test evidence against a stable baseline.


## 9. Initial source-context review and non-modal discovery (2026-11-05)

The first source-context review has been recorded in
`source-context-review.v1.json`. It reads source passages with surrounding
section context, distinguishes producer obligations from reader obligations,
and decomposes compound statements into independently testable constraints.
It is explicitly a primary review; independent second review has not started.

The atomic ledger now contains **15 records**:
- 5 initial fileformat and line-ending seed records;
- 7 additional constraints for UTF-8 encoding, BOM exclusion, prohibited
  control characters, zero-length fields, trailing tabs on the header and
  data lines, and final data-line termination;
- 3 additional constraints for tab-delimited header fields, tab-delimited data
  fields, and unique sample identifiers.

The newly added constraints are source-mapped to VCFv4.1–4.5 where the exact
source statements were checked, or VCFv4.3–4.5 where the statements first
appear in the reviewed source passages. VCFv4.0 applicability and earlier
versions not yet checked remain explicitly unresolved; no inheritance from a
later version is assumed.

The review identified several requirements missed by the current modal-word
extractor:
- declarative format properties (UTF-8);
- negative formulations outside its matcher (zero-length fields "not allowed",
  sample identifiers "not allowed", and control characters "disallowed");
- declarative structural constraints (tab-delimited header and data lines).

See `nonmodal-requirement-discovery.v1.json`. These findings demonstrate why
the 510 modal-language candidates cannot serve as a complete requirements
inventory. The current discovery register is initial, not exhaustive.

### Current evidence counters

| Measure | Current value |
|---|---:|
| Modal-language candidate lines | 510 |
| Atomic ledger records | 15 |
| Independently reviewed requirements | 0 |
| Requirements mapped to production code | 0 |
| Requirements with executed clause-specific tests | 0 |
| Laboratory-qualified versions | 0 |

### Remaining work

1. Review all 510 candidate lines in source context, not only the initial
   fileformat/encoding/data-line passages.
2. Enumerate and inspect actual table rows, grammar productions, field
   definitions, enumerated values, footnotes, and cross-references; the existing
   heading and table-caption inventory is not a row-level requirement ledger.
3. Perform systematic per-version delta analysis, including changes in
   wording, scope, field semantics, constraints, and applicability.
4. Capture and hash immutable VCFv4.0 source bytes before claiming its source
   provenance is pinned.
5. Obtain independent second-person review of every proposed atomic
   requirement before marking it independently reviewed.
6. Only after review, map requirements to implementation and clause-specific
   positive/negative tests. No code mapping, test execution, or conformance
   qualification is claimed by this phase.
