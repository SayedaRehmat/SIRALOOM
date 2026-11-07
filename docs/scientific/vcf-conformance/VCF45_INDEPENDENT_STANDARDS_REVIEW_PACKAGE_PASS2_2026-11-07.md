# VCFv4.5 atomic candidate set — independent standards review package (pass 2)

**Review state:** author pass complete; independent review not yet assigned or completed.  
**Research branch:** `research/vcf-conformance-phase-a-20261105`  
**Existing PR:** [#293](https://github.com/SayedaRehmat/SIRALOOM/pull/293)  
**Pinned specification:** HTS-specs `510c107ba89aa13113818c9e4fa3071283cb7f7`, `VCFv4.5.tex`  
**Source Git blob SHA-1:** `307950e7eeafc33d524969ff906343f756adb7d7`  
**Source SHA-256:** `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5`

## Review set

- Supplemental candidate registry: `VCF45_ATOMIC_CANDIDATE_REGISTRY_PASS1_2026-11-07.json` — 161 records after pass-2 corrections and internal deduplication.
- Source-line crosswalk: `VCF45_ATOMIC_CANDIDATE_CROSSWALK_PASS1_2026-11-07.json` — all 75 original gap candidates mapped; zero unmapped.
- Complete-context review: `VCF45_ATOMIC_CONTEXT_REVIEW_PASS2_2026-11-07.json` — author-level context, modality, atomicity and source-locator review for all 161 surviving records.
- Reconciliation: `VCF45_ATOMIC_RECONCILIATION_PASS2_2026-11-07.json` — comparison against all 226 canonical requirements and all 61 GT/FORMAT candidates, with direct coverage, related overlap and internal deduplication dispositions.
- Ambiguity adjudication: `VCF45_SOURCE_AMBIGUITY_ADJUDICATION_2026-11-07.json` — six source-internal or source-scope questions retained.
- Original gap worklist: `VCF45_NEW_ATOMIC_CANDIDATE_WORKLIST_2026-11-07.json`.

## Formal schema validation

The canonical ledger schema declares JSON Schema Draft 2020-12. A reproducible validator uses `jsonschema==4.26.0`, calls `Draft202012Validator.check_schema`, and validates the full supplemental registry. GitHub Actions run **42350000590** completed successfully for the 161-record registry at the branch head when the registry was last changed.

Validation implementation:
- `scripts/validate_atomic_registry_schema.py`
- `.github/workflows/vcf-research-ledger-schema.yml`

This is a research-only workflow. No existing production CI job, parser, validator, normalizer, toolchain, or application code was changed.

## Reconciliation findings

- 161 surviving provisional records; unique provisional identifiers.
- Three records are covered/subsumed by canonical `VCF-REQ-000076` and must not be promoted separately.
- Seven internally duplicated provisional records were removed/merged, preserving all relevant source locators.
- Partial semantic relationships to existing CNV/tandem-repeat and GT/FORMAT requirements are explicitly recorded; shared topic or field names were not treated as identity.
- No direct duplicate was identified among the 61 GT/FORMAT candidates.
- The canonical 226-record ledger remains unchanged. No canonical IDs were allocated.
- All 75 worklist candidates have at least one mapped provisional record, including adjacent source context needed to express complete clauses.

## Required independent review

Please independently assess each of the 161 surviving records and the crosswalk for:

1. **Atomicity:** one independently testable behavior or one inseparable aggregate rule; identify residual compound clauses and over-splitting.
2. **Normative force:** exact preservation of MUST/MUST NOT/SHOULD/SHOULD NOT/MAY/MAY NOT/REQUIRED/RECOMMENDED/OPTIONAL and descriptive content.
3. **Conditions and actors:** whether conditions, field scope, producer/reader behavior and exceptions are complete.
4. **Source traceability:** exact pinned source lines and complete paragraph/table/list context.
5. **Duplicate reconciliation:** whether canonical coverage or partial relationships are correctly classified against the 226 canonical records and 61 GT/FORMAT candidates.
6. **Version scope:** no VCFv4.1–4.4 or VCFv4.0 applicability should be inferred from this VCFv4.5-only source.
7. **Ambiguities:** confirm, reject or leave unresolved the six documented issues below.

## Open source issues requiring explicit disposition

- Local-allele example: global GT `2/4` versus paired global example `2/2`; do not remap GT through LAA.
- Number=P/PSQ: positional PSQ alignment to PSL positions is the provisional interpretation; independent confirmation required.
- Xanthosine aliases: table/prose capitalization conflicts for M, DPM and ADM names; no case-folding or canonical spelling chosen.
- RUL omission clause: main text says RUS, parenthetical says RS.
- Reference/contig header tags: VCF recommendation, BCF requirement, optional SQ-derived tags and BCF “all entries” scope are not fully reconciled.
- POS/SVLEN versus STR/VNTR catalog wording: precise catalog field mapping remains open.

## Review outcome format

For every record, return one of:
- APPROVE_AS_ATOMIC
- APPROVE_WITH_EDIT (include exact proposed wording and source locator)
- SPLIT (identify each atomic child and preserve modality)
- MERGE_DUPLICATE (identify retained record and all source references)
- REJECT_AS_NON_NORMATIVE (explain whether it remains informative/descriptive)
- HOLD_SOURCE_AMBIGUITY (identify the unresolved source question)

No record should be independently approved by the original author. Reviewer identity, date, rationale, changed wording and evidence should be recorded in a separate review artifact. This package is not a laboratory qualification or implementation conformance claim.
