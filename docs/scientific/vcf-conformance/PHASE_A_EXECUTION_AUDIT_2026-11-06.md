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


## 11. Second execution increment — context closure and version applicability

### 11.1 All 44 VCFv4.5 table context locators captured

The table adjudication and queue now carry exact source-context locators for every VCFv4.5 table. Context evidence is drawn from the row-level INFO/FORMAT review, the full SV/breakend context review, and the sample-mixture/PEDIGREE/gVCF context review. The table queue has:
- 44/44 author-context locator reconciliations recorded;
- 0 generic boilerplate questions remaining;
- 44/44 preliminary five-version applicability matrices recorded;
- 44/44 full clause-level version reconciliations still pending;
- 0 independent reviews completed;
- 45 specific open questions (one full-delta question per table plus the VCFv4.5 alias ambiguity).

The table review status is therefore **author context and preliminary applicability recorded; full clause-level version delta and independent review pending**.

### 11.2 Preliminary version applicability by table

Each of the 44 VCFv4.5 table records now has a five-column applicability record for VCFv4.1, 4.2, 4.3, 4.4 and 4.5. The record distinguishes:
- absent/not found in the pinned source scan;
- prose enumeration versus Number/Type table;
- section-level correspondence versus exact table identity;
- features introduced in a later version;
- unresolved clause-level semantics.

This matrix is a source-navigation and applicability aid, not proof that all earlier-version clauses are equivalent or absent.

### 11.3 Confirmed version-specific semantic findings

The source-backed feature matrix and reserved-row crosswalk now record these high-confidence findings:

1. GLE is present in VCFv4.1 and VCFv4.2; VCFv4.3 change log explicitly records removal of the unused/ill-defined GLE FORMAT tag.
2. VCFv4.3 introduces the general-ploidy genotype-ordering algorithm; VCFv4.1/4.2 describe the earlier diploid likelihood ordering. VCFv4.4/4.5 retain the general-ploidy algorithm.
3. VCFv4.4 adds PSL/PSO/PSQ and Number=P; VCFv4.5 retains them.
4. SVLEN changes from Number=. in VCFv4.1–4.3 to Number=A in VCFv4.4, with explicit per-ALT semantics; VCFv4.5 retains and further specifies missing-value and compatibility behavior.
5. SVTYPE deprecation is recorded in VCFv4.4's change log and explicitly explained in VCFv4.5 normative prose as redundant with symbolic ALT.
6. VCFv4.5 introduces local-allele fields/Number=LA/LR/LG, base-modification M/DPM/ADM families, FORMAT LEN and END deprecation/computed semantics.
7. A dedicated character-encoding/percent-encoding section is present in VCFv4.3–4.5; no equivalent dedicated section/table was found in the VCFv4.1/4.2 scan.
8. Dedicated gVCF reference-block sections are present in VCFv4.3–4.5; VCFv4.5 adds sample-specific FORMAT LEN and the <NON_REF> alias of <*>.
9. Tandem-repeat section is present in VCFv4.4/4.5.
10. Sample mixture, PEDIGREE, small-variant representation and breakend sections are present across VCFv4.1–4.5; their version-specific clause changes still need reconciliation.

### 11.4 Reserved INFO/FORMAT row deltas

The new five-version row crosswalk preserves the earlier prose-only VCFv4.1/4.2 representations and does not invent Number/Type attributes for them. It mechanically records:
- VCFv4.1→4.2: reserved row inventory unchanged;
- VCFv4.2→4.3: INFO AD/ADF/ADR and FORMAT AD/ADF/ADR/PP added; GLE removed; Number/Type table representation formalized;
- VCFv4.3→4.4: FORMAT PSL/PSO/PSQ added;
- VCFv4.4→4.5: 44 FORMAT rows added and the INFO END row description changes to deprecated/backward-compatibility status.

Description changes in table rows are not treated as proof that the detailed field semantics were removed; the prose definitions remain the controlling context.

### 11.5 Current CI and review gates

At the time of this audit refresh, the current PR head is `f3a764a62c878e36b80e32becfe110988f061470`. GitHub Actions run `42186100933` is pending for that head; Vercel is also pending. A prior run `42185002380` passed all three jobs (backend, frontend and postgres-integration) for an earlier commit `707dd56963076b9f3f570e5059f26aa3078d6f97`; it must not be represented as a pass on the current head.

The next work is the full clause-level delta reconciliation for all 44 tables and then the remaining whole-source requirement ledger review. PR #293 remains draft and unmerged. Independent review, implementation mapping, clause-specific executable conformance testing and laboratory qualification remain open.


## 12. Reserved-row reconciliation and remaining VCF 4.5 table debt

### 12.1 All 44 tables: current status

The author-level table work now records:
- 44/44 exact source-context locator sets;
- 44/44 preliminary VCFv4.1–4.5 applicability matrices;
- 42/44 table version-delta assessments reconciled into dedicated evidence artifacts;
- 2/44 reserved INFO/FORMAT tables with row-level version deltas inventoried but field-by-field normative prose/footnote mapping still pending;
- 0 independent table reviews completed.

The only three table-specific open questions are:
1. VCF5.3 — complete field-by-field normative prose/footnote mapping for the 21 INFO rows across all five versions.
2. VCF5.4 — complete field-by-field normative prose/footnote mapping for the 64-field union of FORMAT IDs across all five versions.
3. VCF5.4 — resolve the upstream case-sensitive xanthosine alias inconsistency (VCF45-FORMAT-XAON-ALIAS-CASE-001).

### 12.2 New reserved INFO/FORMAT matrix

`vcf4.1-4.5-reserved-info-format-field-matrix.v1.json` now contains the union of all reserved row IDs and per-version row data:

- 21 reserved INFO row IDs across VCFv4.1–4.5.
- 64 reserved FORMAT row IDs across VCFv4.1–4.5 (the union includes GLE, which is removed in VCFv4.3).
- VCFv4.5 specifically contains 21 INFO rows and 63 FORMAT rows; all 84 have author row/context dispositions.
- VCFv4.1/4.2 prose-only representations are retained without fabricated Number/Type values.
- Per-version source lines, descriptions, Number/Type where present, and mechanical row changes are recorded.

### 12.3 Reserved-row transition findings

The reserved-row semantic delta artifact records:

- VCFv4.1→4.2: no reserved INFO/FORMAT row inventory changes found.
- VCFv4.2→4.3: INFO AD/ADF/ADR and FORMAT AD/ADF/ADR/PP added; GLE removed; Number/Type attributes formalized in tables.
- VCFv4.3→4.4: PSL/PSO/PSQ added with Number=P; SVLEN changes from Number=. to Number=A.
- VCFv4.4→4.5: 44 FORMAT rows added (one LEN, ten local-allele fields, three base-modification generic key patterns and 30 named aliases); INFO END row becomes explicitly deprecated/backward-compatibility.

The row inventory and mechanical version deltas are now reconciled. The remaining VCF5.3/VCF5.4 work is the exact field-by-field prose/footnote mapping and atomic requirement linkage, not re-counting or re-discovering the row sets.

### 12.4 Table-specific version-delta artifacts completed

Dedicated source-backed version-delta artifacts have been added for:
- genotype ordering and GLE removal/general-ploidy transition;
- PSL/PSO/PSQ phase-set list fields;
- gVCF reference blocks and FORMAT LEN;
- base modifications and Number=M;
- character encoding and percent-encoding;
- local alleles and Number=LA/LR/LG;
- small-variant representation and the VCFv4.3 increasing-POS rule;
- breakend syntax, symbolic <BND> prohibition and SVTYPE deprecation;
- sample mixture/PEDIGREE syntax, DPADJ/CNADJ/CICNADJ removal and CN changes.

These author-level artifacts are attached to the 44-table adjudication records. They do not constitute independent approval or executable conformance.

### 12.5 Upstream alias ambiguity remains blocking

The xanthosine alias discrepancy is traced to upstream VCFv4.5 RC2 commit `44aedcff5032a6a16f271085e2d9b16de1f0ccbf`; both spellings were introduced in the same upstream change. The source history does not establish canonical case. This remains an unresolved specification ambiguity and must not be normalized or silently accepted by implementation.

### 12.6 Current quality gates

- Independent second-person review: 0 completed.
- Atomic ledger field-level mapping for VCF5.3/5.4: pending.
- Complete source-to-requirement reconciliation for VCFv4.1–4.5: pending.
- VCFv4.0 authoritative historical source capture: pending.
- Production implementation mapping: not started.
- Clause-specific executable conformance tests: not started.
- Laboratory qualification: not started.

The current PR remains draft and unmerged. CI and Vercel results must be checked against the final PR head; prior successful CI runs on older commits do not qualify the current head.


## 13. Reserved INFO/FORMAT field mapping complete at author level

### 13.1 VCF5.3 — reserved INFO

`vcf4.1-4.5-info-reserved-field-clause-mapping.v1.json` now maps all 21 reserved INFO field IDs across VCFv4.1–4.5, including:
- exact source line and original description for each version;
- prose enumeration versus Number/Type table representation;
- Number/Type only where the source actually specifies them;
- field interpretation and VCFv4.5 semantic note;
- mechanical additions, removals and description changes.

Findings: AD/ADF/ADR enter the reserved INFO inventory in VCFv4.3; END's description changes to deprecated/backward-compatibility in VCFv4.5. The 21 INFO rows are author-mapped. SV-specific INFO definitions outside table VCF5.3 (e.g. SVLEN, SVTYPE, confidence intervals, CN, MATEID/PARID/EVENT/SVCLAIM) remain separate from this 21-row table and are handled in the SV semantic crosswalk.

### 13.2 VCF5.4 — reserved FORMAT

`vcf4.1-4.5-format-reserved-field-clause-mapping.v1.json` maps the union of 64 reserved FORMAT field IDs across VCFv4.1–4.5:
- VCFv4.1/4.2: 13 prose-defined fields, including GLE;
- VCFv4.3: 16 table-defined fields; AD/ADF/ADR/PP added and GLE removed;
- VCFv4.4: 19 table-defined fields; PSL/PSO/PSQ added;
- VCFv4.5: 63 table-defined fields; 44 new rows (LEN, local-allele family and base-modification families/aliases).

All 63 VCFv4.5 rows have author row/context review. The union count is 64 because GLE remains part of the historical version matrix but is removed from VCFv4.3 onward.

### 13.3 Table version-delta gate

The table adjudication queue now records:
- 44/44 VCFv4.5 table contexts reconciled at author level;
- 44/44 preliminary five-version applicability matrices;
- 44/44 table version-delta assessments reconciled at author level;
- 21/21 INFO row IDs author-mapped;
- 64/64 FORMAT union IDs author-mapped (63/63 in VCFv4.5);
- 0 independent reviews completed;
- 1 open source-level blocker: VCFv4.5 xanthosine alias capitalization.

**This completes the author-level VCFv4.5 table version-delta workstream, not the entire VCF stage.** Whole-source atomic requirement decomposition, exact clause-to-ledger linkage, independent review, VCFv4.0 source capture, implementation mapping, executable conformance and laboratory qualification remain separate gates.

### 13.4 Final current limitation

The xanthosine alias case discrepancy remains unresolved upstream. It is not safe to choose one spelling or silently accept both. The project must obtain authoritative maintainer clarification or a specification correction before implementing those aliases.

The GitHub content connector still did not permit a full independent re-read of the large atomic requirement ledger blob in this session. Row and version artifacts were validated structurally from their retrievable contents; complete ledger-to-source hash re-computation remains an explicit independent verification task.


## 14. VCFv4.5 atomic semantic addendum — 2026-11-06 continuation

### 14.1 New source review corrections

The focused VCFv4.5 cardinality review was expanded against the pinned source at HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`.

Two material corrections were made to the first draft of the semantic review:

1. **Number=M was explicitly defined and must not be left unresolved.** VCFv4.5.tex:195–202 defines Number=M as one value per possible base modification for the corresponding ChEBI ID and states that cardinality is determined by genotype and possible modifications for the corresponding alleles. The detailed rules at 201–218 define eligible-base counting, sequence order, N-strand adjacency, GT/phasing order, unphased aggregation, missing/symbolic allele behavior and unstranded encoding. The reserved table and field-specific prose at 556–588 and 720–744 define key families, aliases, ranges and reference-block behavior. The earlier claim that no general Number=M definition was found is withdrawn.
2. **The local-allele worked example has a GT inconsistency.** At VCFv4.5.tex:703–704, the local row has GT `2/4` while its paired global AD/PL row has GT `2/2`. The remaining paired examples do not show the same discrepancy. The prose says genotype may be given against local alleles, but the first pair does not establish an unambiguous global/local GT index mapping. The semantic review now marks this unresolved and prohibits using that first pair as a full-record equivalence oracle until the source is clarified.

The Number=P section was also corrected to quote the actual general definition at VCFv4.5.tex:195–197: one value for each allele value defined in GT. It separately records the PSQ field-specific “one per phase set in PSL” wording as an open cardinality reconciliation item. The explicit PSQ missing-value clarification is scoped to VCFv4.5; VCFv4.4 is marked CHANGED, not treated as having the same clause.

### 14.2 Supplemental atomic requirements

Created `vcf4.5-cardinality-local-allele-atomic-addendum.v1.json` with **34 supplemental atomic requirement records**, IDs `VCF-REQ-000227` through `VCF-REQ-000260`.

Coverage of this supplemental batch:
- Number=LA, LR and LG cardinality;
- LAA distinct 1-based ALT indices, order, presence and BCF missing/empty-vector semantics;
- local/global field semantic equivalence and GQ behavior;
- Number=M cardinality and GT dependency;
- eligible-base counting and ordering, U/T synonymy, N-strand adjacency, GT/phasing order and unphased aggregation;
- missing/symbolic allele behavior, unstranded storage, fraction bounds, reserved key patterns, aliases and reference-block propagation;
- Number=P cardinality and PSL/PSO/PSQ field-specific rules, including the VCFv4.5 PSQ missing-value clarification.

The batch uses the existing atomic ledger schema shape. A structural check against the schema's required requirement fields and enumerated domains found:
- 34 records;
- 34 unique requirement IDs;
- no missing required fields;
- no invalid domain, normative-force, requirement-kind or version-applicability enum values;
- source references present for every record.

This was a schema-directed structural check, **not** a formal JSON Schema engine run. All records remain `IN_REVIEW`; none is independently approved, implementation-mapped or test-executed.

### 14.3 Integration boundary

The canonical `atomic-requirements.v1.json` was not overwritten because the GitHub file-content connector returned zero content for that large blob despite returning its non-empty SHA. The supplemental batch is therefore a separate addendum and is not yet merged into the canonical 226-record ledger. Before integration, retrieve the full ledger bytes through a verified route, check for ID collisions and duplicates, merge the 34 records, recompute dependent hashes, and validate the entire resulting ledger against `atomic-requirement-ledger.schema.json`. Do not claim the canonical ledger contains 260 records until that merge and verification are complete.

### 14.4 Remaining VCFv4.5 semantic work

1. Resolve the local GT mapping contradiction through authoritative source clarification or a documented maintainer issue; until then, retain the raw GT and LAA independently and do not infer a remapping rule.
2. Resolve Number=P versus PSQ per-phase-set cardinality for repeated phase-set identifiers.
3. Resolve xanthosine alias capitalization (table `MXaoN`/DPMXaoN/ADMXaoN versus prose `MxaoN`/DPMxaoN/ADMxaoN) without silently accepting or normalizing either form.
4. Continue full source-to-atomic decomposition beyond the reserved-field subset: grammar, all tables, prose, footnotes, definitions, non-modal constraints, examples and cross-references.
5. Complete independent review before promoting any author candidate to reviewed status.

### 14.5 VCFv4.1–4.4 and VCFv4.0 work remains active

The local-allele and base-modification families are identified as VCFv4.5 introductions in the existing version-delta artifacts. Number=P and PSL/PSO/PSQ are introduced in VCFv4.4 and retained in VCFv4.5; the explicit PSQ missing-value clarification is VCFv4.5-specific. The broader VCFv4.1–4.4 reconciliation remains incomplete and must cover all reserved fields, GT/GL semantics, SV/breakend behavior, grammar, tables, footnotes and cross-references rather than only these newly reviewed topics.

VCFv4.0 source discovery continues separately. The IGSR historical page remains a candidate only; original immutable source bytes and a defensible SHA-256 remain uncaptured. No VCFv4.0 source status is promoted.

### 14.6 Latest commit and qualification state

Latest commit recorded for this continuation: `c4828d8746aaa06031a7d6813895f331af82d1f0` (PSQ VCFv4.4/4.5 applicability correction). The semantic review, source-discovery audit and supplemental atomic addendum are committed on the research branch. No parser/validator/normalizer code was changed; no conformance tests were run; no CI pass or laboratory qualification is claimed.


### 14.7 Deduplication against the existing genotype candidate set

A separate reconciliation artifact, `vcf4.5-cardinality-atomic-candidate-reconciliation.v1.json`, maps the 34 supplemental IDs to the existing 61-item `genotype-format-atomic-candidates.v1.json` set:

- 28 supplemental records map to one or more existing candidate IDs;
- 23 mappings are direct or direct-overlap matches;
- 5 mappings are split, narrowed or combined candidate relationships;
- 6 records have no matching candidate identified in that candidate artifact.

This confirms that the 34 records must **not** be described as 34 net-new unique scientific requirements. They are a schema-shaped decomposition batch used to make field-specific atomic statements explicit. Canonical-ledger deduplication remains blocked until the full large ledger blob can be retrieved and compared. The addendum is intentionally separate and all records remain IN_REVIEW. The canonical 226-record ledger count is unchanged.


### 14.8 CI and branch state after the latest documentation commits

The last PR-triggered workflow retrieved in this continuation was run `42198569374`, associated with commit `9b7523fe5869e1fa6ed8366423a9721c4f1143b2`. Its backend, frontend and PostgreSQL-integration jobs are now all **cancelled**; no failed step was reported, but this is not a passing run. No workflow run was returned for the later documentation-only head `a58c1392375c5d78f1a78098553ed0085540fb8f`.

The research branch comparison against `main` reports 276 commits ahead and 3 behind at the time of this check. No merge or rebase was performed. All changes in this continuation are confined to `docs/scientific/vcf-conformance/`; no application code or CI configuration was modified. CI status for the latest head remains unverified.


### 14.9 Additional VCFv4.5 GT/GL semantic review

Created `VCF45_GT_GL_SEMANTIC_REVIEW_2026-11-06.md`, reviewing source lines 498–516 and 612–683. It decomposes FORMAT ordering, duplicate-key prohibition, GT-first, no-required-key semantics, missing values, trailing-field omission, GT phasing indicators, allele values, ploidy, GL/GP/PL/PP semantics and the general-ploidy genotype-ordering algorithm. It also identifies a candidate-force correction: VCFv4.5 says GT should remain present when specified in FORMAT, so the trailing-GT exception must not be promoted from SHOULD to MUST.

The review maps the existing FMT-GT candidate IDs and keeps examples distinct from normative prose. The local-allele GT example inconsistency remains quarantined. No new canonical requirement IDs were allocated in this GT/GL review, avoiding another overlapping ID batch.

The commit for this GT/GL review is `9ac60ba09abb779bd997f9a16254ffdf135b7a34`. GitHub Actions run `42199179587` was returned as pending for that commit at the time of inspection. It has not been observed passing; no CI pass is claimed.

At the latest branch comparison, the research branch is 280 commits ahead and 3 behind `main`. No merge or rebase was performed.


## 15. Execution update — 2026-11-07

### 15.1 Canonical ledger recovery and VCFv4.5 addendum reconciliation

- The canonical `atomic-requirements.v1.json` file returned an empty content payload through the Contents API despite a valid Git blob SHA. The exact canonical content was recovered through the Git blob endpoint using blob SHA `ba7d1bb0544f5d1105a4bd62f757decae13caee8`.
- Recovered baseline: 226 unique canonical requirement records, IDs `VCF-REQ-000001` through `VCF-REQ-000226`.
- The separate GT/FORMAT candidate artifact contains 61 candidates (`FMT-GT-001` through `FMT-GT-061`).
- All 34 supplemental VCFv4.5 cardinality/local-allele candidates (`VCF-REQ-000227`–`VCF-REQ-000260`) were reconciled against the recovered canonical ledger and GT/FORMAT candidate artifact in `vcf4.5-canonical-ledger-reconciliation.v1.json`.
- Reconciliation disposition: 29 candidates have existing canonical-ledger overlap/matches; four remain unmatched semantic candidates (`000234`, `000256`, `000258`, `000260`); one (`000236`) is retained as library API implementation guidance rather than a file-validation rule.
- The canonical ledger was intentionally not modified. No duplicate candidate was appended, and no new candidate was marked independently approved, implemented or tested.
- Four malformed source locators in the addendum were repaired against the pinned VCFv4.5 source: M fraction range line 726; named aliases lines 724–740; reference-block propagation line 728; ADFM/ADRM non-reservation line 742.

### 15.2 VCFv4.5 reserved INFO/FORMAT row traceability

- Added `vcf4.5-reserved-info-format-row-ledger-traceability.v1.json`.
- Exact source-line mapping covers 21 reserved INFO rows and 63 reserved FORMAT rows: 84/84 map to exactly one canonical ledger record.
- Ten key-only ambiguities caused by INFO/FORMAT repeated names (AD, ADF, ADR, DP and MQ) are resolved using namespace and exact source line.
- Number and Type values in all 84 table rows match the corresponding canonical ledger titles; zero Number mismatches and zero Type mismatches.
- This closes the table-row-to-ledger locator mapping only. It does not close the surrounding prose, footnote, exception, example, or cross-reference review; independent review, implementation mapping and executable tests remain zero.

### 15.3 VCFv4.5 modal source-line traceability gap register

- The two VCFv4.5 primary-context review artifacts contain 185 unique modal-language candidate lines. All have primary context dispositions.
- A conservative exact-source-line overlap audit against the canonical ledger found 91 candidate lines with at least one ledger source-locator overlap and 94 without an exact overlap.
- The 94-line gap register is stored in `VCF45_SOURCE_TO_LEDGER_GAP_REGISTER_2026-11-07.json`: 50 potential normative/mixed obligations, 37 recommendation/permission/implementation-guidance candidates, six informative/explanatory candidates and one ambiguous-scope candidate.
- Exact non-overlap is a traceability warning, not proof that no semantic coverage exists. Every gap requires manual semantic adjudication; no automatic ledger promotion was performed.

### 15.4 Modal candidate intake/context reconciliation

- The seven VCFv4.1–4.5 primary-context review artifacts contain exactly 510 unique candidate IDs, matching all 510 entries in `normative-candidate-intake.v1.json`; there are no missing or extra IDs.
- Updated the intake's `review_status` and `reviewer_notes` for all 510 candidates to reflect `SOURCE_CONTEXT_REVIEWED_PRIMARY_ONLY` and the exact context artifact/disposition.
- Preserved `atomicity_status=NOT_ASSESSED`, `traceability_status=UNMAPPED`, and empty requirement ID arrays. All 510 therefore remain unatomized/unmapped; immediate-neighbour context review is not expanded semantic review or ledger traceability.
- Audit record: `MODAL_CANDIDATE_CONTEXT_RECONCILIATION_2026-11-07.json`.

### 15.5 VCFv4.0 source acquisition research

- New research artifact: `VCF4_0_SOURCE_ACQUISITION_RESEARCH_2026-11-07.md`.
- The IGSR/1000 Genomes core VCFv4.0 page is corroborated by the VCFtools historical specification index as the historical location for the older VCFv4.0 document. An alternate descriptive route and a test-site copy expose matching rendered content.
- A contemporaneous VCFtools poster provides contextual examples only. The separate 1000 Genomes SV conventions page remains a producer/project-specific extension source.
- No original immutable VCFv4.0 source bytes, revision identifier, or SHA-256 were captured. VCFv4.0 remains `SOURCE_NOT_PINNED`; no requirement applicability was promoted.

### 15.6 CI and branch state

- Workflow run `42199248747` for commit `6eeb2d1fdb6bb5d34f43c1d459b8ecf7b1da5b86` completed with failure: frontend passed; PostgreSQL integration passed; backend tests failed (6 failed, 2,241 passed, 49 skipped). The six failures concern VCFv4.0 reserved FORMAT semantics and populated VCFv4.5 Number=P without GT. This research branch did not change production parser/validator code to address them.
- Latest branch commit after the documentation-only updates is `f3cd652723407f39591b379d1e0dc21c22adb6c1`. No GitHub Actions workflow run was returned for that exact commit; its combined commit status reports Vercel pending. Do not claim CI pass for the latest head.
- Branch comparison against `main`: 288 commits ahead, 3 behind. No merge, rebase, reset, or force-push was performed.
- All changes in this update remain under `docs/scientific/vcf-conformance/`; no production parser, validator, normalizer, toolchain, or CI code was modified.

### 15.7 Remaining execution gates

1. Manually adjudicate the 94 VCFv4.5 source-line gaps and reconcile each normative statement to an existing requirement, a new atomic requirement, or an explicit non-requirement disposition.
2. Complete full VCFv4.5 prose/grammar/definitions/footnotes/examples/cross-reference traceability, including the local-GT example inconsistency, Number=P versus PSQ repeated phase-set cardinality, and xanthosine alias capitalization discrepancy.
3. Complete independent review; author-level reviews remain non-independent.
4. After the VCFv4.5 source-to-ledger gate, perform expanded row-by-row semantic reconciliation and atomization for VCFv4.1–4.4, preserving version deltas.
5. Continue original VCFv4.0 source-byte acquisition and provenance qualification in parallel.
6. Resolve the six backend CI failures in their owning implementation workstream; do not mix implementation changes into this documentation-only research branch.
