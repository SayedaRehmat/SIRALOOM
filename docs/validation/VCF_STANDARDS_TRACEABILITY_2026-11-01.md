# VCF standards traceability and qualification status — 2026-11-01

## 1. Decision and scope

This document records a source-based standards audit of SIRALOOM's VCF intake, validation, reference binding, routing, normalization, and provenance boundary. It is a software-conformance assessment, not a declaration that the VCF stage is clinically validated, accredited, or gap-free.

**Current decision: PARTIALLY CONFORMANT AT THE IMPLEMENTED SOFTWARE BOUNDARY; LABORATORY QUALIFICATION NOT ESTABLISHED.**

The audit is anchored to the HTS specifications repository snapshot at commit [`510c107ba89aa13113818c9e4fa3071283cb7f7b`](https://github.com/samtools/hts-specs/commit/510c107ba89aa13113818c9e4fa3071283cb7f7b), dated 2026-08-11. The current published VCF specification in that repository is VCFv4.5. VCFv4.1–v4.5 have versioned specification documents in HTS-specs. VCFv4.0 is retained as a legacy compatibility input and is checked against the historical 1000 Genomes VCFv4.0 description; it is not a currently maintained HTS-specs version.

The current product's declared analytical scope is **small sequence variants (SNVs/indels)**. It preserves and routes structural variants, breakends, CNVs, mitochondrial variants, repeat-expansion records, and gVCF/reference-confidence records to separate/review artifacts. Routing is not analysis. These classes must not be represented as clinically interpreted by the first product.

### Status vocabulary

- **PASS (software):** an identified implementation and automated test support the stated requirement. This does not establish clinical performance.
- **PARTIAL:** some requirements are implemented, but semantics, versions, caller behavior, or evidence remain incomplete.
- **NOT TESTED:** no current execution evidence was located.
- **BLOCKED:** a required external input, laboratory resource, or authorized live environment is not available in repository evidence.
- **NOT APPLICABLE:** outside the explicitly declared first-product VCF-text/SNV-indel scope; this must remain visible to users and in reports.

## 2. Normative and supporting sources

| Source | Role in this audit | Authority and boundary |
|---|---|---|
| [HTS-specs VCFv4.5](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7b/VCFv4.5.tex) | Normative VCFv4.5 text syntax, fixed fields, metadata, genotype cardinalities, local alleles, base modifications, phase sets, reference blocks, and structural-variant INFO fields | Primary technical specification |
| [HTS-specs VCFv4.4](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7b/VCFv4.4.tex), [VCFv4.3](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7b/VCFv4.3.tex), [VCFv4.2](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7b/VCFv4.2.tex), [VCFv4.1](https://github.com/samtools/hts-specs/blob/510c107ba89aa13113818c9e4fa3071283cb7f7b/VCFv4.1.tex) | Version-specific compatibility baseline | Primary technical specifications; each version must be assessed against its own rules |
| [Historical VCFv4.0 description](https://www.internationalgenome.org/wiki/Analysis/vcf4.0/) | Legacy VCFv4.0 compatibility baseline | Historical description, not a current maintained HTS specification |
| [BCFtools manual — norm](https://samtools.github.io/bcftools/bcftools) | Independent normalizer behavior, reference checking, multiallelic splitting, overlap policy | Tool documentation; installed version is separately pinned and attested |
| [GA4GH VRS v2.0](https://www.ga4gh.org/product/variation-representation-specification-vrs/) | Interoperable computational representation and identifiers for sequence variation | Complementary representation layer; does not replace VCF parsing or reference-aware normalization |
| [GA4GH Refget](https://ga4gh.github.io/refget/) and [Sequence Collections v1.0](https://ga4gh.github.io/refget/seqcols/) | Sequence and reference-collection identity using sequence-derived digests | Recommended interoperability layer; not currently emitted by the reference-package contract |
| [NIST Genome in a Bottle](https://www.nist.gov/programs-projects/genome-bottle) | Truth-set benchmarking and confident-region resources | Analytical benchmark evidence; a benchmark is not clinical interpretation validation |
| [ISO 15189:2022](https://www.iso.org/standard/15189) | Medical-laboratory quality and competence framework | Laboratory management/competence standard; applicability and accreditation scope must be determined by the laboratory and its jurisdiction |

The official BCFtools manual describes `bcftools norm -f` as the reference-aware left-alignment/normalization path, `-c e` as exit-on-REF-mismatch, and `-m` as multiallelic splitting. Its `-c s` mode can swap/fix alleles but does not repair PL or other fields; SIRALOOM deliberately does not use that mode.

## 3. Version and format policy

| Input version/format | SIRALOOM policy | Qualification status |
|---|---|---|
| VCFv4.0 | Legacy text VCF compatibility | PARTIAL: compatibility fixtures exist; no maintained HTS-specs VCFv4.0 document |
| VCFv4.1 | Text VCF | PARTIAL: version acceptance and core intake fixtures; not every optional feature/caller extension qualified |
| VCFv4.2 | Text VCF | PARTIAL: version acceptance and core intake fixtures; not every optional feature/caller extension qualified |
| VCFv4.3 | Text VCF | PARTIAL: version acceptance, core parser/routing/normalization/index fixtures |
| VCFv4.4 | Text VCF | PARTIAL: includes version-specific leading GT phasing syntax; not every optional feature qualified |
| VCFv4.5 | Text VCF | PARTIAL: includes local alleles, reference blocks, base-modification fields, reserved-field definitions, and phase-set rules; remaining feature-specific gaps are listed below |
| BCF binary | Not accepted as a VCF-text upload | NOT APPLICABLE to current upload contract; BCF v2.1/v2.2 support would require a separately specified and tested ingestion contract |
| Unknown/future VCF version | Reject; do not infer compatibility | PASS as a fail-closed policy |

Recognition of a fileformat string does not mean that all caller-specific tags, all optional extensions, or all variant classes have clinical semantics in SIRALOOM.

## 4. Requirement-to-implementation traceability

Evidence paths below refer to the current audit branch unless explicitly stated otherwise. The changes in PR #262 are not merged into `main` at the time of this snapshot.

| Requirement | Normative basis | Implementation/evidence | Status | Residual boundary |
|---|---|---|---|---|
| `##fileformat` is first and unique | VCF §§ meta-information/file format | `backend/app/domain/vcf_validation.py`; strict parser ordering tests | PASS (software) | Only listed versions accepted |
| UTF-8, no BOM, forbidden control characters | VCF character encoding/control-character section | Strict parser rejects BOM and forbidden controls; UTF-8 decoder used | PASS (software) | Caller-specific malformed encoding corpus remains a lab check |
| LF and CRLF; final record line separator | VCF data-line framing | Parser strips CR/LF and requires final record line separator; regression test | PASS (software) | Large/corrupt compressed-stream cases remain operational qualification |
| Fixed 8 columns and optional FORMAT/sample columns | VCF header-line syntax | Exact fixed-column prefix; FORMAT position; sites-only handling; duplicate sample-ID rejection | PASS (software) | Caller-specific sample naming corpus still required |
| Structured header definitions and unique IDs | VCF structured metadata rules | Quoted descriptions, escaped quotes, bracketed META lists, duplicate attributes/IDs, and required IDs for VCFv4.5 structured lines | PASS/PARTIAL | Structured metadata is syntax-checked and preserved; every metadata family is not semantically interpreted |
| CHROM values and contiguous contig blocks | VCFv4.3+ SAM reference-name grammar and VCF fixed fields | Versioned contig-name grammar, `##contig` ID validation, contiguous-block enforcement; reference binding uses exact names first, then the finite deterministic aliases implemented by `FastaReference.resolve_contig`; each non-exact resolution is returned in validation provenance; external assembly contig IDs receive an explicit unsupported-input code | PASS (software; PR #263) | Alias mappings are not assembly conversion; each mapping must remain visible and length/REF/optional MD5 checks apply to the resolved sequence; external assembly contigs are not resolved |
| POS order and telomere sentinels | VCF fixed fields | Monotonic POS per contig; POS=0 and declared N+1 preserved as telomere sentinels | PASS (software) | Authoritative REF span/coordinate bounds depend on the selected reference package, not a self-reported VCF contig length alone |
| ID syntax, within-record uniqueness, and cross-record uniqueness | VCF ID field | Duplicate ID values and reuse across records rejected | PASS (software) | No assertion that a caller's chosen identifier is biologically correct |
| REF alphabet and case | VCF REF field | A/C/G/T/N validation and case canonicalization | PASS (syntax) | Exact REF-to-reference concordance is a separate reference-package check |
| REF concordance and no silent repair | BCFtools `norm` reference-check contract | Reference-aware validation and normalization use exact selected FASTA; `bcftools norm -f ... -c e`; no `-c s` | PASS (software contract) | Actual lab/caller mismatch corpus and GIAB known-answer execution remain untested |
| ALT sequence/symbolic/breakend grammar and case | VCF ALT and breakend sections | Sequence alleles canonicalized only; symbolic IDs and mate contig names retain case; malformed symbolic IDs and breakend whitespace rejected | PASS (software; PR #262) | Full SV/BND clinical semantics are out of scope |
| Duplicate ALT values | Versioned ALT-field rule | Duplicate sequence/breakend/symbolic entries rejected for VCFv4.5; identity comparison is case-aware | PASS for VCFv4.5 implementation in PR #262 | VCFv4.0–4.4 rules are not silently upgraded to the VCFv4.5 prohibition |
| QUAL numeric syntax | VCF Float field | Parsed as numeric and non-negative | PARTIAL | Full caller-specific numeric edge-case corpus remains to be qualified |
| FILTER syntax | VCF FILTER field | Rejects empty/duplicate values, reserved `0`, and PASS combined with failing filters | PASS (software) | FILTER declaration/caller vocabulary interoperability is not a complete semantic QC policy |
| INFO syntax, duplicate keys, percent escapes | VCF INFO field | Key grammar, duplicate keys, delimiters, and percent escapes checked | PASS (software) | Free-form values are retained; no inferred semantics for unknown keys |
| INFO/FORMAT declared cardinality and type | VCF Number/Type definitions | A/R/G and numeric cardinalities; sample Number=G uses GT ploidy or the specification's diploid default when GT is absent; variable-cardinality values still undergo type validation; reserved count and probability domains are checked | PASS (software; latest audit branch) | INFO Number=G without a defined ploidy context remains unresolved; any unresolved cardinality must be explicitly recorded rather than guessed |
| VCFv4.5 reserved INFO/FORMAT definitions | VCFv4.5 reserved INFO and genotype tables | Reserved Number/Type maps cover common INFO/FORMAT tags, local-allele tags, base modifications, and structural INFO tags | PASS/PARTIAL | Reserved-field semantic rules are not all implemented; see SV/phase-set rows |
| VCFv4.4/4.5 leading GT phasing separator | Versioned GT syntax | Version-aware GT parser; VCFv4.3 rejects newer leading separator syntax | PASS (software) | Phasing across records remains a separate evidence model |
| LAA local-allele index and ordering constraints | VCFv4.5 local-allele section | LAA placement, distinct/in-range indices, local-field cardinality, called non-reference GT ALT inclusion, and projection equality for standard/local AD, ADF, ADR, EC, GL, GP, PL and PP pairs | PASS (software; PR #262) | Remaining sample/caller-specific local-field combinations require corpus qualification |
| PSL and PS/PSL constraints | VCFv4.5 phase-set section | PS non-negative; PS and PSL cannot both be populated; PSL values for unphased GT alleles must be missing; PSO/PSQ dependencies and missing placeholders are checked | PARTIAL (software; PR #262) | Cross-record phase-set consistency, global phase-set naming, PSO requirements for structural-variant phase sets, and reciprocal BND phasing are not fully qualified |
| VCFv4.5 base-modification Number=M | VCFv4.5 base-modification section | Number=M cardinality, allele/strand interpretation, ranges, and source-only preservation policy | PASS (software fixture scope) | Not used as rare-disease evidence; real modified-base caller corpus is pending |
| VCFv4.5 gVCF/reference blocks | VCFv4.5 reference-block and LEN rules | Sample-specific LEN, wildcard semantics, overlap behavior, END fallback, LAA and CSI boundary tests | PASS (software fixture scope) | Does not perform reference-confidence joint genotyping |
| SV INFO semantics | VCFv4.5 structural-variant INFO section | Reserved definitions and checks for CIPOS/CIEND intervals and MEINFO/METRANS cardinality | PARTIAL | EVENT/EVENTTYPE graph semantics, all BND pairing/orientation cases, PSO/PSQ interpretation, all SV tags, and clinical SV analysis are not fully implemented |
| Multiallelic splitting and genotype projection | BCFtools norm behavior and VCF genotype rules | `-m -any --multi-overlaps .`; source GT/ALT mapping; no conversion of other ALT alleles to reference; missing/unresolved calls stay unresolved | PASS (software tests) | Caller-specific complex multiallelic corpus and clinical interpretation qualification pending |
| Left normalization and REF check | BCFtools norm | Pinned BCFtools 1.24; `-f <reference.fa> -c e -m -any --multi-overlaps .`; sort and CSI index | PASS (software contract) | No atomization is performed; complex MNV decomposition is not implied |
| BGZF and TBI/CSI index concordance | HTS index ecosystem | Uploaded paired index checked against exact BGZF sequential stream; generated CSI and indexed query checks | PASS (software fixture scope) | Representative production caller-generated files and large WGS indexes require lab qualification |
| Reference package identity | VCF `##contig` MD5 definition, SAM sequence MD5 calculation, internal resource contract | FASTA/FAI SHA-256, contig manifest, package checksum, exact contig policy, build binding; optional VCF contig MD5 is syntax-checked and compared with selected FASTA sequence in bounded chunks | PASS (internal integrity and supplied VCF MD5) | VCF MD5 is a compatibility checksum, not a cryptographic integrity control; GA4GH Refget sequence/sequence-collection digests are not currently emitted |
| VRS variant identifiers | GA4GH VRS v2.0 | Not substituted for VCF normalization; no claim of VRS identifier production | NOT IMPLEMENTED (future interoperability) | Future identity layer must preserve source and normalized VCF identities |
| Immutable source and normalized lineage | Laboratory traceability principle; application contract | Uploaded source SHA-256, source-record mapping, ALT-index mapping, normalized artifact identity, tool/version/command provenance | PASS (software contract) | Actual deployed workflow and lab records must be reviewed |
| Analytical truth-set benchmark | NIST GIAB and GA4GH benchmarking practice | GIAB concordance runner and metric/provenance implementation are merged; no real lab/GIAB run result is claimed | NOT TESTED | Must execute with pinned truth VCF, confident regions, query VCF, reference, hap.py, and discrepancy review |
| ISO 15189 laboratory quality/competence | ISO 15189:2022 | Software provenance and test evidence support parts of a lab quality system | NOT VERIFIED | Full laboratory management system, validation/verification, competence, change control, records, risk management, and accreditation scope are not established by this repository audit |

### Important version-specific correction

VCFv4.5 explicitly states that duplicate ALT values are not allowed. Earlier supported versions do not state that same prohibition in the corresponding ALT-field text. The implementation therefore applies the duplicate-ALT rejection specifically to VCFv4.5 rather than imposing a later-version rule on legacy VCFv4.0–4.4 inputs. Sequence allele case is normalized for identity comparison; symbolic IDs and remote contig identifiers remain case-sensitive.

## 5. Normalization contract and prohibited shortcuts

The production normalization path is reference-aware and uses the selected, integrity-checked FASTA. Its core command contract is:

```bash
bcftools norm --no-version \
  -f <reference.fa> -c e \
  -m -any --multi-overlaps . \
  -Oz -o <normalized.vcf.gz> <routed.vcf>
```

The implementation also records source ALT mapping, sorts normalized output, creates a CSI index, and records the exact installed BCFtools version and command provenance.

The following shortcuts are prohibited:

- No Ensembl REST normalization in place of local reference-aware normalization.
- No `bcftools norm -c s` REF/ALT swapping or repair; a reference mismatch must fail closed.
- No silent GRCh37/GRCh38 substitution.
- No implicit or undocumented contig substitution. Exact identifiers are preferred; only the finite deterministic aliases in `FastaReference.resolve_contig` may be used, and every non-exact mapping must be persisted in the validation result. Unknown or version-mismatched accessions fail closed.
- No conversion of non-selected ALT alleles to reference genotype evidence; `--multi-overlaps .` preserves unresolved projection as missing.
- No claim that left normalization alone establishes clinical equivalence, pathogenicity, or reportability.
- No atomization unless a separate, versioned transformation contract and source-to-child lineage are introduced.

## 6. Reference identity and interoperability

The current package contract validates the exact FASTA bytes, FAI bytes, FAI geometry, contig order/length manifest, build identity, and package checksum. This is an appropriate internal integrity boundary and must remain authoritative for analysis. A VCF contig identifier is first matched exactly; when it is not present, only a deterministic alias already defined by the local reference resolver may be accepted. The alias mapping is emitted as provenance, and the selected FASTA sequence remains authoritative for length, REF, and optional contig-MD5 checks. This is not reference-build conversion or a network lookup.

GA4GH Refget Sequences identifies individual sequences by sequence-derived checksums, and Refget Sequence Collections v1.0 provides a digest for a collection of sequences. SIRALOOM currently stores SHA-256 checksums of the FASTA/FAI files and its own contig-manifest digest; it does not currently emit Refget `SQ.` sequence identifiers or sequence-collection digests. These are complementary interoperability enhancements, not reasons to replace the current exact-file integrity checks.

GA4GH VRS v2.0 is a complementary representation and computed-identifier layer. It must not replace source VCF preservation, reference-aware normalization, or the laboratory's original call identity. A future VRS implementation must preserve reference accession/digest, allele representation, source record, and normalization provenance.

## 7. Analytical qualification plan — evidence still required

The following are not software-only tasks. They require an authorized laboratory environment and actual benchmark/sample artifacts.

1. **Define intended use and accreditation scope.** The laboratory must identify its jurisdiction, accreditation body, assay/caller versions, specimen types, reportable regions, and variant classes. ISO 15189:2022 is a relevant international medical-laboratory quality/competence framework, but applicability and accreditation status are not inferred here. CAP/CLIA or other national requirements must only be applied where legally and operationally relevant.
2. **Build the caller/build matrix.** Each supported cell must identify caller and version, WES/WGS assay, GRCh37/GRCh38 reference package digest, VCF version/features emitted, compression/index form, sample mapping policy, and expected report scope.
3. **Select truth sets by sample and assembly.** NIST lists GIAB small-variant benchmark calls and confident regions for GRCh37 and GRCh38. It also reports HG002 v5.0q as a newer small-variant/SV benchmark (Nov 2025–May 2026 updates), while v4.2.1 remains available for other GIAB samples and is deprecated for HG002 by v5.0q. The exact truth-set release, assembly, confident regions, and variant scope must be frozen in the run manifest; do not mix truth-set versions or assume HG002 v4.2.1 is current.
4. **Run independent concordance.** Execute the merged GIAB/hap.py runner against real query/truth/reference/regions. Retain input SHA-256, reference and tool versions, commands, output metrics, strata, and discrepancy artifacts. Review false positives/negatives and exclusions rather than reporting only a single aggregate F1.
5. **Qualify representative assay/caller combinations.** Use positive/negative and difficult-region corpora, multi-allelic and indel edge cases, sample identity checks, reference mismatch challenges, low-complexity/homopolymer regions, and representative WES/WGS scale.
6. **Qualify operational failure modes.** Test corrupt/truncated uploads, decompression, index mismatch, timeouts, worker termination, provider failure, storage exhaustion, backup/restore, and replay on the lab's actual infrastructure.
7. **Approve release.** A qualified laboratory director/authorized reviewer must approve acceptance criteria, intended use, residual risks, version changes, report wording, and release authorization. Software CI or a GIAB truth-set result alone cannot authorize clinical use.

## 8. Evidence snapshot and release boundary

- Main branch inspected: `9c03133ebe11bc8fab28869f87a85964e2b6e4d0`.
- Existing main CI run: [#41305303496](https://github.com/SayedaRehmat/SIRALOOM/actions/runs/41305303496), previously reported successful with backend, frontend, PostgreSQL/Celery integration, and production-container checks.
- Focused conformance work: [PR #263](https://github.com/SayedaRehmat/SIRALOOM/pull/263), which carries the VCFv4.5 conformance changes from PR #262 plus fixes for the two backend regressions found in PR #262's CI. It remains separate from main until the combined checks pass and is not a release qualification.
- Existing GIAB runner and metric semantics corrections are merged in PRs #260 and #261. No real GIAB result is asserted by those code changes.
- The release gate remains [issue #171](https://github.com/SayedaRehmat/SIRALOOM/issues/171). Its controlled deployed end-to-end workflow, recovery, scientific benchmark, and deployment/security evidence are not replaced by this parser audit.

**Release decision: NOT CLINICALLY QUALIFIED.** The repository contains substantial VCF software-conformance and recovery work, but this audit does not establish that every optional feature of every VCF version/caller is supported, that all standards clauses have been met, that a laboratory's complete assay is analytically validated, or that the system is accredited. Every remaining requirement must stay marked PARTIAL, NOT TESTED, BLOCKED, or NOT APPLICABLE until evidence changes its status.
