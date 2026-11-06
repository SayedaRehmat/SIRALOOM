# VCF conformance Phase A — execution audit

**Audit date:** 2026-11-06  
**Repository:** `SayedaRehmat/SIRALOOM`  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Audited PR head:** `ca3ead97fae05b98b498fb152ec444716b5095fc`  
**PR:** [#293 — Research: establish VCF 4.0–4.5 conformance baseline and atomic ledger](https://github.com/SayedaRehmat/SIRALOOM/pull/293)  
**Status:** RESEARCH IN PROGRESS — NOT READY FOR INDEPENDENT SIGN-OFF OR LABORATORY QUALIFICATION

## 1. Purpose and audit boundary

This audit reconciles the recorded Phase A claims with the branch artifacts retrievable at the PR head. It is a research-workstream audit, not a declaration of VCF conformance. The PR remains a draft and its ownership boundary remains `docs/scientific/vcf-conformance/`; parser, validator, normalizer, BCFtools/HTSlib profiles, CI, Docker and production toolchain code are outside this research PR.

No branch rebase, merge, force-push, or production-code change was performed for this audit.

## 2. Source provenance: current state

### 2.1 VCFv4.1–4.5

The PR records that all five source files are pinned to HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`, with archived Git blob IDs matching the corresponding upstream blobs.

The source-hash repair sequence is present in the PR history:

- `bbc22b7b7d685989e6d8435767e6547d9f7eac9a` — exact-byte SHA-256 values applied to the source manifest, all 436 pinned-source ledger references and the consistency audit.
- `8536a136959632e38f9e56d419dacd32f743eefb` — readiness inventory rebound to the corrected ledger blob.
- `ca3ead97fae05b98b498fb152ec444716b5095fc` — corrected source digests propagated through seven dependent semantic/crosswalk artifacts (60 source-digest fields).

The PR's source-hash audit reports zero mismatches among the 436 VCFv4.1–4.5 references. The five recorded SHA-256 values are:

| Source | Bytes | SHA-256 |
|---|---:|---|
| VCFv4.1.tex | 95,857 | `7d29ef8f93745f246202da3e32107ea13b036bbefcb31f7971a3ce31f1045baa` |
| VCFv4.2.tex | 96,701 | `66dbd167e8fb309708e0956ffbb12808bd338a703fbf034d80d1ead56ae480cc` |
| VCFv4.3.tex | 119,335 | `332d8b910ac9952bfba04374118f8c4f318ea996d5017599e68f80379fd61cde` |
| VCFv4.4.tex | 149,282 | `4c88884cf6b016efcec691d5186432a2e0b679396204d14770e89839ef536e1a` |
| VCFv4.5.tex | 164,356 | `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5` |

**Audit qualification:** these are recorded as byte-verified in the committed source-hash audit and PR description. In this independent session, the five committed source files were fetched and their returned Git blob IDs matched the manifest. The complete atomic ledger content could not be retrieved through the GitHub file-content connector: it returned zero characters with a non-empty blob SHA (`ba7d1bb0544f5d1105a4bd62f757decae13caee8`). This is a retrieval/inspection limitation, not evidence that the file is empty. Consequently, the ledger's full internal reference set and all 436 reference-to-manifest comparisons were not independently recomputed in this audit. Re-run that verification from a local Git checkout or a byte-preserving Git blob export before treating the independent audit gate as closed.

### 2.2 VCFv4.0

VCFv4.0 remains the sole source-pinning blocker. The manifest and historical-source provenance artifact correctly retain the IGSR core page as a discovery candidate, not an accepted immutable normative source. No exact original source bytes or SHA-256 are recorded. The separate 1000 Genomes structural-variation page is explicitly a producer/project convention source and must not be merged into core VCFv4.0 requirements.

Additional provenance leads located during this audit:

- IGSR historical core page: https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- Alternate IGSR core route: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/vcf-variant-call-format-version-40/
- 1000 Genomes VCF 4.0 SV conventions: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/
- Contemporary 2011 VCF/VCFtools paper (historical corroboration, not a substitute for the specification): https://pmc.ncbi.nlm.nih.gov/articles/PMC3137218/
- 1000 Genomes announcement archive recording the July 2010 VCF 4.0 pilot release: https://www.internationalgenome.org/announcements/

These leads strengthen historical identity and dating context but do not supply an immutable, custody-qualified original specification artifact. Do not hash rendered web text and call it original source bytes. Continue to seek the original DokuWiki revision/export, contemporaneous archived copy, or another authoritative original artifact with a documented custody chain.

## 3. Requirement discovery and review state

The PR records 510 modal-language candidate lines across VCFv4.1–4.5:

| Version | Candidate lines | Primary immediate-context review |
|---|---:|---:|
| VCFv4.1 | 38 | 38/38 |
| VCFv4.2 | 44 | 44/44 |
| VCFv4.3 | 82 | 82/82 |
| VCFv4.4 core + SV | 161 | 161/161 |
| VCFv4.5 core + SV | 185 | 185/185 |
| **Total** | **510** | **510/510** |

These are first-pass context dispositions only. The per-version artifacts explicitly say atomic decomposition is pending. A candidate source line can contain zero, one or several obligations and is not itself an approved atomic requirement.

The source-structure inventory records 229 headings and 61 table captions. The separate table-structure inventory records 195 VCF-scoped LaTeX table environments across VCFv4.1–4.5, along with row-terminator, footnote-marker and enumerated-list discovery metrics. These are discovery indices, not requirement counts. Manual semantic review remains necessary.

The PR description reports 226 unique candidate records in the atomic ledger, all `IN_REVIEW`; 437 source references, of which 436 are pinned to VCFv4.1–4.5 and one is the unresolved VCFv4.0 candidate. The ledger content retrieval limitation described above prevents a fresh full-ledger parse in this audit.

## 4. VCFv4.5 table-review integrity finding

The VCFv4.5 table semantic queue contains 44 VCF-specific tables and reports:

- 44/44 author-context dispositions recorded;
- 109 atomic requirement IDs associated with the table-review work;
- 21 reserved INFO rows and 63 reserved FORMAT rows separately represented;
- zero independently reviewed tables/requirements.

However, all 44 table entries still contain the same three generic `open_questions`:

1. Which rows are normative definitions versus informative examples?
2. Which surrounding definitions, footnotes and cross-references alter interpretation?
3. Is the behavior version-specific or shared with earlier VCF releases?

That is 132 generic open-question entries. Some table-specific review notes already answer parts of these questions (for example, examples explicitly classified as informative, or reserved fields explicitly treated as optional definitions), while other tables still need explicit version-delta and cross-reference outcomes. The generic questions have not been converted into table-specific resolved findings or concrete outstanding issues.

**Required correction:** do not mark this review queue fully closed merely because every table has an author disposition. For each table, replace the boilerplate questions with:
- a source-backed normative/informative classification;
- the exact related definitions, footnotes and cross-references inspected;
- an explicit version-delta finding or `NOT_YET_ASSESSED` state;
- any remaining concrete question with a source locator and owner/status.

Do not clear a question without recording the evidence that resolves it. Keep example-only tables separate from normative requirements. In particular, inspect tables VCF5.2 and VCF5.6–VCF5.9 (which have no direct atomic requirement IDs) to ensure no normative rule was missed in their governing prose; do not create requirements from examples alone.

## 5. Cross-version semantic work still open

The following artifacts exist, but their own statuses retain semantic/atomic reconciliation as pending:

- VCFv4.1–4.4 reserved-row crosswalk: source-row inventory is complete, semantic and atomic reconciliation pending.
- VCFv4.1–4.4 genotype/SV/breakend crosswalk: expanded author source-context work exists, atomic reconciliation pending.
- VCFv4.1–4.4 per-version candidate-context reviews: primary context disposition is complete, atomic decomposition pending.
- VCFv4.5 reserved INFO/FORMAT semantic review: 84 rows reviewed in author context, independent review and additional atomic decomposition pending.
- Non-modal requirement discovery: explicitly initial and not exhaustive.
- Table-structure inventory: structural indexing complete; row semantics pending.

Version-specific distinctions must remain explicit. Do not backfill VCFv4.0 from later versions. Do not project VCFv4.5 semantics backward without source evidence. Keep BCF serialization, gVCF producer conventions and 1000 Genomes SV conventions as distinct scopes where applicable.

## 6. CI verification at the audited PR head

GitHub Actions run **42016140110** for commit `ca3ead97fae05b98b498fb152ec444716b5095fc` completed successfully.

Jobs:
- `backend` — success;
- `postgres-integration` — success;
- `frontend` — success.

This verifies repository CI for the audited commit. It does not verify normative completeness, independent standards review, VCF parser conformance or laboratory qualification.

## 7. Updated gate assessment

| Gate | Status | Evidence / blocker |
|---|---|---|
| VCFv4.1–4.5 source revision pinning | RECORDED COMPLETE | Pinned HTS-specs revision and matching archived Git blob IDs |
| VCFv4.1–4.5 source SHA-256 repair | RECORDED COMPLETE; INDEPENDENT RECHECK PENDING | Committed exact-byte audit; full ledger not retrievable through connector in this audit |
| VCFv4.0 source pinning | BLOCKED | No exact original/custody-qualified source bytes or SHA-256 |
| 510 candidate immediate-context dispositions | PRIMARY PASS COMPLETE | Explicitly not atomic decomposition |
| Whole-source semantic decomposition | INCOMPLETE | Definitions, grammar, table semantics, footnotes, examples and cross-references remain |
| VCFv4.5 table review | AUTHOR CONTEXT RECORDED; OPEN-QUESTION DEBT | 44 tables have dispositions but 132 generic questions remain |
| VCFv4.1–4.4 semantic/version reconciliation | INCOMPLETE | Crosswalks exist; row-level atomization and deltas remain |
| Atomic ledger independent approval | NOT STARTED | 0 independently approved records |
| Production implementation mapping | NOT STARTED | 0 mappings recorded |
| Clause-specific executable tests | NOT STARTED | 0 executed mappings recorded |
| Laboratory qualification | NOT STARTED | No VCF version qualified |

## 8. Next execution order

1. **Restore independent ledger inspectability.** Retrieve the exact branch blob through a local Git checkout or byte-preserving Git object export. Parse it, validate against the committed schema using a formal JSON Schema implementation, recompute source-reference counts and compare every reference digest with the manifest. Record the exact command, tool/version, input commit, output and result.
2. **Resolve VCFv4.5 table open-question debt.** Replace the 132 generic prompts with evidence-backed per-table dispositions and concrete unresolved issues. Review all 44 tables, not only the INFO/FORMAT tables.
3. **Continue atomic decomposition of the 510 source candidates.** Expand each candidate to full source context; split compound statements; preserve normative force, qualifiers, exceptions and actor (producer/reader); map each atomic requirement to precise line/range and source digest.
4. **Complete non-modal discovery.** Inspect all source sections, grammar/format productions, data types, metadata structures, enumerations, table rows, footnotes, examples and cross-references. Modal-word extraction must not define the universe of requirements.
5. **Complete VCFv4.1–4.4 row-by-row semantic review.** Reconcile reserved INFO/FORMAT semantics, genotype and ploidy rules, SV/breakend definitions, and all version deltas without assuming later-version inheritance.
6. **Acquire VCFv4.0 source bytes.** Obtain an original or custody-qualified historical artifact; record retrieval metadata, exact bytes and SHA-256; compare against IGSR historical text and contemporaneous sources; keep 1000 Genomes conventions separate.
7. **Reconcile the ledger and applicability matrix.** Assign stable IDs, split compound records, identify informative-only material, mark unknown applicability explicitly, and ensure each requirement's source, version applicability and review state are traceable.
8. **Freeze only after coverage and traceability audits pass.** Independent second-person review is a separate mandatory gate; author review must not self-approve.
9. **Only after independent requirements review, map implementation and design per-version positive, negative, boundary and interoperability tests.** Laboratory qualification remains a later, separate quality-system decision.

## 9. Non-claims

This audit does not claim that VCF 4.0–4.5 requirements are complete, that the 226-record ledger is exhaustive, that any requirement has independent approval, that production code implements all clauses, that clause-specific tests have passed, or that any VCF version is laboratory-qualified. PR #293 must remain draft and unmerged while these gates are open.


## 10. Subsequent execution work recorded on 2026-11-06

The following work was committed after the initial audit baseline:

- `vcf4.5-table-review-debt-adjudication.v1.json` — table-specific author dispositions for all 44 VCFv4.5 VCF-scope tables.
- `vcf4.5-table-semantic-review-queue.v1.json` — the three repeated generic questions were replaced by table-specific context-locator and version-delta work. The queue now has 88 baseline open questions plus one source-internal blocking ambiguity.
- `vcf4.1-4.5-version-delta-register.v1.json` — source-pinned transition register for VCFv4.1→4.2→4.3→4.4→4.5, with structural table metrics and direct VCFv4.4/4.5 source locators.
- `vcf4.1-4.5-reserved-row-version-crosswalk.v1.json` — all reserved INFO/FORMAT row inventories carried forward through VCFv4.5, retaining prose-only 4.1/4.2 representations without fabricated Number/Type values; mechanical row deltas are explicitly distinguished from semantic conclusions.
- `vcf4.5-info-format-row-semantic-review.v1.json` — 21 INFO and 63 FORMAT rows were structurally checked for unique IDs, source lines, author disposition and semantic notes.

### 10.1 VCFv4.5 table disposition counts

| Author disposition | Tables |
|---|---:|
| Normative table definitions | 3 |
| Mixed normative prose / informative matrix | 1 |
| Informative examples or illustrations | 40 |
| Total | 44 |

All 44 table records have source locators and author dispositions. All 44 still require exact locator-level surrounding-context reconciliation and version-delta assessment. Independent review remains 0/44. The 5.5 genotype-ordering matrix is treated as illustrative; its surrounding general-ploidy algorithm and footnote must be atomized independently. No normative requirement is inferred solely from example rows.

### 10.2 Reserved INFO/FORMAT row inventory

| Version | INFO rows | FORMAT rows | Source representation |
|---|---:|---:|---|
| VCFv4.1 | 18 | 13 | Prose enumerations |
| VCFv4.2 | 18 | 13 | Prose enumerations |
| VCFv4.3 | 21 | 16 | Number/Type tables |
| VCFv4.4 | 21 | 19 | Number/Type tables |
| VCFv4.5 | 21 | 63 | Number/Type tables |

Mechanical row findings:
- VCFv4.1→4.2 reserved row inventory unchanged; this does not erase the separately recorded ALT-star semantic delta.
- VCFv4.2→4.3 formalizes Number/Type attributes, adds INFO AD/ADF/ADR and FORMAT AD/ADF/ADR/PP, and removes GLE from the reserved FORMAT inventory. GLE's status requires contextual resolution; no silent compatibility decision is made.
- VCFv4.3→4.4 adds PSL/PSO/PSQ.
- VCFv4.4→4.5 adds 44 FORMAT rows and changes the END row description to deprecated/backward-compatibility status.

### 10.3 Newly confirmed upstream VCFv4.5 source ambiguity

A case-sensitive xanthosine alias inconsistency exists in the authoritative pinned VCFv4.5 source:

- Reserved table lines 586–588: `MXaoN`, `DPMXaoN`, `ADMXaoN`.
- Prose alias lists lines 724, 734 and 740: `MxaoN`, `DPMxaoN`, `ADMxaoN`.
- The discrepancy is present in upstream commit `44aedcff5032a6a16f271085e2d9b16de1f0ccbf` (2024-06-06, VCFv4.5 RC2), which introduced both spellings in the same change.
- Retrieved VCFv4.5 file history contains no later correction; scoped issue and pull-request searches returned no result.

The canonical spelling remains unresolved. This is an upstream specification ambiguity, not a SIRALOOM extraction typo. Obtain authoritative maintainer clarification or a source correction before implementation. Do not normalize case or silently accept both spellings.

### 10.4 Within-version source history

Upstream commit `e821e4f02ae25c2175f9a366edca1322d6a2de72` (2026-02-24, #851) changed LGL and LGP Type from Integer to Float. The pinned VCFv4.5 source contains Float for both rows, consistent with that source-history change.

### 10.5 CI status after research commits

GitHub Actions run `42185002380` completed successfully for commit `707dd56963076b9f3f570e5059f26aa3078d6f97`; backend, frontend and postgres-integration jobs all passed. This run predates subsequent research artifact commits, so it is not CI verification of the current PR head. The current PR head has no returned workflow run at the time of this audit refresh. Vercel reported pending for the latest head when last checked.

### 10.6 Current gate status

The 44-table work is now more precisely adjudicated but remains incomplete. Exact locator-level context reconciliation, VCFv4.1–4.4 row and clause comparison, whole-source semantic decomposition, VCFv4.0 immutable source capture, independent second-person review, implementation mapping, executable conformance testing and laboratory qualification remain open. The atomic ledger's complete contents were not independently re-read in this session because the GitHub content retrieval path returned an empty body for its large blob; this is a retrieval limitation, not evidence of an empty ledger.

PR #293 remains draft and unmerged. No production parser, normalizer, validator or BCF implementation changes were made in this research pass.
