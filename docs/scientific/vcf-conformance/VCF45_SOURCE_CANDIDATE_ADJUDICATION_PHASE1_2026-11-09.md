# VCFv4.5 source-candidate semantic adjudication — Phase 1

**Status:** `AUTHOR_ADJUDICATION_PENDING_INDEPENDENT_REVIEW`  
**Scope:** the 50 `POTENTIAL_NORMATIVE_OR_MIXED_OBLIGATION` candidates plus the one `AMBIGUOUS_SCOPE` candidate in the existing VCFv4.5 source-to-ledger gap register.  
**Source:** pinned `VCFv4.5.tex`, hts-specs commit `510c107ba89aa13113818c9e4fa3071283cb7f7b`, Git blob `307950e7eeafc33d524969ff906343f756adb7d7`, SHA-256 `37f13e0d2e8e741ea8505b0342b6e6034637a1f476eeb3af1b8acc25d70246c5`.  
**Canonical ledger snapshot:** `atomic-requirements.v1.json`, Git blob `81d27c5b306f120c45d1d5347b931f8ceaf1f47c`, 226 records.

## Adjudication outcome

| Decision | Candidates |
|---|---:|
| Map to existing canonical requirement(s) | 4 |
| Propose new atomic requirement(s) | 27 |
| Split mixed candidate into separate obligations | 8 |
| Retain recommendation/permission without promoting to MUST | 5 |
| Exclude informative context from normative requirements | 1 |
| Retain for future variant/producer workstream | 6 |
| **Total adjudicated** | **51** |

The adjudication produced **51 atomic requirement proposals**: 43 Phase 1 proposals and 8 future-phase proposals. There are 11 direct canonical mapping edges and 5 related/context-only edges. Related edges are not counted as complete semantic coverage. Candidate L0502 maps only its LAA-presence component to `VCF-REQ-000053`; its ordering rule is separately proposed. Candidate L2027 refines the RN behavior in `VCF-REQ-000091`.

No proposal has been assigned a canonical `VCF-REQ` ID. The canonical 226-record ledger has not been changed. No production code or runtime tests have been changed by this adjudication.

## Modality and interpretation controls

- `MUST` and `MUST NOT` remain mandatory/prohibitive.
- `SHOULD` statements at L0400 and L0401 remain recommendations; they are not turned into hard parser rejection rules.
- VCF recommendations that are BCF requirements at L0129 and L0301 are not promoted into VCF-text requirements. BCF remains a separate scope.
- The recommended optional INFO `Source` and `Version` attributes at L0151 remain optional. If supplied, L0175's quoting and semantic content rules apply.
- The recommendation for a local-allele abstraction API at L0715 is implementation guidance, not a VCF file-conformance rule.
- L0411 is a producer-side reference-sequence conversion obligation. It is retained for upstream producer/reference provenance; SIRALOOM must not silently rewrite an incoming REF allele.
- L0406 is split into the simple-indel anchor rule, the position-1 right-padding exception, and the permitted optional padding behavior for complex alleles.
- L0407 separates symbolic-ALT padding from the special `<*>` reference-confidence convention. The spanning-deletion `*` allele is not conflated with `<*>`.
- L0488 is not treated as fully covered by END deprecation or END-to-LEN fallback. It proposes the independent computed-END consistency rule.
- L0502 preserves the existing LAA-presence and GT-first requirements but adds the separate LAA ordering obligation.
- L1989 preserves the difference between recommended CN field presence and mandatory consistency when those fields are present.
- L2027 is recorded as a refinement of the existing RN rule, not as an unrelated duplicate.

## Candidate-by-candidate decisions

The full source excerpt and three lines of context on either side are preserved in the machine-readable adjudication JSON. This table is an index; it does not replace the exact source context.

| Source line | Candidate | Decision | Direct canonical mapping | Related/context mapping | Proposal(s) | Phase 1 scope | Source excerpt |
|---:|---|---|---|---|---|---|---|
| 81 | `VCFv4.5:L0081` | MAP_EXISTING_REQUIREMENT | VCF-REQ-000114, VCF-REQ-000115, VCF-REQ-000116, VCF-REQ-000117, VCF-REQ-000118, VCF-REQ-000119, VCF-REQ-000120, VCF-REQ-000121 | — | — | CORE_REQUIRED | Some characters have a special meaning when they appear (such as field delimiters '\verb\|;\|' in INFO or '\verb\|:\|' FORMAT fields),  |
| 104 | `VCFv4.5:L0104` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0104-1 | CORE_REQUIRED | File meta-information lines start with ''\verb\|##\|'' and must appear first in the VCF file, before the header line (section~\ref{head |
| 107 | `VCFv4.5:L0107` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0107-1 | CORE_REQUIRED | An \emph{unstructured} meta-information line consists of a~\emph{key} (denoting the type of meta-information recorded) and a~\emph{valu |
| 119 | `VCFv4.5:L0119` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0119-1 | CORE_REQUIRED | All structured lines require an ID which must be unique within their type, i.e., within all the meta-information lines with the same '' |
| 126 | `VCFv4.5:L0126` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0126-1 | CORE_REQUIRED | The values of optional fields must be written as quoted strings, even for numeric values. |
| 129 | `VCFv4.5:L0129` | RECOMMENDATION_OR_PERMISSION_EXCLUDE_NORMATIVE | — | — | — | NOT_APPLICABLE | It is recommended in VCF and required in BCF that the header includes tags describing the reference and contigs backing the data contai |
| 130 | `VCFv4.5:L0130` | INFORMATIVE_EXCLUDE_NORMATIVE | — | — | — | NOT_APPLICABLE | These tags are based on the SQ field from the SAM spec; all tags are optional (see the VCF example above). |
| 133 | `VCFv4.5:L0133` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0133-1 | CORE_REQUIRED | Implementations must not rely on the order of the fields within structured lines and are not required to preserve field ordering. |
| 135 | `VCFv4.5:L0135` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0135-1 | CORE_REQUIRED | Meta-information lines are optional, but if they are present then they must be completely well-formed. |
| 136 | `VCFv4.5:L0136` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0136-1 | CORE_REQUIRED | Other than \verb\|##fileformat\|, they may appear in any order. |
| 151 | `VCFv4.5:L0151` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0151-1, VCF45-PROP-0151-2 | CORE_REQUIRED | INFO meta-information lines are structured lines with required fields ID, Number, Type, and Description, and recommended optional field |
| 159 | `VCFv4.5:L0159` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0159-1 | CORE_REQUIRED | For example, if the INFO field contains a single number, then this value must be $1$; if the INFO field describes a pair of numbers, th |
| 164 | `VCFv4.5:L0164` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0164-1 | CORE_REQUIRED |  The values must be in the same order as listed in the ALT column (described in section \ref{data-lines}). |
| 166 | `VCFv4.5:L0166` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0166-1 | CORE_REQUIRED |  The order of the values must be the reference allele first, then the alternate alleles as listed in the ALT column. |
| 168 | `VCFv4.5:L0168` | MAP_EXISTING_REQUIREMENT | VCF-REQ-000136 | — | — | CORE_REQUIRED |  The values must be in the same order as prescribed in section \ref{genotype-fields:genotype-ordering} (see \textsc{Genotype Ordering}) |
| 172 | `VCFv4.5:L0172` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0172-1 | CORE_REQUIRED | The 'Flag' type indicates that the INFO field does not contain a Value entry, and hence the Number must be $0$ in this case. |
| 173 | `VCFv4.5:L0173` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0173-1 | CORE_REQUIRED | The Description value must be surrounded by double-quotes. |
| 174 | `VCFv4.5:L0174` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0174-1 | CORE_REQUIRED | Double-quote character must be escaped with backslash $\backslash$ and backslash as $\backslash\backslash$. |
| 175 | `VCFv4.5:L0175` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0175-1 | CONDITIONAL_INPUT | Source and Version values likewise must be surrounded by double-quotes and specify the annotation source (case-insensitive, e.g.\ \verb |
| 178 | `VCFv4.5:L0178` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0178-1 | CORE_REQUIRED | FILTER meta-information lines are structured lines with required fields ID and Description that define the possible content of the FILT |
| 185 | `VCFv4.5:L0185` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0185-1 | CORE_REQUIRED | FORMAT meta-information lines are structured lines with required fields ID, Number, Type, and Description that define the possible cont |
| 258 | `VCFv4.5:L0258` | FUTURE_PHASE_REQUIREMENT | — | — | VCF45-PROP-0258-1 | OUT_OF_SCOPE_EXPLICIT_REJECTION | ID values are case sensitive strings and must not contain whitespace, commas or angle brackets (See \ref{fixed-fields}.\ref{fixed-field |
| 259 | `VCFv4.5:L0259` | FUTURE_PHASE_REQUIREMENT | — | — | VCF45-PROP-0259-1 | OUT_OF_SCOPE_EXPLICIT_REJECTION | The first level type must be one of the following: |
| 265 | `VCFv4.5:L0265` | FUTURE_PHASE_REQUIREMENT | — | — | VCF45-PROP-0259-1 | OUT_OF_SCOPE_EXPLICIT_REJECTION |  \item CNV Region of uniform copy number (may be deletion, duplication or copy number neutral) |
| 301 | `VCFv4.5:L0301` | RECOMMENDATION_OR_PERMISSION_EXCLUDE_NORMATIVE | — | — | — | NOT_APPLICABLE | It is recommended for VCF, and required for BCF, that the header includes tags describing the contigs referred to in the file. |
| 302 | `VCFv4.5:L0302` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0302-1, VCF45-PROP-0302-2 | CONDITIONAL_INPUT | The structured \texttt{contig} field must include the ID attribute and can include additional optional attributes with |
| 322 | `VCFv4.5:L0322` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0322-1 | CORE_REQUIRED | they may contain any printable ASCII characters in the range \verb\|[!-~]\| apart from '{\tt\verb\|\\|\,,\,"''\,()\,[]\,\verb\|{}\|\,<> |
| 329 | `VCFv4.5:L0329` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0329-1 | CORE_REQUIRED | The contig names must not use a reserved symbolic allele name. |
| 391 | `VCFv4.5:L0391` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0391-1 | CORE_REQUIRED |  All entries for a specific CHROM must form a contiguous block within the VCF file. |
| 392 | `VCFv4.5:L0392` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0392-1 | CORE_REQUIRED |  (String, no whitespace permitted, Required). |
| 397 | `VCFv4.5:L0397` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0397-1 | CORE_REQUIRED |  (Integer, Required) |
| 400 | `VCFv4.5:L0400` | RECOMMENDATION_OR_PERMISSION_EXCLUDE_NORMATIVE | — | — | — | CONDITIONAL_INPUT |  No identifier should be present in more than one data record. |
| 401 | `VCFv4.5:L0401` | RECOMMENDATION_OR_PERMISSION_EXCLUDE_NORMATIVE | — | — | — | CONDITIONAL_INPUT |  If there is no identifier available, then the MISSING value should be used. |
| 403 | `VCFv4.5:L0403` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0403-1 | CORE_REQUIRED |  \item REF --- reference base(s): Each base must be one of A,C,G,T,N (case insensitive). |
| 406 | `VCFv4.5:L0406` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0406-1, VCF45-PROP-0406-2, VCF45-PROP-0406-3 | CORE_REQUIRED |  For simple insertions and deletions in which either the REF or one of the ALT alleles would otherwise be null/empty, the REF and ALT S |
| 407 | `VCFv4.5:L0407` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0407-1, VCF45-PROP-0407-2 | CONDITIONAL_INPUT |  If any of the ALT alleles is a symbolic allele (an angle-bracketed ID String ''$<$ID$>$'') then the padding base is required and POS d |
| 411 | `VCFv4.5:L0411` | FUTURE_PHASE_REQUIREMENT | — | — | VCF45-PROP-0411-1 | NOT_APPLICABLE |  If the reference sequence contains IUPAC ambiguity codes not allowed by this specification (such as R = A/G), the ambiguous reference  |
| 416 | `VCFv4.5:L0416` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0416-1, VCF45-PROP-0416-2, VCF45-PROP-0416-3 | CORE_REQUIRED |  Each allele in this list must be one of: a non-empty String of bases (A,C,G,T,N; case insensitive); the '*' symbol (allele missing due |
| 417 | `VCFv4.5:L0417` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0417-1 | CORE_REQUIRED |  If there are no alternative alleles, then the MISSING value must be used. |
| 422 | `VCFv4.5:L0422` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0422-1 | CORE_REQUIRED |  If unknown, the MISSING value must be specified. (Float) |
| 425 | `VCFv4.5:L0425` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0425-1 | CORE_REQUIRED |  '0' is reserved and must not be used as a filter String. |
| 426 | `VCFv4.5:L0426` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0426-1 | CORE_REQUIRED |  If filters have not been applied, then this field must be set to the MISSING value. |
| 429 | `VCFv4.5:L0429` | PROPOSE_NEW_ATOMIC_REQUIREMENT | — | — | VCF45-PROP-0429-1 | CORE_REQUIRED |  Each subfield consists of a short \emph{key} with optional \emph{values} in the format: key[=value[,\,\ldots,value]]. |
| 433 | `VCFv4.5:L0433` | SPLIT_MIXED_CANDIDATE | — | — | VCF45-PROP-0433-1, VCF45-PROP-0433-2 | CORE_REQUIRED |  INFO keys must match the regular expression \texttt{\^{}([A-Za-z\_][0-9A-Za-z\_.]*\|1000G)\$}, please note that ''1000G'' is allowed a |
| 488 | `VCFv4.5:L0488` | SPLIT_MIXED_CANDIDATE | — | VCF-REQ-000106, VCF-REQ-000129 | VCF45-PROP-0488-1 | CONDITIONAL_INPUT | This is a computed field that, when present, must be set to the maximum end reference position (1-based) of: |
| 502 | `VCFv4.5:L0502` | MAP_EXISTING_REQUIREMENT | VCF-REQ-000053 | VCF-REQ-000019 | VCF45-PROP-0502-1 | CONDITIONAL_INPUT | If any local-allele field is present, LAA must also be present and precede all fields other than GT. |
| 715 | `VCFv4.5:L0715` | RECOMMENDATION_OR_PERMISSION_EXCLUDE_NORMATIVE | — | — | — | NOT_APPLICABLE |  It is recommended that VCF libraries provide an API in which local allele encoding can be abstracted away from the API consumer and va |
| 726 | `VCFv4.5:L0726` | FUTURE_PHASE_REQUIREMENT | — | VCF-REQ-000075 | VCF45-PROP-0726-1 | OUT_OF_SCOPE_EXPLICIT_REJECTION |  Values must be between 0 and 1 and indicate how prevalent the modified base is in the sample. |
| 1989 | `VCFv4.5:L1989` | SPLIT_MIXED_CANDIDATE | — | VCF-REQ-000096 | VCF45-PROP-1989-1, VCF45-PROP-1989-2 | OUT_OF_SCOPE_EXPLICIT_REJECTION |  \item The INFO and FORMAT CN fields should be present for $<$CNV:TR$>$ records (as they are $<$CNV$>$ records) and, when present, must |
| 1996 | `VCFv4.5:L1996` | FUTURE_PHASE_REQUIREMENT | — | — | VCF45-PROP-1996-1 | OUT_OF_SCOPE_EXPLICIT_REJECTION |  \item RUS or RUL must be specified for each $<$CNV:TR$>$. |
| 2027 | `VCFv4.5:L2027` | MAP_EXISTING_REQUIREMENT | VCF-REQ-000091 | — | VCF45-PROP-2027-REFINE-000091 | OUT_OF_SCOPE_EXPLICIT_REJECTION |  \item RN was omitted as it is only required if at least one $<$CNV:TR$>$ allele has RN greater than 1. |

## Future workstream retention

The following source semantics are retained rather than discarded or misrepresented as Phase 1 small-variant support:

- **Structural variants:** L0258 symbolic SV identifier lexical rules and L0259 enumerated top-level type domain.
- **CNV:** L0265 CNV type definition and L1989 CN field semantics.
- **Tandem repeats:** L1996 RUS/RUL requirement and L2027 RN conditional requirement/refinement.
- **Base modifications:** L0726 Number=M value range; related to, but not fully covered by, `VCF-REQ-000075`.
- **Upstream VCF producer/reference provenance:** L0411 IUPAC ambiguity conversion. This is not permission for a consuming pipeline to mutate incoming REF.
- **gVCF/reference-confidence handling:** L0407 and L0416 preserve the distinct `<*>` construct and its routing semantics.
- **Existing PSO/BND/derivative-chromosome work:** preserved by the profile PR; no PSO/BND code or test files were changed by this adjudication.

## What this adjudication does not establish

1. It is an author-level semantic review, not an independent standards-owner review.
2. VCFv4.1–4.4 source applicability has not yet been reconciled for each candidate.
3. Proposed atomic requirements are not yet in the canonical ledger and have no implementation/test evidence.
4. The remaining 37 recommendation/permission/implementation-guidance candidates and 6 informative candidates in the source-gap register still require their own disposition pass.
5. VCFv4.0 historical source bytes and immutable provenance remain unresolved.
6. No production parser behavior, gVCF runtime behavior, laboratory qualification or release readiness is claimed.

## Reproducibility

The accompanying validator checks:
- JSON Schema Draft 2020-12 validity;
- exact identity of the pinned VCFv4.5 source bytes (Git blob and SHA-256);
- one-to-one coverage of the 50+1 candidate IDs from the source-gap register;
- exact source excerpt and surrounding-context equality against the pinned source;
- existence of every referenced canonical requirement ID;
- uniqueness and count consistency of proposal IDs;
- separation of direct mappings from related/context-only mappings;
- unchanged canonical ledger, production code and PSO/BND preservation controls.

The validator establishes artifact integrity and traceability only. It does not adjudicate scientific correctness or replace independent review.
