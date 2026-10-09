# Standards and authoritative-source traceability — initial matrix

This matrix is an applicability assessment, not a declaration of compliance. Jurisdiction, intended use and the deploying laboratory's quality system determine which obligations apply.

| Source / version | Relevance to SIRALOOM | Implementation implication | Current evidence / gap |
|---|---|---|---|
| HTS specifications: VCF v4.5 (current specification family; repository validator currently declares 4.2/4.3) | File syntax, headers, INFO/FORMAT cardinality, genotype and allele representation | Decide supported VCF versions explicitly; build malformed and edge-case fixtures; use a standards-aware parser/tool in addition to local checks | Validator has custom checks and BCFtools validation; version policy and conformance suite need review |
| Official BCFtools/HTSlib docs | Normalization, splitting, REF checks, indexing and command behavior | Pin version and command policy; validate against reference FASTA; test genotype/annotation remapping and publication atomicity | CI asserts BCFtools 1.19; golden benchmark remains a release gate |
| ACMG/AMP Richards et al. 2015 | Five-tier sequence-variant classification framework | Evidence-weighted, documented proposals; no arbitrary score-to-classification shortcut; retain expert review | Criterion infrastructure exists; repository declares classification correctness unvalidated |
| ClinGen Variant Classification Guidance (page updated July 2025) and applicable VCEP specifications | Criterion-specific refinements and gene/disease applicability | Bind exact specification identity/version and eligible evidence; fail closed on ambiguity or unsupported methods | Specification selection/assessment code exists; independent expert-adjudicated concordance remains required |
| GA4GH VRS v2.0 | Interoperable variation representation and computed identifiers | Keep local canonical key distinct from VRS identifiers; add VRS only through a separately tested mapping layer if required | Current canonical identity exists; no evidence here of VRS conformance |
| ISO 15189:2022 | Medical-laboratory quality and competence system | Translate applicable requirements into controlled requirements, validation records, change control, risk management and laboratory procedures | Software alone cannot establish laboratory accreditation; lab QMS/validation is external |
| ISO/IEC 27001 / ISO 27799 and applicable privacy law | Information-security management and health-information safeguards | Threat model, access controls, incident handling, retention, encryption, backups, vendor/egress review | Code controls exist; live security assessment and operational evidence remain |
| IEC 62304 / ISO 14971, where product classification/intended use makes them applicable | Medical-software lifecycle and risk management | Determine jurisdictional classification with qualified counsel/regulatory specialist before asserting applicability | Applicability not determined in this audit |
| FHIR Genomics / GA4GH VA-Spec, where integration is needed | Interoperable exchange of genomic results and evidence statements | Define exchange use cases and mappings; preserve source assertions and provenance | Not a Phase-1 release blocker unless required by pilot customers |

## Authoritative references

- [HTS specifications repository](https://github.com/samtools/hts-specs) — the VCF v4.3 document explicitly says it is superseded by v4.4 and v4.5; the supported-version policy should therefore be deliberate.
- [BCFtools documentation](https://samtools.github.io/bcftools/bcftools.html)
- [ACMG/AMP consensus guideline (Richards et al., 2015)](https://doi.org/10.1038/gim.2015.30)
- [ClinGen Variant Classification Guidance](https://www.clinicalgenome.org/tools/clingen-variant-classification-guidance/)
- [GA4GH VRS documentation](https://vrs.ga4gh.org/en/stable/)
- [ISO 15189:2022 official page](https://www.iso.org/standard/76677.html)
- [GA4GH Variant Annotation Specification](https://va-spec.ga4gh.org/en/stable/)

## Evidence required before any compliance statement

For each applicable requirement: controlled requirement ID; responsible owner; implementation link; test/validation protocol and raw result; risk assessment; deviations/limitations; review/approval; release/version scope; and retention location. Do not state “ISO compliant” or “clinically validated” based solely on repository code or CI.
