# VCF version-by-version conformance status report

**Report date:** 2026-11-07  
**Repository:** SayedaRehmat/SIRALOOM  
**Branch:** research/vcf-conformance-phase-a-20261105  
**Implementation baseline reviewed:** f0e04c446fe2b62f185fe798fbe823730f75125c  
**Disposition:** NOT READY FOR LABORATORY QUALIFICATION

This report separates parser behavior, executable test evidence, explicit capability limits, source-reconciliation status, and laboratory qualification. A parser accepting a version header is not proof of full conformance. A test existing in the repository is not proof it passed on the current commit. No independent standards approval or laboratory qualification is claimed.

## 1. Release-gate status

| Gate | Current evidence | Status |
|---|---|---|
| VCFv4.5 PSO/BND | Production validator has cross-record PSO checks, per-ALT MATEID matching, reciprocal coordinate checks, CIPOS uncertainty reporting, single-breakend handling, ordered PSL/PSO comparison and source-derived regression fixtures | Implemented; latest exact-head execution still required |
| VCFv4.5 Number=M | Production slot projection and explicit strandedness policy exist; unstranded cross-record checks and boundary reporting exist | Implemented with declared limitations; latest exact-head execution still required |
| VCFv4.5 full semantics | Reserved fields, local alleles, GT/GL ordering, base modifications, phase-set semantics and SV/BND logic have targeted tests | Partial; full source-to-code/test traceability absent |
| VCFv4.1–4.4 | Pinned sources and author crosswalks exist | Source crosswalks exist; semantic/atomic reconciliation and version-specific execution evidence incomplete |
| VCFv4.0 source | Historical IGSR VCFv4.0 page identified and content reviewed | Blocked: exact authoritative source bytes and SHA-256 not captured |
| Requirement traceability | atomic-requirements.v1.json contains 226 records: 142 behavior candidates and 84 reserved-field descriptive candidates | All 226 remain IN_REVIEW; zero code mappings; zero executed-test mappings; zero independent reviews; 49 unresolved source questions |
| Full verification | A previous full CI run passed on d69d351b44f631f82ae754049063820efdd9a159; later changes were made after that run | Not verified on implementation baseline 965be03d56fe2d05c4dca9a9c6837333ca80d4fc |

**Ledger distinction:** the registry's atomic_requirements_created count of 142 refers to behavior requirements; the additional 84 records are descriptive reserved INFO/FORMAT row candidates. There are 226 records total. The registry reports zero code mappings and zero executed-test mappings. Tests in the repository therefore cannot yet be treated as a complete requirement-level conformance matrix.

## 2. Version-by-version assessment

### VCFv4.0

**Source:** Historical IGSR page, https://www.internationalgenome.org/wiki/Analysis/vcf4.0/. Source identity is corroborated, but original normative bytes are not pinned. The provenance record status is HISTORICAL_SOURCE_IDENTITY_CORROBORATED_EXACT_SOURCE_BYTES_AND_SHA256_BLOCKED.

**Implemented:** SUPPORTED_VCF_VERSIONS includes VCFv4.0. A VCFv4.0-specific implicit FORMAT definition helper exists for GT, DP, FT, GL, GQ and HQ. Generic fixed-column, record, genotype and cardinality validation is shared with other versions.

**Tested:** tests/test_vcf40_gt_required.py covers GT presence, explicit missing GT alleles and VCFv4.0 reserved FORMAT declarations. tests/test_vcf_validation.py::test_strict_validation_accepts_standardized_vcf_4x_versions includes VCFv4.0 header acceptance.

**Unsupported / blocked:** VCFv4.0 must not be treated as source-qualified until the historical normative source is captured as exact bytes with a verified SHA-256. 1000 Genomes SV conventions/extensions are not interchangeable with the VCFv4.0 core specification.

**Unresolved:** Full historical source provenance, complete source-to-requirement extraction, full VCFv4.0 reserved INFO/FORMAT reconciliation, and a dedicated version-specific conformance corpus.

### VCFv4.1

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.1.tex; SHA-256 7d29ef8f93745f246202da3e32107ea13b036bbefcb31f7971a3ce31f1045baa.

**Implemented:** Strict parser accepts VCFv4.1. Version-specific reserved FORMAT definitions are enforced for GT, DP, FT, GL, PL, GP, GQ, HQ, PS, PQ, EC and MQ. The VCFv4.1/4.2 GLE field is recognized as reserved but requires an explicit header definition because the source prose does not establish a reliable Number cardinality. The VCFv4.1/4.2 INFO prose does not provide the Number/Type table later versions provide; the known reserved INFO identifiers are recognized, while custom INFO fields require a header declaration.

**Tested:** Shared cross-version acceptance and cardinality tests in tests/test_vcf_validation.py exercise VCFv4.1. These are shared tests, not a complete VCFv4.1 conformance suite.

**Unsupported / blocked:** No whole-version conformance claim is supported.

**Unresolved:** Complete reserved-row prose/footnote/cross-reference review, atomic mapping to implementation, version-specific valid/invalid/boundary corpus, and executed-test mapping.

### VCFv4.2

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.2.tex; SHA-256 66dbd167e8fb309708e0956ffbb12808bd338a703fbf034d80d1ead56ae480cc.

**Implemented:** Strict parser accepts VCFv4.2 and enforces the same version-specific reserved FORMAT definitions as VCFv4.1, including explicit unresolved handling for GLE. The VCFv4.1/4.2 INFO prose does not provide the Number/Type table later versions provide; the known reserved INFO identifiers are recognized, while custom INFO fields require a header declaration. The version-delta register records the VCFv4.2-to-4.3 removal of GLE from the reserved set.

**Tested:** Shared cross-version acceptance and cardinality tests in tests/test_vcf_validation.py exercise VCFv4.2. No complete VCFv4.2-specific conformance corpus is evidenced.

**Unsupported / blocked:** No whole-version conformance claim is supported.

**Unresolved:** Full reserved-field semantic reconciliation, GLE version behavior and compatibility tests, implementation mapping, and dedicated executed conformance report.

### VCFv4.3

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.3.tex; SHA-256 332d8b910ac9952bfba04374118f8c4f318ea996d5017599e68f80379fd61cde.

**Implemented:** Version-specific VCFv4.3 reserved INFO and FORMAT definitions are now enforced, including structural-variant fields. Header Number/Type declarations that contradict the pinned definitions are rejected. Non-reserved custom INFO/FORMAT keys without header declarations are rejected. VCFv4.3 GLE is no longer reserved (it was removed in 4.3). VCFv4.3 copy-number FORMAT/CN is Integer (tested against the VCFv4.4 Float transition). The parser applies the VCFv4.3+ SAM reference-name grammar to CHROM and breakend remote-contig names.

**Tested:** tests/test_vcf_validation.py includes VCFv4.3+ contig grammar, external-contig capability and breakend tests. Shared cross-version tests include VCFv4.3.

**Unsupported / blocked:** External assembly contigs are valid syntax but explicitly unsupported by the configured reference-package contract. They must be reported as a capability limitation, not mislabeled as universally invalid VCF syntax.

**Unresolved:** Full source-to-code mapping for VCFv4.3 semantic changes, full reserved INFO/FORMAT reconciliation, and independent/version-specific conformance execution.

### VCFv4.4

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.4.tex; SHA-256 4c88884cf6b016efcec691d5186432a2e0b679396204d14770e89839ef536e1a.

**Implemented:** Version-specific VCFv4.4 reserved INFO and FORMAT definitions are now enforced, including structural-variant and tandem-repeat wire definitions. Header Number/Type declarations that contradict the pinned definitions are rejected. Non-reserved custom INFO/FORMAT keys without header declarations are rejected. CN changes to Float; MATEID and SVLEN use Number=A; CIPOS/CIEND use Number=.; PSL/PSO/PSQ and Number=P are enforced. Cross-record PSO obligations and reciprocal BND PSL/PSO comparisons are applied to VCFv4.4 and VCFv4.5. SVTYPE is deprecated and is not required for VCFv4.4/4.5 breakpoint-notation records. Tests cover leading GT phase separators, Number=P/GT dependency, PSO obligations, reciprocal BND phase vectors, per-ALT MATEID, and telomeric coordinate zero.

**Tested:** Shared cross-version tests and targeted VCFv4.4 reserved INFO/FORMAT mismatch, GT/local-allele boundary, PSO and BND tests exist in tests/test_vcf_validation.py, tests/test_vcf44_phase_set_conformance.py and tests/test_vcf44_breakend_phase_conformance.py. The VCFv4.4 phase-set suite also tests PSQ positional behavior for repeated PSL identifiers with distinct quality values and missing-value alignment.

**Unsupported / blocked:** VCFv4.5-only Number=M base-modification semantics and the VCFv4.5 local-allele model must not be back-applied to VCFv4.4. External assembly contigs remain a reference-package capability limitation for VCFv4.3+.

**Unresolved:** Production cross-record PSO/BND logic is now applied to VCFv4.4 and VCFv4.5. New VCFv4.4 tests cover phase-set-wide PSO obligations, reciprocal BND PSL/PSO equality, MATEID Number=A cardinality, Number=P requiring GT, and telomeric remote coordinate zero. These tests still require exact-head CI execution and full requirement mapping. Full reserved INFO/FORMAT and SV/breakend semantic reconciliation, dedicated corpus execution, and requirement-level traceability remain pending.

### VCFv4.5

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.5.tex; SHA-256 37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5.

**Implemented:**
- Reserved INFO/FORMAT definitions include M, P, LA, LR and LG cardinality handling, local-allele fields, structural-variant fields and tandem-repeat wire definitions RN, RUS, RUL, RUC, RB, CIRUC, CIRB and RUB. Reserved header Number/Type mismatches are rejected. Non-reserved custom INFO/FORMAT keys without header declarations are rejected.
- GT allele values remain global ALT indexes; LAA controls local A/R/G vectors.
- Number=M slot mapping preserves GT allele order and exposes per-value biological slot assignments.
- An explicit analysis-creation field, base_modification_strandedness, is persisted in Analysis.configuration and passed to both VCF validation passes. None means unknown/not asserted; values are never inferred from VCF observations.
- The unstranded policy checks same-record and adjacent-record complementary bases, same sample, contig, modification field, GT copy and phase-set context. Unresolved phase contexts are counted and warned; length-changing alleles are rejected for this coordinate projection.
- PSO is required across every observed occurrence of a sample/phase-set when that phase set contains a recognized symbolic SV or breakpoint-notation allele.
- BND MATEID association is retained per ALT, reciprocal ALT and coordinate checks use CIPOS intervals, unresolved CIPOS is surfaced, and reciprocal PSL/PSO comparison preserves GT chromosome-copy order.
- Single breakends and telomeric remote coordinate zero are included in the validator grammar.
- VCFv4.4 and VCFv4.5 deprecate SVTYPE; BND records may be represented by breakpoint notation and MATEID without requiring SVTYPE. MATEID Number=A and per-ALT CIPOS semantics are applied to VCFv4.4/4.5. If SVTYPE is supplied, a conflicting value is rejected.

**Tested:** Targeted suites include tests/test_vcf45_number_m_conformance.py, tests/test_vcf45_base_modification_position_semantics.py, tests/test_vcf45_phase_set_positional_semantics.py, tests/test_vcf45_gt_semantic_conformance.py, tests/test_vcf45_laa_requirements.py, tests/test_vcf45_local_allele_projection_conformance.py, tests/test_vcf45_reserved_sv_format_conformance.py, and tests/test_vcf_assay_policy.py. Shared tests in tests/test_vcf_validation.py cover VCFv4.5 cardinality, local alleles, reference blocks, CIPOS/CIEND and reserved INFO/FORMAT domains. The full backend suite previously passed on d69d351b44f631f82ae754049063820efdd9a159; later PSO/BND, CIPOS, assay-policy and test changes are newer than that successful run.

**Unsupported / bounded behavior:**
- Unstranded Number=M cross-record coordinate projection is restricted to equal-length sequence alleles. Length-changing alleles raise VCF_BASE_MODIFICATION_UNSTRANDED_UNSUPPORTED.
- Heterozygous unphased or partially phased calls without a per-allele PSL or a usable PS cannot establish cross-record haplotype identity; those observations remain record-local and are reported with VCF_BASE_MODIFICATION_UNSTRANDED_PHASE_CONTEXT_UNRESOLVED. Fully phased genotypes without PS/PSL use the implicit phase set required by the VCFv4.4/4.5 specification.
- Missing/ambiguous assay strandedness is not inferred. The caller must explicitly select stranded or unstranded to apply that policy.
- External assembly contigs remain unsupported by the configured reference-package contract.
- VCF itself does not prove experimental truth of base-modification fractions/depth; assay/read-level evidence is outside this validator's input evidence.

**Unresolved:**
- Derivative chromosome reconstruction and global PSO ordinal uniqueness/monotonicity are not implemented.
- Strict reciprocal BND PSL/PSO equality remains an implementation interpretation requiring standards-owner review.
- Xanthosine alias capitalization remains inconsistent in the pinned source; both spellings are retained without normalization.
- The local-row GT value in the VCFv4.5 LAA example remains an apparent source typo; global GT indexing is preserved.
- PSQ repeated-identifier interpretation is implemented positionally from Number=P, but upstream clarification remains open.
- Full requirement-to-code/test mapping, independent source review and laboratory qualification remain pending.

## 3. Cross-version source reconciliation

The current author research artifacts establish source inventory but do not establish complete conformance:

- vcf4.1-4.4-reserved-row-version-crosswalk.v1.json reports source-row crosswalk complete, but semantic and atomic reconciliation pending. It inventories 18 INFO / 13 FORMAT rows for 4.1; 18 / 13 for 4.2; 21 / 16 for 4.3; and 21 / 19 for 4.4.
- vcf4.1-4.4-genotype-sv-breakend-semantic-crosswalk.v1.json reports an expanded author source-context crosswalk, with atomic reconciliation still pending.
- vcf4.1-4.5-version-delta-register.v1.json records author reconciliation of all 44 VCFv4.5 tables and the five-version applicability matrices. It reports zero independent table reviews, one open table-specific question and one blocking source ambiguity.
- Confirmed transitions include GLE removal from the reserved set in 4.3, PSL/PSO/PSQ and Number=P addition in 4.4, SVLEN cardinality change, SVTYPE deprecation, and VCFv4.5 additions for local alleles, base modifications, FORMAT LEN and END deprecation.

The next cross-version implementation gate is to complete semantic/atomic reconciliation of every VCFv4.1–4.4 source row and structural-variant rule, then map each applicable source rule to a production symbol and an executed version-specific test.

## 4. Exact verification evidence and limitation

- Full SIRALOOM CI passed on the historical exact commit d69d351b44f631f82ae754049063820efdd9a159. This is not evidence for the implementation baseline reviewed above.
- CI on bde6e63957b39a5f8167ea30d3d852aa35d2a4c1 failed with three backend test failures. Subsequent commits corrected the BND/CIPOS diagnostics and telomeric coordinate handling, and added VCFv4.4 phase-set and Number=M regressions.
- VCF research-ledger schema validation passed on f685a22754431187bcc061933da101610d8f9c87. No full SIRALOOM CI run is associated with the implementation baseline 15feffa75bb8fecaec2f3d53ba7729f420cd4d5e in the retrieved workflow-run records. Therefore, this baseline is not CI-verified.
- The same-record unstranded Number=M negative regression (populated complementary-strand slot must be rejected under the explicit unstranded assay policy) is present in tests/test_vcf45_number_m_conformance.py. It has not yet been executed by GitHub Actions.
- The VCFv4.5 phase-set test helper's undefined version variable was corrected; it now accepts an explicit VCF version (default VCFv4.5). VCFv4.4 PSQ positional and missing-value regressions were added in tests/test_vcf44_phase_set_conformance.py. These new tests have not yet been executed by GitHub Actions.
- The GitHub commit-workflow query returned no pull-request workflow runs or check-runs for the latest inspected branch head 9c39c03ad8920de2844f6155ea32e98b30623273. No backend or conformance result is inferred from the absence of a run or from deployment status.
- Do not infer success from the previous green commit or from schema validation. The final exact commit must have a full successful run of backend tests, VCFv4.5 conformance tests, PostgreSQL integration, frontend tests/build, and container/toolchain checks.

## 5. Release decision

**VCF stage remains incomplete and not laboratory-qualified.** VCFv4.5 implementation has materially advanced, including production validator changes and explicit assay-policy wiring. VCFv4.0 source pinning, VCFv4.1–4.4 semantic reconciliation, complete 226-record requirement traceability, independent review, and full CI on the latest exact commit remain open release gates.

This report is a status/evidence register. It does not convert candidate requirements into approved requirements, and it does not represent the presence of tests as proof that all source requirements are implemented.


**Additional unresolved VCFv4.5/4.4 structural semantics:** the reserved wire definitions for tandem-repeat INFO fields are now enforced, but the nested list-of-list cardinality rules across RN/RUS/RUL/RUC/RB/CIRUC/CIRB/RUB, confidence-interval consistency, repeat-sequence IUPAC constraints, and cross-field consistency are not yet implemented. Phase 1 does not claim repeat-expansion analysis support. These fields must be explicitly rejected/routed as unsupported or fully validated before any clinical use.


**Additional version-specific FORMAT evidence:** VCFv4.3 CN is Number=1, Type=Integer; VCFv4.4 changes CN to Number=1, Type=Float. This transition is now encoded in the reserved FORMAT registry and has a negative declaration-mismatch regression test. VCFv4.1/4.2 GLE remains explicitly unresolved at the Number level: it requires a header declaration rather than inventing a cardinality from prose.
