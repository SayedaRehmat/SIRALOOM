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


### Table-structure inventory

A source-structure index now records **195 VCF-scoped LaTeX table environments**
across VCFv4.1–4.5 (35, 35, 40, 41, and 44 respectively), with 939
row-terminator lines as navigation aids. It also records 123 footnote-marker
lines and 84 enumerated-list starts. These counts are structural discovery
metrics, not counts of normative requirements or semantically reviewed rows.
The existing 61 table-caption entries therefore cannot be treated as a complete
inventory of all table environments. See
`table-structure-inventory.v1.json`.

No explicit grammar/BNF environment or `::=` production marker was found by
the narrow marker scan. This is not evidence that grammar constraints are
absent; manual syntax/grammar review remains open. Table-row semantics,
enumerated values, definitions, footnotes, and cross-references have not yet
been decomposed into requirements.


### Initial version-delta comparison

`version-delta-review.v1.json` records a limited comparison of the reviewed
fileformat, encoding, and line-structure passages across VCFv4.1–4.5. It
identifies the terminology shift from "fileformat field" (4.1–4.2) to
"fileformat line" (4.3–4.5), explicit LF/CRLF reader support and character
encoding constraints in 4.3–4.5, and the later explicit trailing-tab and
final-data-line terminator constraints. Tab-delimited header/data fields and
unique sample identifiers are present in the reviewed passages across 4.1–4.5.

This is a scoped delta analysis only. "Not identified" in a reviewed passage
does not prove absence from the entire earlier specification. VCFv4.0 remains
excluded from the comparison until its exact historical source bytes are
captured and pinned. No full version-by-version semantic delta analysis is
claimed.


## 10. Modal-candidate line-context disposition and core field-row review

A first-pass primary disposition has now been recorded for **all 510 modal-language candidate lines** from the pinned VCFv4.1–4.5 sources:

| Version | Candidate lines | Immediate source-context dispositions |
|---|---:|---:|
| VCFv4.1 | 38 | 38 |
| VCFv4.2 | 44 | 44 |
| VCFv4.3 | 82 | 82 |
| VCFv4.4 | 161 | 161 |
| VCFv4.5 | 185 | 185 |
| **Total** | **510** | **510** |

The per-version review artifacts retain the exact candidate line, adjacent source lines, source locator, primary disposition, and reviewer note. Dispositions distinguish mandatory constraints, recommendations, permissions, informative examples, mixed clauses, backward-compatibility rules, and unresolved scope. VCFv4.4 and VCFv4.5 are split into core/header/genotype and later SV/representation batches.

**This is not a claim that all 510 candidates have received complete expanded semantic review or have become atomic requirements.** Immediate-neighbour review identifies what kind of statement a candidate contains. Compound clauses still require decomposition; references to tables, footnotes, grammar, and other sections must be expanded and adjudicated before a requirement can enter the approved ledger.

See `candidate-context-review-index.v1.json` for the per-version artifact index and explicit limitations.

### Core fixed-record and reserved-key review

The fixed-record source review captures VCFv4.1–4.5 passages for CHROM, POS, ID, REF, ALT, QUAL, FILTER, INFO and conditional FORMAT/sample columns. It records 28 proposed source-derived obligations and the version deltas, including:
- VCFv4.1–4.2 QUAL labelled Numeric versus Float in VCFv4.3–4.5;
- the VCFv4.2 introduction of the spanning-deletion `*` ALT allele;
- explicit ALT grammar and INFO key regular-expression constraints in VCFv4.3–4.5;
- VCFv4.4–4.5 unspecified allele `<*>` and its padding exception;
- VCFv4.3–4.5 explicit IUPAC reference ambiguity reduction rule.

### Reserved INFO/FORMAT entries

The core reserved-key inventory now contains **223 source entries** across the five pinned versions:
- VCFv4.1: 18 INFO + 13 FORMAT prose entries;
- VCFv4.2: 18 INFO + 13 FORMAT prose entries;
- VCFv4.3: 21 INFO + 16 FORMAT table rows;
- VCFv4.4: 21 INFO + 19 FORMAT table rows;
- VCFv4.5: 21 INFO + 63 FORMAT table rows.

The 4.1–4.2 lists are prose enumerations and do not explicitly provide Number/Type columns; those values have not been backfilled from later tables. The 4.3–4.5 rows preserve their exact Number, Type and Description. All 223 entries have an initial primary semantic classification, but detailed field-specific prose, cross-references, genotype ordering, local-allele and base-modification semantics still need atomization and independent review.

Important version deltas retained:
- VCFv4.4 adds PSL, PSO and PSQ phase-set-list FORMAT fields.
- VCFv4.5 adds LEN, local-allele FORMAT fields, and base-modification key patterns and aliases.
- VCFv4.5 changes INFO END to a deprecated backward-compatibility field; it is not interchangeable with FORMAT LEN.
- Reserved-key presence is not universally mandatory. A row's existence defines a reserved field, not an unconditional requirement that every record or sample carry it.

See `core-info-format-row-inventory.v1.json`, `format-reserved-row-source-review.v1.json`, and `core-info-format-version-delta.v1.json`.

### Updated evidence counters

| Evidence class | Current value | Interpretation |
|---|---:|---|
| Modal candidate lines with initial immediate-context disposition | 510/510 | Primary review only; expanded semantic review remains |
| Reserved INFO/FORMAT entries indexed and initially classified | 223 | Not mandatory requirements and not fully atomized |
| Fixed-record source-derived candidate obligations | 28 | Proposed, not independently approved |
| Seed atomic ledger records | 15 | In review |
| Independently second-person reviewed requirements | 0 | Not started |
| Production-code mappings | 0 | Not started |
| Executed clause-specific tests | 0 | Not started |
| Laboratory-qualified versions | 0 | Not qualified |
| VCFv4.0 historical source bytes with SHA-256 | 0 | Capture and source adjudication outstanding |

### Remaining source-review work

1. Expand every candidate line to the full clause and all relevant definitions, grammar, tables, examples, footnotes and cross-references; do not treat immediate-neighbour disposition as semantic completion.
2. Atomize all compound clauses and table definitions, preserving normative force and per-version applicability.
3. Review all non-modal constraints and the remaining table environments; the 223 reserved INFO/FORMAT entries are only one subset of the 195 indexed table environments.
4. Complete semantic delta analysis for all VCFv4.1–4.5 clauses and add VCFv4.0 only after immutable historical source capture.
5. Obtain independent second-person review before any requirement is marked independently reviewed.
6. Only then map to production code and execute version-specific conformance tests.


## FORMAT/GENOTYPE semantic expansion — 2026-11-05

A direct source-context pass was performed against the pinned HTS-specs TeX files for VCFv4.1–4.5. This expanded the initial FORMAT candidate set from 18 to 61 proposed candidates.

Coverage added:
- General genotype likelihood ordering for arbitrary ploidy and alternate-allele count, including inclusive loop boundaries, recursive enumeration, diploid triangular indexing, and the VCFv4.5 inverse-index expression.
- The VCFv4.3 to VCFv4.4 change from genotype-level separators to allele-level phasing indicators, including the implicit first-indicator rule and partial phasing.
- PSL, PSO and PSQ definitions and constraints: list cardinality, unphased allele placeholders, cross-chromosome phase-set identity, PS/PSL mutual exclusion and non-interoperability, derivative-chromosome traversal ordinals, paired-breakend consistency and quality missingness.
- VCFv4.5 local-allele Number LA/LR/LG/P/M semantics, LAA index/order behavior, conditional LAA requirement, local/global field equivalence, and the BCF empty-vector/MISSING caveat.
- VCFv4.5 base-modification FORMAT semantics: M/DPM/ADM key families, aliases, ChEBI-related key pattern reservation, U/T synonymy, GT dependency, genotype/phasing-dependent value order, strand handling, missing/symbolic allele handling and unstranded conventions.

The 61 candidate records are proposals, not 61 approved requirements. One broad LAA candidate (FMT-GT-017) is explicitly retained as a split parent after the more precise source condition was captured in FMT-GT-039. Sixty candidate records were reconciled into the atomic ledger as VCF-REQ-000016 through VCF-REQ-000075. All 75 ledger records remain IN_REVIEW. VCFv4.0 applicability is marked SOURCE_NOT_PINNED for these new records; no VCFv4.0 claim is inferred.

Version-delta review now includes five additional genotype/FORMAT topics: genotype ordering, GT phasing representation, phase-set-list model, local-allele semantics, and base-modification semantics. The delta registry contains 11 row-level semantic delta topics in total.

### Explicit evidence limits after this pass

- Primary source context review is not independent second-person review.
- Candidate-to-ledger reconciliation does not mean approval; the 60 new ledger records remain IN_REVIEW.
- No implementation mapping, executable clause tests, differential parser tests or laboratory qualification was performed.
- The reserved INFO/FORMAT row inventory remains broader than the current atomic requirement set; detailed semantics for many individual reserved rows still require decomposition.
- VCFv4.0 historical source bytes have not yet been authoritatively captured and SHA-256 pinned. The previously recorded International Genome Sample Resource (IGSR) VCF 4.0 page is a discovery/reference page, not accepted as the normative specification source. Producer conventions and examples from 1000 Genomes/IGSR must remain a separate source class and must not be substituted for the normative VCF 4.0 specification.


## Current evidence snapshot after FORMAT expansion and VCFv4.0 provenance assessment

| Evidence item | Current state |
|---|---:|
| Initial modal-language candidate lines, VCFv4.1–4.5 | 510; initial context dispositions 510/510 |
| Reserved INFO/FORMAT entries inventoried | 223 |
| FORMAT/GENOTYPE atomic candidate records | 61 |
| FORMAT/GENOTYPE candidate records reconciled into ledger | 60 |
| Split-parent candidates retained outside ledger | 1 (FMT-GT-017) |
| Atomic ledger records | 75 |
| Ledger records still IN_REVIEW | 75/75 |
| Independently second-person reviewed records | 0 |
| Production implementation mappings | 0 |
| Executed clause-specific tests | 0 |
| Laboratory-qualified VCF versions | 0 |
| VCFv4.0 original source bytes captured and SHA-256 pinned | No |

The full 40-character HTS specification commit is `510c107ba89aa13113818c9e4fa3071283cb7f7b`. All VCFv4.1–4.5 source references in the reviewed artifact set and atomic ledger have been reconciled to this exact revision and their per-file blob identities remain recorded.

The VCFv4.0 source investigation has identified the IGSR historical core page and a separate IGSR/1000 Genomes structural-variation conventions page. The core page is currently a **discovery/reference candidate only**; it has not been accepted as the authoritative normative source and its raw immutable bytes have not been captured. The structural-variation page is classified separately as a producer-convention/extension source. VCFv4.0 applicability in the atomic ledger remains `SOURCE_NOT_PINNED`.

A bounded independent-review package has been prepared at `INDEPENDENT_REVIEW_PACKAGE.v1.md`. It is ready for reviewer appointment and record-by-record dispositions for the current 75-record tranche. It does not claim that review has occurred or that the 75 records exhaust the VCF specification.

### Immediate gates

1. Acquire and provenance-qualify the original/authoritative VCFv4.0 historical artifact, preserve exact bytes, and compute SHA-256; compare it with the IGSR page.
2. Continue semantic review and atomic decomposition for remaining INFO/FORMAT rows, SV/breakend, gVCF, grammar, definitions, footnotes, examples and cross-references.
3. Reconcile additional version-specific requirements into the ledger without upgrading proposed records to approved status.
4. Obtain independent review of the bounded 75-record tranche and continue source review beyond it.
5. Only after requirement coverage and independent review, begin implementation mapping and clause-specific tests.
