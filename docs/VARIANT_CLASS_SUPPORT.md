# Variant-class support matrix (mainline snapshot: 2026-10-09)

## Status semantics

- **Implemented:** the current code path has explicit handling.
- **Unit-tested:** focused automated test evidence exists.
- **Not independently validated:** no suitable truth-set/expert benchmark evidence has been reviewed.
- **Unsupported:** must fail visibly rather than be silently dropped or reported as analyzed.

This matrix describes the repository code at commit `72cf5b703c1d0ce48d18ba2b14a1abb376b3298f`; it is not a clinical validation statement.

| Input class | Intake / validation | Normalization behavior | Current disposition | Remaining qualification |
|---|---|---|---|---|
| SNV | Parser and strict validation | BCFtools reference-aware normalization against qualified FASTA | In intended small-variant scope | Independent truth-set concordance required |
| MNV | Parser/strict validator allow DNA alleles | BCFtools normalization; atomization is not enabled | In intended small-variant scope; preserve MNV representation unless tool policy says otherwise | Golden cases needed for MNV representation and annotation |
| Short insertion/deletion | DNA alleles and REF checks | BCFtools left-normalization, sorting, CSI indexing | In intended small-variant scope | Repeat-context truth fixtures and benchmark concordance required |
| Multiallelic short-variant record | Intake can accept; record profile counts multiallelic ALT | BCFtools `norm -m -any` splits records while reference-checking | Implemented and covered by a basic normalization fixture | Add genotype-bearing FORMAT plus Number=A/R/G INFO/FORMAT fixtures to verify allele-index remapping, phase and cardinality |
| Symbolic ALT (e.g. `<DEL>`, `<DUP>`, `<INS>`) | Can be structurally profiled | Workflow rejects before normalization | Unsupported in Phase 1; must not be reported as normalized/analyzed | Ensure user-visible state and report cannot imply success |
| Breakend ALT | Can be structurally profiled | Workflow rejects with unsupported structural-variant handling | Unsupported in Phase 1 | Paired breakend/SV workflow is out of scope |
| Star ALT (`*`) | Classifier currently groups it with symbolic records | Workflow's symbolic-record guard rejects it | Unsupported in Phase 1 | Confirm exact message and no downstream record creation |
| GVCF reference-confidence blocks / `<NON_REF>` | Header markers are profiled | Workflow rejects GVCF markers before normalization | Unsupported as analysis input; requires appropriate upstream genotyping/joint genotyping | Add direct integration fixture for record/header combinations and error state |
| Phased / multi-sample genotypes | VCF parser accepts sample columns where supported; BCFtools handles normalization semantics | Must preserve GT and FORMAT semantics during splitting | Not fully qualified by the existing basic multiallelic fixture | Add multi-sample phased/unphased/missing genotype golden tests |
| VCF version | Strict validator allowlist is VCFv4.2 and VCFv4.3 | BCFtools has its own parser support | Explicitly limited by current validator | Decide and test whether VCFv4.4/v4.5 should be supported; do not imply latest-spec conformance without tests |
| Malformed records / REF mismatch | Validation/reference checks | Fail closed | Unsupported invalid input | Maintain stable error codes and regression tests |

## Code evidence

- `backend/app/domain/vcf_validation.py`: strict structural and semantic validation, including version allowlist and record profiling.
- `backend/app/domain/vcf_tools.py`: `classify_records` and `normalize_vcf_with_bcftools`; the latter uses `bcftools norm -f REF -c e -m -any`, sorting, and CSI indexing before publishing.
- `backend/app/workflows/variant.py`: explicitly raises `UNSUPPORTED_GVCF_INPUT` for GVCF markers and `UNSUPPORTED_STRUCTURAL_VARIANT` for symbolic/breakend records before normalization.
- `tests/test_vcf_tools.py`: basic reference-aware multiallelic splitting/left-alignment fixture and artifact-preservation tests.
- `tests/test_vcf_validation.py`: malformed record, genotype index and profiling tests.

## Scientific policy

1. Intake acceptance is not proof of normalization, annotation, interpretability or reportability.
2. Unsupported classes must fail visibly with a durable failure/review state.
3. Do not atomize MNVs, remove duplicates, repair REF alleles or otherwise change representation without an approved policy and regression evidence.
4. A tool-level split test is not a complete genotype-remapping validation. Add fixtures for GT, phased GT, INFO Number=A/R/G, FORMAT Number=A/R/G, missing values and multiple samples.
5. A green CI run establishes only that configured tests passed; it does not establish clinical sensitivity, specificity or suitability for patient care.

## Authoritative format references

- [HTS specifications repository](https://github.com/samtools/hts-specs) — current VCF specification family; VCFv4.3 is superseded by v4.4 and v4.5.
- [BCFtools manual](https://samtools.github.io/bcftools/bcftools.html) — authoritative command semantics for `norm`, reference checking, multiallelic splitting and indexing.
- [GA4GH VRS](https://vrs.ga4gh.org/en/stable/) — separate variation representation/identifier layer; do not equate it with BCFtools normalization or a local canonical key.
