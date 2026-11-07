# VCF version-by-version conformance status report

**Report date:** 2026-11-07  
**Repository:** SayedaRehmat/SIRALOOM  
**Branch:** research/vcf-conformance-phase-a-20261105  
**Implementation baseline reviewed:** 965be03d56fe2d05c4dca9a9c6837333ca80d4fc  
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

**Implemented:** Strict parser accepts VCFv4.1 and applies shared fixed-record, INFO/FORMAT, GT and cardinality validation. Version-delta research identifies VCFv4.1 GT/GL and structural-variant source sections.

**Tested:** Shared cross-version acceptance and cardinality tests in tests/test_vcf_validation.py exercise VCFv4.1. These are shared tests, not a complete VCFv4.1 conformance suite.

**Unsupported / blocked:** No whole-version conformance claim is supported.

**Unresolved:** Complete reserved-row prose/footnote/cross-reference review, atomic mapping to implementation, version-specific valid/invalid/boundary corpus, and executed-test mapping.

### VCFv4.2

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.2.tex; SHA-256 66dbd167e8fb309708e0956ffbb12808bd338a703fbf034d80d1ead56ae480cc.

**Implemented:** Strict parser accepts VCFv4.2 and applies shared fixed-record, INFO/FORMAT, GT and cardinality validation. The version-delta register records the VCFv4.2-to-4.3 removal of GLE from the reserved set.

**Tested:** Shared cross-version acceptance and cardinality tests in tests/test_vcf_validation.py exercise VCFv4.2. No complete VCFv4.2-specific conformance corpus is evidenced.

**Unsupported / blocked:** No whole-version conformance claim is supported.

**Unresolved:** Full reserved-field semantic reconciliation, GLE version behavior and compatibility tests, implementation mapping, and dedicated executed conformance report.

### VCFv4.3

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.3.tex; SHA-256 332d8b910ac9952bfba04374118f8c4f318ea996d5017599e68f80379fd61cde.

**Implemented:** Strict parser applies the VCFv4.3+ SAM reference-name grammar to CHROM and breakend remote-contig names. Shared record, genotype, structural-variant and breakend validation is present.

**Tested:** tests/test_vcf_validation.py includes VCFv4.3+ contig grammar, external-contig capability and breakend tests. Shared cross-version tests include VCFv4.3.

**Unsupported / blocked:** External assembly contigs are valid syntax but explicitly unsupported by the configured reference-package contract. They must be reported as a capability limitation, not mislabeled as universally invalid VCF syntax.

**Unresolved:** Full source-to-code mapping for VCFv4.3 semantic changes, full reserved INFO/FORMAT reconciliation, and independent/version-specific conformance execution.

### VCFv4.4

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.4.tex; SHA-256 4c88884cf6b016efcec691d5186432a2e0b679396204d14770e89839ef536e1a.

**Implemented:** Parser accepts VCFv4.4. Tests cover VCFv4.4 leading GT phase separator behavior and reject VCFv4.5-only local-allele semantics when presented as VCFv4.4. The source delta register identifies PSL/PSO/PSQ and Number=P as additions in the VCFv4.3-to-4.4 transition.

**Tested:** Shared cross-version tests and targeted VCFv4.4 GT/local-allele boundary tests exist in tests/test_vcf_validation.py.

**Unsupported / blocked:** VCFv4.5-only Number=M base-modification semantics and the VCFv4.5 local-allele model must not be back-applied to VCFv4.4. External assembly contigs remain a reference-package capability limitation for VCFv4.3+.

**Unresolved:** Production cross-record PSO/BND logic is currently gated to VCFv4.5. Since PSL/PSO/PSQ were introduced in VCFv4.4, VCFv4.4 phase-set semantics require their own source reconciliation and implementation/test work; VCFv4.5 behavior is not evidence that VCFv4.4 is complete. Full reserved INFO/FORMAT and SV/breakend semantic reconciliation, dedicated corpus execution, and requirement-level traceability remain pending.

### VCFv4.5

**Source:** Pinned samtools/hts-specs revision 510c107ba89aa13113818c9e4fa3071283cb7f7b; VCFv4.5.tex; SHA-256 37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5.

**Implemented:**
- Reserved FORMAT definitions include M, P, LA, LR and LG cardinality handling, local-allele fields and VCFv4.5 structural-variant fields.
- GT allele values remain global ALT indexes; LAA controls local A/R/G vectors.
- Number=M slot mapping preserves GT allele order and exposes per-value biological slot assignments.
- An explicit analysis-creation field, base_modification_strandedness, is persisted in Analysis.configuration and passed to both VCF validation passes. None means unknown/not asserted; values are never inferred from VCF observations.
- The unstranded policy checks same-record and adjacent-record complementary bases, same sample, contig, modification field, GT copy and phase-set context. Unresolved phase contexts are counted and warned; length-changing alleles are rejected for this coordinate projection.
- PSO is required across every observed occurrence of a sample/phase-set when that phase set contains a recognized symbolic SV or breakpoint-notation allele.
- BND MATEID association is retained per ALT, reciprocal ALT and coordinate checks use CIPOS intervals, unresolved CIPOS is surfaced, and reciprocal PSL/PSO comparison preserves GT chromosome-copy order.
- Single breakends and telomeric remote coordinate zero are included in the validator grammar.
- VCFv4.5 SVTYPE is deprecated; BND records may be represented by breakpoint notation and MATEID without requiring SVTYPE. If SVTYPE is supplied, a conflicting value is rejected.

**Tested:** Targeted suites include tests/test_vcf45_number_m_conformance.py, tests/test_vcf45_base_modification_position_semantics.py, tests/test_vcf45_phase_set_positional_semantics.py, tests/test_vcf45_gt_semantic_conformance.py, tests/test_vcf45_laa_requirements.py, tests/test_vcf45_local_allele_projection_conformance.py, tests/test_vcf45_reserved_sv_format_conformance.py, and tests/test_vcf_assay_policy.py. Shared tests in tests/test_vcf_validation.py cover VCFv4.5 cardinality, local alleles, reference blocks, CIPOS/CIEND and reserved INFO/FORMAT domains. The full backend suite previously passed on d69d351b44f631f82ae754049063820efdd9a159; later PSO/BND, CIPOS, assay-policy and test changes are newer than that successful run.

**Unsupported / bounded behavior:**
- Unstranded Number=M cross-record coordinate projection is restricted to equal-length sequence alleles. Length-changing alleles raise VCF_BASE_MODIFICATION_UNSTRANDED_UNSUPPORTED.
- Heterozygous unphased or phased calls without PS/PSL cannot establish cross-record haplotype identity; those observations remain record-local and are reported with VCF_BASE_MODIFICATION_UNSTRANDED_PHASE_CONTEXT_UNRESOLVED.
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

The next cross-version implementation gate is to reconcile VCFv4.4 phase-set semantics (PSL/PSO/PSQ) independently from VCFv4.5, then map each applicable source row/prose rule to a production symbol and an executed version-specific test.

## 4. Exact verification evidence and limitation

- Full CI and ledger-schema validation passed on exact commit d69d351b44f631f82ae754049063820efdd9a159.
- CI on bde6e63957b39a5f8167ea30d3d852aa35d2a4c1 failed with three test failures. Those failures exposed an invalid test assumption about IMPRECISE on BND, an expected-error-code mismatch for the shared CIPOS validator, and an obsolete test that rejected remote BND coordinate zero.
- The code/tests were corrected after that run. The current implementation baseline 965be03d56fe2d05c4dca9a9c6837333ca80d4fc has no associated GitHub Actions run in the retrieved workflow-run records. Therefore, the current baseline is not CI-verified.
- Do not infer success from the previous green commit. The final exact commit must have a full successful run of backend tests, VCFv4.5 conformance tests, PostgreSQL integration, frontend tests/build, and container/toolchain checks.

## 5. Release decision

**VCF stage remains incomplete and not laboratory-qualified.** VCFv4.5 implementation has materially advanced, including production validator changes and explicit assay-policy wiring. VCFv4.0 source pinning, VCFv4.1–4.4 semantic reconciliation, complete 226-record requirement traceability, independent review, and full CI on the latest exact commit remain open release gates.

This report is a status/evidence register. It does not convert candidate requirements into approved requirements, and it does not represent the presence of tests as proof that all source requirements are implemented.
