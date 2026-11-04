# VCF version requirement-to-code-to-test traceability matrix

**Status: PARTIAL — NOT A CONFORMANCE DECLARATION**

This matrix is the implementation audit baseline for VCFv4.0–4.5. It separates
version recognition, finite fixture execution, normative requirement coverage,
public-file interoperability, and clinical laboratory validation. A PASS in
one column never implies PASS in another.

## Specification authority and version policy

| Version | Authority | SIRALOOM policy | Current acceptance status |
|---|---|---|---|
| VCFv4.0 | Historical VCF 4.0 compatibility material; not listed in the current HTS specifications index | Legacy compatibility only; no claim of current normative conformance | PARTIAL / legacy smoke |
| VCFv4.1 | GA4GH Large Scale Genomics HTS specification | Version-specific normative target | PARTIAL |
| VCFv4.2 | GA4GH Large Scale Genomics HTS specification | Version-specific normative target | PARTIAL |
| VCFv4.3 | GA4GH Large Scale Genomics HTS specification | Version-specific normative target | PARTIAL |
| VCFv4.4 | GA4GH Large Scale Genomics HTS specification | Version-specific normative target | PARTIAL |
| VCFv4.5 | GA4GH Large Scale Genomics HTS specification; current canonical VCF text | Version-specific normative target | PARTIAL |

The authoritative HTS index lists VCFv4.1–4.5. It describes VCFv4.5 as the
canonical specification and the earlier documents as predecessors. VCFv4.0
therefore remains a deliberately narrower compatibility target.

## Requirement-to-implementation matrix

Status meanings:

- **IMPLEMENTED / TESTED:** a focused implementation and regression test exist.
  This proves only the named behavior, not the entire specification section.
- **PARTIAL:** some implementation/tests exist but clause coverage, boundary
  behavior, or independent evidence is incomplete.
- **UNSUPPORTED / BLOCKED:** the input must not silently proceed through the native clinical path.
- **NOT ASSESSED:** no defensible evidence has yet been established.

| Requirement ID | Requirement family / normative section | Version applicability | Existing implementation | Existing tests / evidence | Audit status |
|---|---|---|---|---|---|
| VCF-HDR-001 | Fileformat present, first, unique, recognized exact version | 4.0–4.5 | vcf_validation.py read_vcf_fileformat / validate_vcf_strict | fileformat tests; versioned fixture suite | PARTIAL |
| VCF-HDR-002 | Meta-information precedes #CHROM; no metadata after header | 4.0–4.5 | validate_vcf_strict header state machine | metadata-after-header test | IMPLEMENTED / TESTED |
| VCF-HDR-003 | Structured metadata grammar, quoting, escaping, unique attributes and IDs | 4.1–4.5; legacy subset 4.0 | _structured_header_id, _parse_field_definition | duplicate/invalid structured-header tests | PARTIAL |
| VCF-HDR-004 | INFO/FORMAT declarations require ID, Number, Type, Description and valid domains | 4.1–4.5 | _parse_field_definition, reserved VCFv4.5 definitions | header definition and reserved-field tests | PARTIAL |
| VCF-HDR-005 | FILTER, ALT, contig, SAMPLE, PEDIGREE and other metadata declarations | 4.1–4.5 | structured-header parsing and feature checks | limited structured-header tests | PARTIAL |
| VCF-HDR-006 | Eight fixed columns; FORMAT and sample columns in valid positions | 4.0–4.5 | validate_vcf_strict | header/sample column tests | IMPLEMENTED / TESTED |
| VCF-HDR-007 | Sample IDs unique and record sample-column count consistent | 4.0–4.5 | validate_vcf_strict | duplicate sample and record column-count tests | PARTIAL |
| VCF-ENC-001 | UTF-8, no BOM, forbidden control characters | Explicit in 4.3+; compatibility behavior earlier | _open, FORBIDDEN_CONTROL_RE | BOM/control-character tests | PARTIAL |
| VCF-ENC-002 | LF and CRLF separators; reject bare CR and embedded CR | Maintained specification line-ending requirements | _open and strict parser line checks | new CRLF/bare-CR/embedded-CR tests | IMPLEMENTED / TESTED for line-ending behavior |
| VCF-REC-001 | Record column count, tab delimitation and nonempty required fields | 4.0–4.5 | _validate_record, validate_vcf_strict | malformed-record and column-count tests | PARTIAL |
| VCF-REC-002 | CHROM syntax and version-specific reference-name grammar | 4.0–4.5; SAM name grammar from 4.3 | _validate_record, VCF_CONTIG_NAME_RE | VCFv4.3+ CHROM/contig/breakend tests | PARTIAL |
| VCF-REC-003 | POS integer, coordinate semantics, sort order and contig blocks | 4.0–4.5 | _validate_record and parser ordering state | position-order and noncontiguous-contig tests | PARTIAL |
| VCF-REC-004 | ID syntax, missing value, list semantics and uniqueness | 4.0–4.5 | _validate_record and record_ids_seen | duplicate-ID and punctuation tests | PARTIAL |
| VCF-REC-005 | REF sequence alphabet and ALT sequence/symbolic/breakend syntax | 4.0–4.5 | _validate_record, _validate_structural_alt | malformed ALT, symbolic, breakend and REF tests | PARTIAL |
| VCF-REC-006 | QUAL numeric syntax and missing value semantics | 4.0–4.5 | _validate_record | selected malformed-record cases | PARTIAL |
| VCF-REC-007 | FILTER PASS, missing and declared filter identifiers | 4.0–4.5 | _validate_record | limited FILTER fixtures | PARTIAL |
| VCF-INF-001 | INFO key/value/flag syntax, duplicate keys and missing values | 4.0–4.5 | _validate_info, _info_values | INFO duplicate and malformed-value tests | PARTIAL |
| VCF-INF-002 | INFO Type and Number cardinality A/R/G/fixed/variable | 4.0–4.5 | _validate_declared_value, _expected_cardinality | A/R/G/type/cardinality tests | PARTIAL |
| VCF-INF-003 | Reserved INFO fields and structural-variant semantics | Version-specific | reserved VCFv4.5 definitions and _validate_vcf45_structural_info | reserved INFO/SV interval tests | PARTIAL |
| VCF-FMT-001 | FORMAT key syntax, uniqueness, sample value count and missingness | 4.0–4.5 | _validate_record, _validate_declared_value | FORMAT key/value tests | PARTIAL |
| VCF-FMT-002 | GT syntax, allele index bounds, separators, phase and ploidy | 4.0–4.5; leading separator v4.4+ | _gt_allele_tokens and genotype validation | ploidy, allele-index and leading-separator tests | PARTIAL |
| VCF-FMT-003 | Number=A/R/G cardinality, sample ploidy and genotype ordering | 4.0–4.5 | _expected_cardinality and genotype-order helpers | haploid/diploid/polyploid and multiallelic tests | PARTIAL |
| VCF-FMT-004 | FORMAT reserved definitions and value domains | 4.0–4.5; expanded in 4.5 | reserved VCFv4.5 definitions and _validate_declared_value | reserved FORMAT/type/domain tests | PARTIAL |
| VCF-ALT-001 | Symbolic ALT declarations, END/SVLEN span and reference padding | 4.0–4.5 | _validate_structural_alt and span helpers | symbolic deletion and span tests | PARTIAL |
| VCF-BND-001 | Four breakend orientations, remote loci and MATEID linkage | 4.1–4.5 | breakend parser and deferred mate-link validation | orientation, reciprocity and mismatch tests | PARTIAL |
| VCF-BND-002 | MATEID version-specific cardinality and ordering | 4.1–4.3 Number=.; 4.4–4.5 Number=A | validate_vcf_strict version branch | legacy unordered and v4.4+ ALT-alignment tests | PARTIAL |
| VCF-GVCF-001 | Unspecified allele and reference-only block representation | 4.3+; producer dialect separately identified | VCFv4.5 block/span helpers | <*> / <NON_REF> / END / LEN tests | PARTIAL |
| VCF-GVCF-002 | GATK <NON_REF> plus END producer dialect | Producer interoperability, not general normative feature | explicit compatibility path | GATK interoperability fixtures | PARTIAL; not general gVCF sign-out support |
| VCF-43-001 | VCFv4.3+ SAM reference-name grammar | 4.3–4.5 | VCF_CONTIG_NAME_RE and version branches | CHROM/contig/breakend grammar tests | IMPLEMENTED / TESTED for tested cases |
| VCF-43-002 | External assembly contig references | 4.3–4.5 | explicitly rejected by native validator | external assembly unsupported test | UNSUPPORTED / BLOCKED |
| VCF-44-001 | Leading phasing separator in GT | 4.4–4.5 | _gt_allele_tokens | v4.3 rejection and v4.4/v4.5 acceptance tests | IMPLEMENTED / TESTED for tested cases |
| VCF-44-002 | MATEID per-ALT mapping and placeholders | 4.4–4.5 | validate_vcf_strict | mixed/multiallelic MATEID tests | PARTIAL |
| VCF-45-001 | Local-allele LA/LAA/LAD/LADF/LADR/LEC/LGL/LGP/LPL/LPP | 4.5 | _expected_cardinality and local-field equivalence | local-allele cardinality/projection tests | PARTIAL |
| VCF-45-002 | Number=M base-modification fields and value domains | 4.5 | _base_modification_field_kind, _validate_declared_value | base-modification tests | PARTIAL |
| VCF-45-003 | Per-sample <*> reference blocks and FORMAT/LEN | 4.5 | reference-block state machine | per-sample LEN/span/overlap tests | PARTIAL |
| VCF-45-004 | Reserved INFO/FORMAT definitions and phase-set dependent fields | 4.5 | reserved definitions and phase validation | reserved field and PS/PSL/PSO/PSQ tests | PARTIAL |
| VCF-45-005 | CILEN, CIPOS, CIEND, MEINFO, METRANS semantics | 4.5 | _validate_vcf45_structural_info | confidence interval and MEINFO/METRANS tests | PARTIAL |
| VCF-REF-001 | Contig lengths and MD5 reconciliation | 4.0–4.5 where declared | declared_vcf_contig_lengths / declared_vcf_contig_md5s | contig length/MD5 tests | PARTIAL |
| VCF-REF-002 | Selected-reference REF validation and assembly identity | SIRALOOM workflow | validate_vcf_reference_alleles and reference package checks | REF mismatch and GIAB chromosome-1 tests | PARTIAL |
| VCF-IO-001 | Plain VCF, gzip, BGZF, truncation and block integrity | Compression profile independent of VCF version | _verify_bgzf, _open, ingestion validation | BGZF/gzip and GIAB tests | PARTIAL |
| VCF-IO-002 | TBI/CSI applicability, identity, freshness and query concordance | Index specification / SIRALOOM intake | ingestion index validation | GIAB index and index tests | PARTIAL |
| VCF-SCOPE-001 | SNV/small-INDEL eligibility and unsupported CNV/SV/MT/repeat classes | SIRALOOM product scope | route_vcf_records and specialized-review routing | unsupported VCF worker routing tests | PARTIAL; reportability bypass requires end-to-end proof |
| VCF-OPS-001 | Immutable source, record accounting, safe errors, atomic output, replay and provenance | SIRALOOM operations contract | ingestion, worker, artifact and audit services | existing unit/integration tests | PARTIAL |

## Version-specific behavior gates

| Behavior | 4.0 | 4.1 | 4.2 | 4.3 | 4.4 | 4.5 |
|---|---|---|---|---|---|---|
| Normative HTS VCF document listed | No | Yes | Yes | Yes | Yes | Yes |
| Legacy parser compatibility | Yes | Yes | Yes | Yes | Yes | Yes |
| Version-aware native validation | Limited | Yes | Yes | Yes | Yes | Yes |
| VCFv4.3+ SAM reference-name grammar | N/A | N/A | N/A | Yes | Yes | Yes |
| GATK <NON_REF> producer fixture in current corpus | No | No | No | Yes | No | No |
| Leading GT phasing separator | No | No | No | No | Yes | Yes |
| Local allele LA/LAA family | No | No | No | No | No | Yes |
| Number=M base modification fields | No | No | No | No | No | Yes |
| Per-sample <*> block FORMAT/LEN | No | No | No | No | No | Yes |
| MATEID per-ALT cardinality | No | No | No | No | Yes | Yes |

N/A means not applicable, not tested support.

## Existing evidence baseline

The current synthetic corpus contains VCFv4.0=1 legacy smoke, v4.1=16,
v4.2=15, v4.3=20, v4.4=19 and v4.5=38 cases. The conformance runner
deliberately reports v4.1–v4.5 as PARTIAL with no fully covered normative
sections. The 680 extracted source lines are candidate lines, not reviewed
atomic clauses. This matrix does not promote them to complete conformance.

## Required closure work

1. Human-review every normative candidate and relevant table/definition; split compound requirements into atomic clauses with stable IDs.
2. Record exact version applicability and normative strength; distinguish MUST/SHALL, SHOULD and MAY.
3. Map every clause to production function/line, positive test, negative test, boundary test and retained evidence.
4. Execute immutable public VCF inputs for every declared version.
5. Resolve parser discrepancies without weakening version-specific checks.
6. Keep unsupported features blocked and visible.
7. Re-run regression and preserve reports against the exact PR commit.

**Acceptance rule:** no VCF version may be labelled fully conformant while any
applicable normative clause remains unmapped, untested, unresolved or without
reviewable evidence. VCFv4.0 may only be described as legacy-compatible unless
an authoritative historical specification basis and complete review are established.


## Additional normative header grammar findings (2026-11-04)

The official VCFv4.5 text states that unstructured metadata values must be
non-empty and must not begin with an angle bracket; structured metadata must
be well formed, and custom structured lines require an ID. It also requires
FILTER and ALT declarations to contain ID and Description, and Source/Version
optional attributes to be quoted strings.

The validator was tightened accordingly:
- every structured metadata line is parsed for every supported version, not
  only selected known header keys or v4.5;
- generic structured metadata requires ID, with the existing VCFv4.5 PEDIGREE
  exception preserved;
- FILTER and ALT declarations require a quoted Description;
- INFO/FORMAT Source and Version optional attributes must be quoted;
- unstructured metadata requires a non-empty key and value.

Regression cases cover each behavior across VCFv4.1–4.5 where applicable.
These are implementation changes awaiting the queued CI run; they do not
establish complete normative conformance.


## Escaped structured-header values

The parser's structured-header scanners now recognize only the VCF-defined
escaped quote and escaped backslash sequences inside quoted values. Unsupported
escape sequences are rejected. Regression coverage includes INFO descriptions
and custom structured metadata. This closes a parser-state defect where an
escaped quote could previously be interpreted as the end of a quoted value.
The tests are awaiting execution in the queued CI verification.


## Evidence-runner robustness

The public corpus runner now records BCFtools timeout and process-start failures
per source instead of aborting before the remaining version inputs are tested.
The evidence artifact upload is non-fatal when an earlier CI step prevents the
runner from creating its output directory. The report also asserts exactly one
source per declared version.


## Public-source route-disposition assertions

The immutable public corpus now declares the expected SIRALOOM route category
for each input. The 4.0–4.3 small-variant examples must produce sequence
records; the official 4.4 SV example must produce specialized structural
records; and the HPRC 4.5 KIV-2 file must produce repeat-expansion records.
Each source must also reconcile every input record to exactly one exclusive
routing disposition. This proves the parser does not silently discard these
out-of-scope classes; it does not qualify their downstream clinical analysis.


## User-visible compatibility status

The compatibility registry no longer labels VCFv4.1–4.5 simply SUPPORTED.
It now emits PARTIAL_FEATURE_QUALIFICATION and VERSION_AWARE_PARTIAL. The
version is recognized and a tested feature subset is parsed; this does not
mean every normative clause or optional feature is implemented. VCFv4.0
continues to emit LEGACY_COMPATIBILITY_ONLY / LEGACY_PARSER_SMOKE_ONLY.


## PEDIGREE structured-header correction

The official VCFv4.3–4.5 text requires an ID for structured metadata lines,
including PEDIGREE. An earlier regression incorrectly allowed a VCFv4.5
PEDIGREE line without ID. That acceptance has been removed. Maintained-version
tests now reject missing PEDIGREE IDs and accept a valid unique ID. The
VCFv4.0 legacy profile retains its narrower historical parser behavior.


## Version-specific structured-header rule correction

The normative source review identified a critical version distinction:
VCFv4.1/v4.2 PEDIGREE lines use relationship attributes such as Derived and
Original and do not carry the later generic ID field. VCFv4.3 introduced the
rule that all structured metadata lines require a unique ID, including
PEDIGREE. The parser and tests now preserve the v4.1/v4.2 legacy form while
requiring ID for PEDIGREE and custom structured metadata in v4.3–v4.5.
Source/Version optional-attribute quoting is likewise applied to v4.3–v4.5,
where those attributes are standardized, rather than imposing that rule on
older versions.


## FILTER and ALT identifier constraints

The strict validator now rejects reserved/invalid FILTER IDs (including the
reserved ID 0), whitespace and delimiter characters in FILTER IDs, and
whitespace/comma/angle-bracket characters in symbolic ALT IDs. Record FILTER
values also reject commas, which cannot be represented as valid declared
filter identifiers. Version-specific test cases cover these constraints.


## INFO/FORMAT identifier grammar is versioned

VCFv4.3 introduced explicit INFO and FORMAT tag-name regular expressions,
with the legacy INFO tag 1000G exception. VCFv4.1/v4.2 do not state that same
regular expression. The validator now applies the strict regex only to
VCFv4.3–4.5 and preserves the older token grammar for VCFv4.0–4.2. Tests cover
a legacy hyphenated INFO/FORMAT identifier and rejection of that identifier
under VCFv4.3–4.5.


The versioned INFO/FORMAT identifier regression includes both header
declarations and record-level keys. VCFv4.3–4.5 reject nonconforming INFO and
FORMAT tag names; VCFv4.1/v4.2 retain their earlier token grammar.


The VCFv4.3+ generic structured ID rule is now applied to every structured
header type, including custom metadata, SAMPLE, PEDIGREE and META identifiers:
IDs are case-sensitive strings and cannot contain whitespace, commas or angle
brackets. INFO/FORMAT, FILTER, ALT and contig types retain their stricter
type-specific constraints.


## Integer numeric range correction

The VCF Integer type uses a signed 32-bit representation, but the eight
lowest signed values (-2^31 through -2^31+7) are reserved by the binary
encoding and are disallowed in both VCF and BCF. The validator therefore
accepts [-2^31+8, 2^31-1] and rejects values outside that interval. Both
boundaries and adjacent out-of-range values have regression cases.


## Simple insertion/deletion padding

The VCF fixed-field rules require a padding base for simple insertions and
deletions: the preceding base is used except at contig position 1, where the
following base is used. The validator now detects simple prefix/suffix indel
representations and rejects a right-padded representation away from position
1 or a left-padded representation at position 1. Complex replacements that
retain bases on both sides are not incorrectly treated as simple indels.
Tests cover valid and invalid examples at both coordinate boundaries.


## Integer range source correction

A direct review of the official VCFv4.3 data-type clause shows that the eight
lowest signed 32-bit integer values (-2^31 through -2^31+7) are explicitly
disallowed in both VCF and BCF because they cannot be represented in the
binary encoding. The earlier implementation's lower bound was therefore
correct. The attempted full signed-range change has been reverted; boundary
tests now accept -2147483640 and reject -2147483641, while retaining the
upper signed-32-bit boundary.


## Fixed-field lexical validation

The VCFv4.3+ Float grammar applies to QUAL as well as declared INFO/FORMAT
Float fields. QUAL now rejects nonconforming tokens that Python's float()
would otherwise accept, while accepting decimal/exponent, INF/INFINITY and
NAN forms specified by HTS. POS is now lexically constrained to unsigned
decimal digits before integer conversion, preventing permissive acceptance of
plus signs, decimal points or nonnumeric suffixes.
