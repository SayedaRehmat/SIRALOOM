# Germline small-variant VCF profile reconciliation — first pass

**Status:** AUTHOR-PROPOSED; source-context review and independent standards review remain pending.  
**Base:** `e8ddc2a0d108ee8ca7486c2beb547ffa7edc6212` (PR #293 head at branch creation)  
**Canonical ledger:** `atomic-requirements.v1.json`, blob `81d27c5b306f120c45d1d5347b931f8ceaf1f47c`, 226 records  
**Scope:** ordinary germline called-variant VCF and GATK-style germline gVCF.  
**Release disposition:** NOT READY FOR LABORATORY QUALIFICATION.

## 1. Decision and interpretation

Phase 1 has two explicit input modes:

- `GERMLINE_VARIANT_VCF`: called germline SNVs, short insertions/deletions, defined complex short alleles and multiallelic small variants. It does not interpret reference-confidence blocks.
- `GERMLINE_GVCF`: the same called-variant classes plus sample-level reference-confidence blocks.

This overlay classifies every existing canonical requirement against both modes. It does **not** change the canonical ledger, source applicability, implementation status, test evidence, or review status. Scope disposition and conformance evidence are independent axes.

## 2. Reconciliation counts

| Profile | CORE_REQUIRED | CONDITIONAL_INPUT | OUT_OF_SCOPE_EXPLICIT_REJECTION | DESCRIPTIVE_RESERVED | NOT_APPLICABLE |
|---|---:|---:|---:|---:|---:|
| GERMLINE_VARIANT_VCF | 37 | 57 | 43 | 84 | 5 |
| GERMLINE_GVCF | 37 | 65 | 42 | 82 | 0 |

The overlay contains 226 unique canonical requirement IDs, each mapped to both profiles. The canonical ledger still has 26 production code mappings and 26 executed passing test mappings; 200 requirements remain without complete code/test mapping. Independent reviews: 0. Open source questions: 49.

**Important:** `OUT_OF_SCOPE_EXPLICIT_REJECTION` is a Phase 1 clinical-processing boundary. It does not mean the VCF record is syntactically malformed. The required runtime behavior is recognize, preserve, and route the record away from SNV/indel interpretation. That routing contract is not yet implemented/qualified by this overlay.

## 3. gVCF version boundary

The existing author crosswalk `vcf4.1-4.5-gvcf-reference-block-version-delta.v1.json` records:

- VCFv4.1/4.2: no dedicated gVCF reference-block section found in the reviewed core specification. GATK-style gVCF support must therefore use a separately pinned producer-convention profile.
- VCFv4.3/4.4: reference-only blocks use the INFO/END model with `<*>`; the reviewed source prefers `<*>` over `<NON_REF>`.
- VCFv4.5: reference blocks use sample-specific FORMAT/LEN; implicit positions impose per-sample GT/FORMAT restrictions, with the LAA exception; `<NON_REF>` is a backwards-compatibility alias of `<*>`; missing LEN may be inferred from END under the source's SHOULD force.

Do not back-apply VCFv4.5 LEN or implicit-position rules to VCFv4.3/4.4. Do not present GATK's earlier `<NON_REF>` convention as a VCF-core MUST.

## 4. Variant handling boundaries

- Called sequence alleles are normalized only against the configured, checksum-verified reference package. Preserve original record/allele representation and transformation provenance.
- `*` (spanning-deletion allele) is distinct from `<*>` (unknown/reference-confidence allele) and from `<NON_REF>`; it must not be normalized as an ordinary sequence ALT.
- Reference-confidence blocks are coverage/confidence evidence, not variant records. They must not enter small-variant normalization, annotation, or pathogenicity scoring.
- A reference-confidence gap is no-call/insufficient evidence, not benign evidence.
- Structural variants, BNDs, CNVs and tandem-repeat expansions are outside Phase 1 clinical interpretation. Recognize and preserve them; route them explicitly. Mixed files require a tested partial-processing policy.
- Do not silently discard fields, genotype data, sample identity, or original records.

## 5. Preserved future workstreams

The overlay enumerates the requirement IDs and existing repository assets retained for:
- PSO/BND and derivative-graph traversal;
- general structural variants;
- CNV;
- tandem repeats;
- VCFv4.5 base modifications;
- pedigree/haplotype metadata.

The current PSO/BND implementation and regression tests are retained. The last recorded full workflow passed on `f7636dfa0b83886f3a52e6f317657c5f8c63433c` (run [42370069178](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/42370069178)). The current PR #293 head `e8ddc2a0d108ee8ca7486c2beb547ffa7edc6212` is a documentation-only child of that tested commit. Separately, the profile overlay schema and integrity validator passed on profile-branch commit `c7dc2dc92cd0d00199a08ccd0ca7a43456918212` (run [42576161367](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/42576161367)). That run validates schema and reconciliation integrity only; it does not exercise VCF/gVCF runtime behavior or clinical processing.

## 6. Source-to-ledger gaps requiring new atomic requirements or separate policy records

### GVCF-43-44-REFERENCE-BLOCK-END

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.3, VCFv4.4
- **Evidence:** VCFv4.3.tex:1428-1465; VCFv4.4.tex:1686-1747
- **Finding:** The canonical 226 ledger does not contain atomic requirements for the VCFv4.3/4.4 reference-only block model using INFO/END and <*> (with <*> preferred over <NON_REF>).
- **Disposition:** MISSING_CANONICAL_ATOMIC_REQUIREMENTS
- **Next action:** Extract each normative obligation with complete source context, exact modality, and version applicability; map to tests.

### GVCF-41-42-GATK-PRODUCER-DIALECT

- **Class:** PRODUCER_CONVENTION
- **Versions:** VCFv4.1, VCFv4.2
- **Evidence:** No pinned locator yet
- **Finding:** The VCFv4.1/4.2 core sources reviewed contain no dedicated gVCF reference-block section. GATK-style <NON_REF>/END reference-confidence blocks therefore require a separately pinned GATK producer convention, not a fabricated VCF-core requirement.
- **Disposition:** PRODUCER_SOURCE_NOT_PINNED
- **Next action:** Pin exact GATK documentation/source and producer versions; define supported GATK gVCF dialects, including END, NON_REF, PL and GQ-band conventions; add real producer fixtures.

### GVCF-45-SAMPLE-SPECIFIC-LEN

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.5
- **Evidence:** VCFv4.5.tex:1846-1878
- **Finding:** The 226 ledger has a reserved FORMAT/LEN field-definition row (VCF-REQ-000169) and an END-to-LEN inference candidate (VCF-REQ-000129), but no complete atomic set for sample-specific block lengths, mixed sample block extents, and all boundary cases.
- **Disposition:** PARTIAL_CANONICAL_COVERAGE
- **Next action:** Decompose sample-specific LEN and END inference rules, mixed variant/reference records, and sample-level interval behavior into atomic requirements.

### GVCF-45-IMPLICIT-POSITIONS

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.5
- **Evidence:** VCFv4.5.tex:1846-1862
- **Finding:** VCF-REQ-000126/127 cover implicit-position GT/FORMAT restrictions and LAA inclusion, but no complete executable conformance evidence is mapped.
- **Disposition:** CANONICAL_REQUIREMENTS_UNMAPPED_TO_CODE_TEST
- **Next action:** Add mixed-sample positive/negative/boundary fixtures for missing GT, only-LAA exception, LAA containing <*> at block start, and implicit positions.

### GVCF-NON-REF-ALIAS

- **Class:** VCF_NORMATIVE_AND_PRODUCER_COMPATIBILITY
- **Versions:** VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** VCFv4.3.tex:1428-1465; VCFv4.4.tex:1686-1747; VCFv4.5.tex:1846-1878
- **Finding:** VCF-REQ-000128 records the VCFv4.5 backward-compatibility alias as RECOMMENDED/APPLICABLE only in 4.5. Earlier GATK <NON_REF> behavior is a producer convention and must not be generalized as a VCF-core MUST.
- **Disposition:** VERSIONED_SEMANTIC_AND_PRODUCER_SPLIT_REQUIRED
- **Next action:** Keep VCFv4.5 alias force exact; add a separate GATK dialect mapping for earlier versions after source pinning.

### SMALLVAR-STAR-SPANNING-DELETION

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** VCFv4.5.tex small-variant representation/decoding sections
- **Finding:** No dedicated canonical requirement explicitly separates the '*' spanning-deletion allele from <*> unknown/reference-confidence allele and ordinary sequence ALT alleles.
- **Disposition:** MISSING_CANONICAL_ATOMIC_REQUIREMENT
- **Next action:** Extract source clauses and add genotype/allele-index tests proving '*' is retained as a spanning-deletion placeholder, not normalized as a sequence allele or conflated with <*>.

### SMALLVAR-43-ORDERING

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** VCFv4.3.tex:711-716; VCFv4.4.tex small-variant section; VCFv4.5.tex small-variant section
- **Finding:** The small-variant source crosswalk identifies an explicit increasing-POS sorting requirement added in VCFv4.3, but this clause is not represented as a dedicated canonical requirement in the 226 ledger.
- **Disposition:** MISSING_CANONICAL_ATOMIC_REQUIREMENT
- **Next action:** Verify complete version context and add version-specific ordering tests; do not back-project the 4.3 clause to 4.1/4.2 without source evidence.

### SMALLVAR-REF-ALT-ANCHORING

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** VCFv4.1.tex:299-467; VCFv4.2.tex:316-484; VCFv4.3.tex:692-869; VCFv4.4.tex:1003-1180; VCFv4.5.tex:1164-1341
- **Finding:** The canonical 226 ledger does not yet expose a complete atomic mapping for small-variant REF/ALT anchoring, padding bases, and the distinction between encoding examples and a normalization algorithm.
- **Disposition:** SOURCE_REVIEW_AND_ATOMIC_MAPPING_REQUIRED
- **Next action:** Extract exact REF/ALT construction rules, padding, POS interpretation and examples; keep left-alignment separate because the VCF examples do not specify a canonical left-normalization algorithm.

### SMALLVAR-REFERENCE-VALIDATION

- **Class:** SIRALOOM_POLICY
- **Versions:** VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** No pinned locator yet
- **Finding:** Operational assembly identity, FASTA checksum, contig manifest, REF-vs-FASTA verification and reference-package qualification are not VCF format requirements and are not fully represented by the 226 VCF normative candidates.
- **Disposition:** SEPARATE_SIRALOOM_POLICY_REQUIREMENTS_REQUIRED
- **Next action:** Create policy requirements for assembly/package identity, operational FASTA/FAI/manifest checks, contig compatibility, REF validation, and persisted command/output provenance.

### SMALLVAR-NORMALIZATION

- **Class:** EXTERNAL_TOOL_AND_SIRALOOM_POLICY
- **Versions:** VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** bcftools norm documentation and pinned toolchain record
- **Finding:** Reference-based left alignment, common suffix/prefix trimming, multiallelic splitting, and preservation of original representation are pipeline normalization policy/tool behavior, not a VCF normative canonicalization rule.
- **Disposition:** SEPARATE_EXECUTION_REQUIREMENTS_REQUIRED
- **Next action:** Pin bcftools/HTSlib and reference package; define exact command/options, normalization idempotence, original-record mapping, Number=A/R/G remapping, and transformation reconciliation tests.

### SMALLVAR-MULTIALLELIC-REMAP

- **Class:** SIRALOOM_POLICY_AND_VCF_SEMANTICS
- **Versions:** VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** No pinned locator yet
- **Finding:** The ledger includes some allele-index and local-allele semantics but does not by itself prove end-to-end multiallelic splitting and correct remapping of GT, AD, PL/GL/GP, INFO/FORMAT Number=A/R/G and local-allele fields.
- **Disposition:** END_TO_END_TRANSFORMATION_TRACEABILITY_REQUIRED
- **Next action:** Add original-to-normalized allele map and positive/negative/property tests for genotype and all applicable allele-indexed fields.

### SMALLVAR-CORE-FIXED-FIELDS

- **Class:** VCF_NORMATIVE
- **Versions:** VCFv4.0, VCFv4.1, VCFv4.2, VCFv4.3, VCFv4.4, VCFv4.5
- **Evidence:** version-specific fixed-field and record grammar sections
- **Finding:** The 226 ledger currently has only two FIXED_FIELDS candidates and does not demonstrate complete CHROM/POS/ID/REF/ALT/QUAL/FILTER/INFO field grammar and semantic constraints for the Phase 1 profile.
- **Disposition:** SOURCE_REVIEW_AND_ATOMIC_MAPPING_REQUIRED
- **Next action:** Reconcile all eight fixed columns and optional FORMAT/sample columns, coordinate bounds, missingness, REF/ALT grammar, QUAL/FILTER semantics and per-version changes.

### VCF40-SOURCE-PROVENANCE

- **Class:** VCF_NORMATIVE_SOURCE
- **Versions:** VCFv4.0
- **Evidence:** https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- **Finding:** VCFv4.0 remains SOURCE_NOT_PINNED in the canonical ledger; the historical page is a discovery candidate, not byte-qualified normative source.
- **Disposition:** SOURCE_CAPTURE_BLOCKED
- **Next action:** Capture immutable authoritative bytes/revision and retrieval metadata, independently compute SHA-256, and keep the separate 1000 Genomes SV convention source distinct.

## 6.1 Full VCFv4.5 source-gap candidate triage

The existing VCFv4.5 source-to-ledger gap register contains **94 source-line candidates**. All 94 are now explicitly triaged against both Phase 1 profiles, while preserving the original source text, surrounding context, primary disposition and traceability disposition.

| Source-gap register class | Candidate lines |
|---|---:|
| Potential normative or mixed obligation | 50 |
| Recommendation, permission or implementation guidance | 37 |
| Informative or explanatory context | 6 |
| Ambiguous scope | 1 |
| **Total** | **94** |

The profile-scope triage is 39 CORE_REQUIRED, 22 CONDITIONAL_INPUT, 27 OUT_OF_SCOPE_EXPLICIT_REJECTION and 6 NOT_APPLICABLE candidates in each profile. These are candidate-level scope dispositions, not 94 newly approved requirements.

I independently reran the exact-locator overlap test against the current canonical ledger blob `81d27c5b306f120c45d1d5347b931f8ceaf1f47c`: **0 of 94 candidates have an exact source-locator overlap**. The original gap register was generated against older ledger blob `ba7d1bb0544f5d1105a4bd62f757decae13caee8`; the current-ledger recheck is now recorded separately in the overlay and enforced by the validator.

Exact-locator non-overlap does **not** prove semantic non-coverage. Each candidate still requires full-context adjudication to decide whether it maps to an existing requirement, needs a new atomic requirement, is recommendation/permission guidance, or is informative and should be excluded with rationale.

One concrete modality conflict is flagged: `VCFv4.5:L1187` says positions **must** be sorted in increasing order, while the old gap register labels the line `INFORMATIVE_EXAMPLE`. The VCFv4.3 version-delta crosswalk also records an explicit MUST sorting rule. This must be corrected through source-context review, not inherited from the old classification.

## 6.2 Semantic adjudication of the 50 normative/mixed candidates

The 50 `POTENTIAL_NORMATIVE_OR_MIXED_OBLIGATION` candidates and the single `AMBIGUOUS_SCOPE` candidate have now received an author-level semantic disposition. The complete record is in:

- `VCF45_SOURCE_CANDIDATE_ADJUDICATION_PHASE1_2026-11-09.json`
- `VCF45_SOURCE_CANDIDATE_ADJUDICATION_PHASE1_2026-11-09.md`
- Schema: `vcf45-source-candidate-adjudication.schema.json`

| Decision | Candidates |
|---|---:|
| Map to existing canonical requirement(s) | 4 |
| Propose new atomic requirement(s) | 27 |
| Split mixed candidates into separate obligations | 8 |
| Retain recommendation/permission without promoting to MUST | 5 |
| Exclude informative context from normative requirements | 1 |
| Retain for future variant/producer workstream | 6 |
| **Total** | **51** |

The pass produced **51 atomic proposals** (43 Phase 1, 8 future-phase), with 11 direct canonical mapping edges and 5 related/context-only edges. Related edges are not counted as complete semantic coverage. Proposals use temporary IDs and have not been inserted into the canonical 226-record ledger.

### Important adjudication decisions

- **L0081:** maps to the eight existing percent-encoding requirements `VCF-REQ-000114` through `VCF-REQ-000121`; it is the lead-in to their table, not a ninth independent escape rule.
- **L0104:** proposes a distinct rule that all meta-information lines precede the `#CHROM` header and data records. Existing `VCF-REQ-000003` only states that `##fileformat` is first.
- **L0129/L0130 and L0301:** preserve the VCF recommendation versus BCF requirement distinction. Contig/reference header tags are optional in VCF under these statements; this does not waive SIRALOOM's separate operational reference-identity policy.
- **L0133/L0135/L0136:** separate structured-attribute order independence, well-formedness of present meta-information lines, and arbitrary ordering of non-`fileformat` meta-information lines.
- **L0151/L0173/L0174/L0175:** separate required INFO declaration fields from recommended optional `Source`/`Version` attributes. The quote/escape rules at L0173–L0174 are scoped to the INFO metadata subsection where they occur; this pass does not silently generalize those locators to all structured metadata types.
- **L0159/L0164/L0166/L0168:** add generic Number cardinality and A/R ordering requirements; L0168 maps to existing arbitrary-ploidy Number=G ordering `VCF-REQ-000136`.
- **L0400/L0401:** retain the exact SHOULD force. Neither global duplicate record IDs nor use of the missing ID marker is promoted to a MUST rejection rule by these lines.
- **L0406:** decomposes simple-indel padding, the contig-position-1 right-padding exception, and optional padding for complex non-empty alleles.
- **L0407/L0416:** keep `*`, `<*>`, ordinary sequence alleles, symbolic SV alleles and breakend strings distinct. The generic symbolic-ALT padding rule excludes `<*>`, whose reference-call interval includes POS. Phase 1 must route unsupported symbolic SV/BND constructs without treating them as malformed sequence alleles.
- **L0411:** retained as a future upstream producer/reference-provenance obligation. It is not permission for a reader to rewrite incoming REF alleles.
- **L0488:** proposes a separate computed-END consistency rule. Existing END deprecation and END-to-LEN fallback requirements are related context, not complete coverage of this rule.
- **L0502:** maps the LAA-presence component to `VCF-REQ-000053`; GT-first is related to `VCF-REQ-000019`; the additional LAA ordering condition is a separate proposal.
- **L0715:** excluded from file conformance because it is a VCF-library API recommendation.
- **L0726:** retained for the future base-modification phase; existing Number=M cardinality coverage does not include the 0–1 value range.
- **L1989/L1996/L2027:** retained for CNV/tandem-repeat work. L1989 is split into a SHOULD for CN presence and a MUST consistency condition when present. L2027 refines existing RN behavior in `VCF-REQ-000091`.

The source excerpts and three preceding/following lines are stored exactly from the pinned VCFv4.5 source. The integrity validator now checks the source bytes, Git blob identity, candidate-set bijection, exact source/context equality, mapping references, proposal uniqueness and count consistency, and the profile's reference to the exact adjudication artifact blob.

**This is author adjudication, not independent standards approval.** Cross-version applicability for each candidate remains open. The remaining 37 recommendation/permission/implementation-guidance candidates and 6 informative candidates have not yet been adjudicated. The VCFv4.0 source-provenance gap remains open.

## 7. Provenance consistency issue

The current canonical ledger blob is `81d27c5b306f120c45d1d5347b931f8ceaf1f47c` and records 26 code mappings plus 26 executed-test mappings. Two downstream VCFv4.5 author artifacts still refer to older canonical ledger blob `ba7d1bb0544f5d1105a4bd62f757decae13caee8`, whose snapshot records zero code/test mappings:

- `VCF45_ATOMIC_RECONCILIATION_PASS2_2026-11-07.json`
- `VCF45_SOURCE_TO_LEDGER_GAP_REGISTER_2026-11-07.json`

Those artifacts must either be regenerated against the current ledger or explicitly retained as historical snapshots. Their gap counts must not be treated as reconciled to the current ledger until rerun.

The PR #293 description also still reports zero mappings and no successful full workflow, whereas the current ledger and superseding status-report section record 26 mappings and workflow run 42370069178. The PR description should be reconciled before it is used as the authoritative status surface.

## 8. Required next gates

1. Independently review every scope disposition and every source-gap candidate.
2. Reconcile the 226 canonical records against all source rows and cross-version deltas; do not assume this overlay fills source-coverage gaps.
3. Add canonical atomic requirements for missing VCFv4.3/4.4 reference-block rules and other confirmed omissions only after complete source-context review.
4. Pin GATK producer conventions and real GATK gVCF fixtures for the supported versions.
5. Implement and test gVCF block parsing, per-sample interval handling, LEN/END rules, implicit positions, LAA constraints, block gaps and transformation preservation.
6. Implement and test ordinary VCF allele/REF/ALT/normalization requirements, including spanning-deletion `*`, multiallelic remapping, reference identity, and mixed-file routing.
7. Keep VCFv4.0 blocked until exact source bytes and SHA-256 are captured.
8. Run full CI on the final exact commit, then independent standards review and laboratory qualification.

**No implementation-completion or laboratory-readiness claim is made by this reconciliation.**
