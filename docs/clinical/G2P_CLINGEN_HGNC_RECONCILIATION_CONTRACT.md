# HGNC, Gene2Phenotype and ClinGen Gene-Disease Reconciliation Contract

**Status:** Implementation in progress; technical and scientific qualification are separate gates.  
**Scope:** Gene-identifier normalization and cross-source gene–disease assertion reconciliation for germline SNV/INDEL interpretation.  
**Non-scope:** Variant pathogenicity classification, patient-specific inheritance compatibility, de novo confirmation, diagnosis, ACMG/AMP evidence assignment, or clinical sign-out.

## 1. Existing work and dependency order

This document extends the existing unmerged clinical work; it does not replace it:

- **PR #303:** phenotype intake, amendments/interoperability and phenotype source audit.
- **PR #304:** family genotype matrix and inheritance review contract. The matrix is a deterministic projection of source-bound sample calls, not an inheritance algorithm.
- **PR #311:** pedigree relationship revision lifecycle.
- **PR #314:** HGNC crosswalk, G2P/ClinGen source assertions, and source reconciliation.

The dependency order remains: qualify HGNC acquisition and deterministic resolution; bind that exact HGNC release through the analysis resource plan; reconcile G2P and ClinGen source assertions; independently qualify disease-specific interpretation; only then consider patient/family inheritance compatibility.

## 2. Authoritative source boundaries

### HGNC

- Authority: https://www.genenames.org/
- Archive downloads: https://www.genenames.org/download/archive/
- License: https://www.genenames.org/about/license/
- The complete-set and withdrawn files are separate source artifacts. The complete set represents approved nomenclature; the withdrawn file retains withdrawn and merged/split history.
- A merged withdrawn accession can resolve to one approved replacement. A split accession can have multiple replacements and must remain ambiguous/unresolved; it must never be flattened to one arbitrary gene.
- The SIRALOOM release manifest pins the archive release, exact official URLs, file sizes, local SHA-256 digests, and license/checksum semantics. HGNC does not publish a per-file cryptographic checksum for these TSV artifacts; the local SHA-256 is explicitly identified as a locally calculated integrity digest, not a publisher checksum.

### Gene2Phenotype (G2P)

- Authority and data access: https://www.ebi.ac.uk/gene2phenotype/
- Current export endpoint: https://www.ebi.ac.uk/gene2phenotype/api/panel/all/download/
- Archive location: https://ftp.ebi.ac.uk/pub/databases/gene2phenotype/G2P_data_downloads/
- Terms: https://www.ebi.ac.uk/about/terms-of-use/
- The source release must be pinned to an exact archive/acquisition date and exact local bytes. A moving “latest” endpoint is not a reproducible release identity.
- The parser preserves the source-native G2P record identifier, gene symbol, HGNC ID field, MONDO identifier, allelic requirement, confidence, molecular mechanism, publications, and raw row.
- If the source-native HGNC ID is present, it is resolved against the qualified HGNC release. An unresolved native ID is not silently replaced by a symbol-derived match. If the native ID is absent, symbol resolution is permitted only through the same qualified HGNC resolver.
- Numeric HGNC accessions are normalized to the canonical HGNC:<accession> representation only because the field is explicitly the source's HGNC ID field. This conversion is not applied to arbitrary numeric strings or gene symbols.

### ClinGen Gene-Disease Validity

- Curated downloads: https://search.clinicalgenome.org/kb/downloads
- Official gene-validity export: https://search.clinicalgenome.org/kb/gene-validity/download
- Gene-Disease Validity SOP: https://www.clinicalgenome.org/docs/gene-disease-validity-standard-operating-procedure/
- The exported file's FILE CREATED date is the release identity for that snapshot. The exact file bytes are locally SHA-256 pinned.
- The export's HGNC identifier, MONDO disease identifier, classification, mode-of-inheritance (MOI), report identifier, panel and source row are preserved.
- Gene-Disease Validity classifications remain source assertions. They are not automatically converted into ACMG/AMP variant evidence.

## 3. Identifier reconciliation rules

Cross-source identity is permitted only when both dimensions resolve:

1. The gene resolves to one canonical approved HGNC accession under the exact HGNC release selected by the analysis resource plan.
2. The disease identifier is a syntactically valid, exact seven-digit MONDO:<digits> identifier in both source assertions.

The join key is therefore (canonical_hgnc_id, canonical_mondo_id).

The following are deliberately not accepted as substitutes:

- Similar or identical gene symbols without a qualified HGNC resolution.
- Gene names, disease names, synonyms, text similarity, or fuzzy matching.
- A missing MONDO identifier.
- An ambiguous HGNC alias or a withdrawn accession with multiple replacements.
- An unqualified HGNC file, a different HGNC release, or a resource that was not selected and pinned by the analysis plan.

If HGNC is not selected and executable, source assertions remain separate and the cross-source join is blocked. G2P's native HGNC field does not bypass this gate.

## 4. Reconciliation outcomes

The reconciliation engine preserves source records and returns explicit identity outcomes, including:

- MATCHED: exact canonical HGNC and MONDO identity across sources.
- G2P_ONLY / CLINGEN_ONLY: source-local assertions that do not have an exact counterpart.
- UNMATCHABLE_MISSING_MONDO: a source record lacks a disease identifier required for the cross-source join.
- UNMATCHABLE_IDENTIFIER_NAMESPACE: gene identity cannot be resolved into the canonical HGNC namespace.
- UNMATCHABLE_NO_GENE_IDENTIFIER: no usable gene identifier is present.

A matched identity does not mean the sources agree on every evidence dimension. Each dimension is compared separately, and the complete raw source assertions remain available for review.

## 5. Mode-of-inheritance handling

### G2P

The provider maps the source's allelic-requirement values into controlled internal mode labels while preserving the original source term. Unrecognized values remain explicitly UNKNOWN/unmapped and are not silently assigned a mode.

### ClinGen

The official export uses compact MOI codes. The current deterministic mapping is:

| ClinGen source code | Internal representation | Treatment |
|---|---|---|
| AD | AUTOSOMAL_DOMINANT | Normalized |
| AR | AUTOSOMAL_RECESSIVE | Normalized |
| SD | AUTOSOMAL_SEMIDOMINANT | Normalized |
| XL | Unmapped source assertion | Review required; generic X-linked does not distinguish dominant from recessive |
| UD | Unmapped source assertion | Review required; undetermined is not a specific inheritance mode |

The raw ClinGen code and source row are retained. An unrecognized future code must remain unmapped until its meaning is established from an authoritative source and added with tests.

### Cross-source comparison

- Equal normalized mode sets: AGREE.
- Non-empty overlap with additional source modes: PARTIAL_AGREEMENT, not a total contradiction; review required.
- Disjoint normalized mode sets: CONFLICT; review required.
- Unknown, undetermined, or unrecognized source terms: UNMAPPED; review required.
- A mode supplied by only one source is not treated as cross-source agreement.

These statuses compare curated gene–disease assertions. They do not calculate whether a patient's observed family genotypes are compatible with a disease model. That remains outside this milestone.

## 6. Provenance and reproducibility

Each source assertion retains:

- Source/provider identity and source-record identifier.
- Resource ID, release/version and local SHA-256.
- Source-record SHA-256 where available.
- Request fingerprint and response digest.
- Raw source assertion.
- HGNC release, complete-set digest, withdrawn-file digest, input identifier, resolution status and candidate HGNC accessions.

The reconciliation identity includes the source record IDs and source resource IDs, versions, resource digests and source-record digests. A new source release therefore creates a new reconciliation identity instead of silently reusing an earlier result.

HGNC resolution is recorded as a resource execution within the analysis. Runtime execution re-verifies the exact manifest and both HGNC artifact digests. No silent provider or release substitution is permitted.

## 7. Clinical and laboratory safety boundaries

- G2P confidence and ClinGen gene–disease validity are not variant pathogenicity classifications.
- A MATCHED gene–disease assertion is not proof that the patient's variant causes the disease.
- A source MOI is not a patient-specific inheritance conclusion.
- A family genotype matrix is not proof of biological parentage or a de novo event.
- No phenotype similarity, inheritance compatibility score, or ACMG/AMP criterion is generated by this reconciliation.
- Conflicting, partial, unmapped, incomplete, or source-only evidence remains visible and requires human review.
- Technical resource qualification, organization approval, clinical validation, and laboratory accreditation are separate activities.

## 8. Verification state and remaining gates

The current code adds deterministic resolver binding, source-native HGNC preservation, strict identifier parsing, exact HGNC+MONDO reconciliation, source-versioned identities, explicit MOI mapping, and review statuses. Synthetic regression tests cover these behaviors.

The following are still required before G2P/ClinGen can be described as fully qualified for a laboratory:

1. Acquire actual G2P and ClinGen source snapshots from the official endpoints or exact official archives.
2. Record each release identity, exact source URL, byte size, local SHA-256, license/terms status and acquisition provenance.
3. Execute the real provider parsers against those downloaded bytes and compare the observed schemas and source values with the pinned provider contracts.
4. Create an independently reviewed G2P/ClinGen known-answer corpus covering canonical HGNC identifiers, withdrawn/merged/split identifiers, MONDO matching, multiple assertions, conflicting validity classifications, and MOI codes.
5. Run database-backed resource qualification, approval, activation, execution, failure/replay and audit tests.
6. Obtain laboratory review of any local policy needed for use in clinical interpretation.

Until these gates pass, synthetic test success is not evidence of clinical validity or real-source qualification. The implementation must remain fail-closed when the required approved resource release is absent.
