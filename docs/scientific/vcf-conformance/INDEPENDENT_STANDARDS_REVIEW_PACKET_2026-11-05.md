# Independent standards review packet — readiness assessment

**Assessment date:** 2026-11-05  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Pull request:** [#293](https://github.com/SayedaRehmat/SIRALOOM/pull/293)  
**Assessment scope:** Existing atomic ledger and source-review artifacts only. This document does not approve requirements or claim specification completeness.

## 1. Review disposition

**Disposition: NOT READY for a complete-ledger independent standards review.**

The current 75-record ledger can be submitted for a *scoped pilot review* of the source-derived file/header and FORMAT/GENOTYPE proposals, provided the reviewer is explicitly told that it is incomplete. It must not be represented as the complete VCFv4.0–4.5 requirement set.

The principal blocker is coverage, not merely reviewer availability: most VCF sections, tables, grammar productions, definitions, examples, footnotes and cross-references have not yet been decomposed into the ledger. The VCFv4.0 normative provenance is also unresolved.

## 2. Reproducible inventory findings

The following counts were recomputed from the branch artifacts at the assessed branch head:

| Measure | Observed |
|---|---:|
| Atomic-ledger records | 75 |
| Duplicate requirement IDs | 0 |
| Records with at least one source reference | 75/75 |
| Records with source locator values | 75/75 |
| Records marked `IN_REVIEW` | 75/75 |
| Records with independent second review approved | 0/75 |
| Records with implementation evidence | Not established by this inventory |
| Records with one or more test-evidence entries | 0/75 |no open-question entries | 46/75 |
| Records whose VCFv4.0 applicability is `SOURCE_NOT_PINNED` | 75/75 |
| Unresolved applicability cells in VCFv4.1–4.2 | 18 (9 each) |nresolved applicability cells | 0 in the current ledger; this is not proof of complete coverage |

The ledger contains 40 `DESCRIPTIVE` records. These are useful semantic definitions but must not automatically become rejection rules. The remaining normative-force vocabulary includes `MUST`, `MUST_NOT`, `SHOULD`, `RECOMMENDED`, `MAY`, `REQUIRED` and `NOT_STATED`; reviewers must check that each label reflects the source's actual modal language and not an editorial interpretation.

The 61-record FORMAT/GENOTYPE candidate artifact is a proposal inventory. Its expanded pass now includes general-ploidy genotype ordering, VCFv4.4 allele-level phasing and first-indicator inference, PSL/PSO/PSQ, VCFv4.5 local-allele semantics and base-modification semantics. Detailed per-key Number/Type and field-specific algorithms remain incompletely decomposed. It records primary-source-context review, not independent approval. One candidate (`FMT-GT-017`) is explicitly a split parent and must not be counted as an independently atomic requirement. The ledger's 75 records include 60 reconciled FORMAT/GENOTYPE children/independent candidates plus the initial seed records; the 61st candidate remains a parent candidate.

## 3. Source and traceability caveats

1. VCFv4.1–4.5 source files are pinned to the exact 40-character HTS-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`. Recorded Git blob SHA-1 values identify repository objects; they are not archived-source SHA-256 digests.
2. VCFv4.0 is not yet supported by an accepted, provenance-qualified normative source capture. The IGSR historical core page is a discovery/reference candidate only.
3. The separate 1000 Genomes structural-variation page is a producer/project convention source. It must remain separately classified and must not be merged into core VCFv4.0 requirements.
4. The source references in the ledger do not all include source-excerpt SHA-256 values or retrieval timestamps. The current 75-record ledger contains 0 test-evidence entries and 0 production implementation mappings. A stable line locator alone is not a complete evidence package.
5. The genotype candidate artifact now decomposes several major algorithms and conditional semantics, but detailed per-key Number/Type semantics, remaining reserved rows, and full cross-reference coverage still require review.
6. A zero unresolved-cell count for VCFv4.3–4.5 in the current 75 records only describes the records that happen to exist. It does not establish whole-specification coverage.

## 4. Ledger issues to resolve before a complete review

| Issue | Required action | Review gate |
|---|---|---|
| Incomplete specification coverage | Finish non-modal and modal discovery across every section and all table environments, including grammar, definitions, footnotes, examples and cross-references | Coverage inventory reconciled to each pinned source |
| Genotype candidate semantics | Reconcile each candidate to exact source passages and all dependent tables/definitions; split compound statements and retain split-parent links | Candidate-to-atomic ledger traceability complete |
| Version applicability | Resolve 4.1–4.2 open applicability cells from the exact source; do not infer 4.0 from later versions | Every ledger row has justified per-version disposition |
| VCFv4.0 provenance | Capture original historical core bytes, response metadata and SHA-256; establish provenance; separately capture 1000 Genomes SV convention source | Source steward accepts provenance and source class |
| Source excerpt evidence | Add stable excerpt hashes and retrieval metadata where technically available; preserve immutable source revision identifiers | Evidence reproducible by a reviewer |
| Normative force | Separate mandatory rules, recommendations, permissions, descriptive definitions, examples and producer conventions | No modal-strength inflation |
| Atomicity | Identify parent candidates, child requirements, shared predicates and cross-requirement dependencies | Each accepted requirement is independently testable |
| Independent review | Assign a reviewer independent of the authoring pass; capture reviewer identity/role, date, rationale, disposition and comments | Signed review record with no unresolved critical findings |

## 5. Independent reviewer instructions

The reviewer should not accept the ledger based on its record count or the presence of source links. Review each proposed requirement against the exact pinned source version and its complete semantic context.

For every record, assess:

- **Source fidelity:** Does the cited source actually state the proposed behavior?
- **Context completeness:** Have surrounding prose, definitions, table headers and rows, footnotes, examples and cross-references been examined?
- **Normative force:** Is the distinction between MUST/SHOULD/MAY, descriptive text and examples preserved?
- **Atomicity:** Can the statement be accepted or rejected independently? If not, identify a split parent and atomic children.
- **Actor and condition:** Is the obligated actor correct (producer, reader, or both), and are preconditions/conditional applicability explicit?
- **Observable testability:** Is the acceptance condition objectively testable without adding behavior not required by the source?
- **Version scope:** Is the behavior present in that exact version? Do not backport later semantics.
- **Exceptions and interactions:** Are missing values, ploidy, allele ordering, symbolic alleles, phasing, local-allele representation and BCF-only serialization behavior correctly bounded?
- **Source class:** Is the item core VCF specification, informative guidance, an external standard, a producer convention or SIRALOOM policy?
- **Disposition:** Approve, reject, request revision, or mark unresolved, with a reason and precise source locator.

The reviewer must independently inspect the source; the author's summary and candidate text are navigation aids, not evidence substitutes.

## 6. Required review record

For each reviewed requirement, record:

- requirement ID and exact ledger revision/commit;
- reviewer name or controlled reviewer identifier and relevant expertise;
- review date (UTC);
- disposition: `APPROVE`, `REVISE`, `REJECT`, or `UNRESOLVED`;
- source version, immutable source revision, and precise locator;
- findings on source fidelity, context, force, atomicity, applicability and testability;
- requested changes and rationale;
- conflict-of-interest/independence declaration;
- reviewer sign-off.

Do not set `second_review_status=APPROVED` until a real independent reviewer has completed and recorded the review. The author must not self-approve the independent-review field.

## 7. Proposed staged review boundary

A reviewer may begin a **pilot review** of the current 75 records to test the ledger schema and review protocol. The pilot must be labelled incomplete and must not be used to declare VCF conformance. A complete standards review should begin only after:

1. the source-structure inventory is reconciled to every pinned document;
2. all discovered requirements and non-requirements have explicit dispositions;
3. candidate-to-ledger mapping is complete and duplicate/split-parent relationships are explicit;
4. per-version deltas and VCFv4.0 provenance are resolved or formally excluded from the claimed scope;
5. source excerpts and locators are reproducible;
6. the ledger passes schema and cross-reference integrity checks.

## 8. Explicit non-claims

This packet does not claim that the 75 records are the complete VCF standard, that every source clause has been reviewed, that VCFv4.0 is normatively pinned, that any requirement has independent approval, that production code implements the requirements, that clause-specific tests have passed, or that any VCF version is laboratory-qualified.
