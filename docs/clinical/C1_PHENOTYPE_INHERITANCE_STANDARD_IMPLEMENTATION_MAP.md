# C1 phenotype and inheritance: clinical-laboratory implementation map

**Status:** Engineering requirements baseline; not a claim of clinical qualification  
**Scope:** Germline SNV/INDEL phenotype, pedigree, disease-model compatibility and segregation evidence  
**Architecture:** Preserve the existing SIRALOOM workflow, resource registry, evidence engine, immutable analysis snapshots and human-review boundary.

## 1. Operating rule

SIRALOOM must consume established clinical vocabularies, curated gene–disease assertions, published variant-interpretation recommendations and laboratory-approved procedures. It must not invent phenotype weights, inheritance rules, penetrance values, de novo thresholds, segregation strengths or diagnostic cutoffs.

There is no single universal phenotype-ranking algorithm or single gene-inheritance database mandated for every diagnostic laboratory. Laboratories select and validate their tools, evidence sources and SOPs. SIRALOOM therefore preserves source-specific assertions and requires an explicitly approved, versioned laboratory policy where a decision requires a policy choice. Conflicting or missing assertions remain visible; they are not silently resolved by a home-grown hierarchy.

## 2. Standards and source-to-function map

| Laboratory function | Governing standard / source | Required SIRALOOM behavior | Existing implementation / disposition |
|---|---|---|---|
| Phenotype vocabulary | Human Phenotype Ontology (HPO), pinned ontology release | Store stable HPO identifiers; retain submitted term and canonical resolution; preserve ontology release and artifact digest. | Existing HPO resource/ontology adapters and clinical phenotype intake are retained. |
| Phenotype observation semantics | GA4GH Phenopackets v2; HPO annotation conventions | Keep PRESENT, ABSENT, EXCLUDED, UNKNOWN and NOT_ASSESSED distinct; preserve onset, severity, modifiers, frequency, source and subject. Absence of a record is not an absent phenotype. | Existing clinical intake and C1.1 present-proband-only matching are retained; audit field-level round-trip against Phenopackets. |
| Family phenotype and pedigree exchange | GA4GH Phenopackets v2 Family/Pedigree; GA4GH Pedigree v1.0; PED interoperability | Represent proband, relatives, affected status and relationships explicitly. Map every family VCF sample identifier to exactly one pedigree member. Preserve relationship type and verification state. | Existing pedigree lifecycle and clinical snapshots are retained; no inferred biological relationship. |
| Disease–gene validity | ClinGen Gene-Disease Validity framework; GenCC assertions; approved expert-panel curation | Preserve each assertion's source, disease identifier, validity classification, evidence, release and record identity. Do not equate evidence scales across providers. | C1.2 G2P/ClinGen acquisition and HGNC-gated identity reconciliation implemented; technical CI qualification passed. |
| Disease-specific inheritance and molecular mechanism | G2P allelic requirement/mechanism; ClinGen Gene-Disease Validity mode of inheritance; GenCC and other laboratory-approved disease-specific assertions | Bind mode and mechanism to the specific gene–disease assertion, not gene alone. Preserve provider-native labels and conflicting assertions. Unknown/ambiguous modes remain unresolved. | Source adapters preserve G2P allelic requirement/mechanism and ClinGen MOI; the current review-context builder records assertions but deliberately makes no compatibility conclusion. |
| Disease phenotype annotations | HPOA disease annotations, release-pinned | Preserve positive and NOT annotations, evidence, frequency, onset, sex and reference. Do not interpret missing annotations as absence or convert annotation frequency into an unvalidated patient likelihood. | C1.1 preserves HPOA provenance and NOT annotations; current exact/IS-A context ordering is not a clinical semantic-similarity score. |
| Phenotype-based candidate prioritization | Validated, documented algorithm selected by the laboratory; Exomiser is an established candidate implementation, not a universal mandated standard | Use a documented semantic-similarity implementation and pinned disease/phenotype data. Validate against known-answer cases and the laboratory's intended population. Explain components and limitations. Never convert rank into diagnosis or ACMG evidence automatically. | Current C1.1 is explicitly CONTEXTUAL_CANDIDATE_ORDERING_ONLY. Its exact/IS-A term-count ordering is not accepted as a final clinical prioritizer. Evaluate an offline, version-pinned Exomiser adapter and compare it with the existing evidence workflow before enabling clinical ranking. |
| Genotype / family compatibility | Disease-specific inheritance assertion plus qualified VCF genotype, phase, callability, sample identity, ploidy and pedigree evidence | Produce evidence sufficiency and compatibility states only when required evidence and a versioned lab policy are satisfied. Distinguish AR homozygous, AR trans, cis, unresolved phase, AD, X-linked subtypes and de novo hypotheses. | No clinical compatibility engine is enabled. The existing inheritance review context is provenance/evidence-gap only. |
| Segregation variant evidence | ACMG/AMP 2015; ClinGen SVI PP1/BS4/PP4 guidance; applicable ClinGen Variant Curation Expert Panel specifications | Keep inheritance-model compatibility separate from variant pathogenicity evidence. Apply PP1/BS4 only with the relevant disease/gene context, eligible relatives, phenotype/penetrance considerations and the applicable specification. PP4 requires phenotype specificity; simple HPO overlap is insufficient. | Must be implemented only as a versioned evidence-policy layer with criterion-specific known answers and reviewer approval. |
| De novo variant evidence | ACMG/AMP PS2/PM6; ClinGen SVI PS2/PM6 recommendation and any applicable VCEP specification | Do not call confirmed de novo from absent parental ALT alone. Require proband and parental genotype QC/callability, sample identity, relationship status, phenotype consistency and policy-specific evidence. Distinguish confirmed from assumed parentage. | Not implemented as a clinical conclusion. Existing family matrix records missing calls and unverified relationships as evidence gaps. |
| Recessive allelic evidence | ACMG/AMP PM3 and applicable VCEP specification | Require two disease-relevant alleles and adequate trans evidence before applying PM3. Cis or unresolved phase must not be treated as trans. Apply strength only according to the current gene/disease-specific specification. | Not yet implemented as a criterion engine. |
| Penetrance, expressivity and age | Disease-specific curated assertion or cited primary literature approved by the laboratory | Store value/range, population/context, age/sex dependence, evidence, source and uncertainty. Never fill missing penetrance with a generic default. | Current data contract requires an explicit status but G2P/ClinGen sources do not necessarily provide penetrance. Unknown remains unknown; a separate governed source is required. |
| Clinical conclusion and report | Laboratory SOP, qualified clinical reviewer and applicable jurisdictional quality/regulatory framework | Automated output is a review aid. Only authorized human review and laboratory-approved sign-out can produce a clinical report. Preserve all inputs, sources, policy versions and decisions. | Existing human review and reportability boundaries remain; no automated diagnosis/sign-out is introduced by C1. |

## 3. Non-negotiable interpretation boundaries

1. **A phenotype rank is not a diagnosis.** HPO term count, ontology proximity or a semantic-similarity score cannot independently establish causality or satisfy PP4.
2. **A gene-level mode is not a disease-specific model.** A gene may cause multiple disorders through different mechanisms and inheritance patterns. Use the exact gene–disease assertion.
3. **Homozygous does not mean causal AR.** Require a valid disease association, compatible mechanism, two-allele evidence, phenotype context and technical QC.
4. **Two heterozygous variants do not prove trans.** Use parental origin or a qualified phasing method; otherwise retain PHASE_UNRESOLVED.
5. **Missing is not reference.** No-record, unavailable genotype, no-call, partial no-call and low-quality call are separate states. They cannot support de novo or segregation claims.
6. **Unaffected is not automatically benign evidence.** Evaluate disease-specific penetrance, age, sex and phenotype ascertainment before interpreting an unaffected carrier.
7. **Recorded pedigree is not verified biological parentage.** Sample identity and biological relatedness are distinct evidence domains.
8. **Sex is not a ploidy call.** Use assembly-specific PAR boundaries, specimen/caller evidence and an approved locus-specific ploidy policy. Unsupported or conflicting ploidy requires review.
9. **Inheritance compatibility is not ACMG classification.** Candidate model compatibility and ACMG/AMP evidence codes are separate outputs with separate provenance and policies.
10. **No cross-provider confidence arithmetic.** G2P confidence, ClinGen validity classifications and GenCC classifications retain their native semantics; no numeric conversion or implicit precedence is allowed.
11. **No population inference from consanguinity assumptions.** Consanguinity is explicit family-history evidence; homozygosity, surname, geography or ethnicity cannot establish it.
12. **Unsupported mechanisms stay unsupported.** Imprinting, mosaicism, oligogenicity, repeat expansions, CNV/SV and mitochondrial mechanisms require separately qualified scope. They must not inherit autosomal SNV/INDEL logic.

## 4. Required implementation sequence

### C1.1 — Phenotype data and candidate context
- Preserve the current HPO/HPOA source-pinned inputs and explicit phenotype states.
- Keep the current deterministic exact/IS-A output labelled contextual and unqualified.
- Audit phenotype capture and exports against Phenopackets v2 and the GA4GH pedigree mapping.
- Evaluate a pinned offline Exomiser release/data bundle as a candidate phenotype-prioritization provider, not as SIRALOOM's complete inheritance engine. Current Exomiser documentation lists AD, AR, X_RECESSIVE and UNDEFINED inheritance modes; this does not cover the full SIRALOOM target (including X-linked dominant and all required complex family evidence states). Jannovar documentation also describes reduced specificity for larger pedigrees. Exomiser therefore cannot replace C1.4's complete disease-specific family evidence workflow. Review its AGPL-3.0 software license, data redistribution terms, runtime, HPO/disease-resource versions and reproducibility before any commercial SaaS integration.
- Compare its outputs with the existing method on public, documented known-answer cases. Do not implement a replacement home-grown score.
- Enable clinical ranking only after independent validation and explicit laboratory approval.

### C1.2 — Gene–disease and mechanism sources
- Retain the successful real-source G2P, ClinGen and HGNC acquisition/qualification workflow.
- Preserve native assertions and disagreements by exact HGNC + disease identifier and source record.
- Add GenCC and any further source only through the same acquisition, provenance, parser and qualification lifecycle.
- Do not invent a precedence rule where sources conflict. Require a governed review decision.

### C1.3 — Family evidence qualification
- Validate real public GIAB and 1000 Genomes family data for technical genotype, pedigree, phase, callability and ploidy behavior.
- Keep public technical benchmarks distinct from clinical family known-answer qualification.
- Do not claim clinical penetrance, phenotype or diagnosis validation from datasets without those data.
- Preserve controlled family data outside public GitHub and only under the applicable access terms.

### C1.4 — Inheritance compatibility
- Remains blocked until the disease-specific assertion contract, family sample mapping, relationship evidence, phase, callability and ploidy policies are qualified.
- Implement only the compatibility/evidence-state rules required by the cited disease-specific assertions and laboratory-approved policy.
- Every result must carry source assertion IDs, source versions, policy version, genotype/family evidence, missing evidence and a reproducible fingerprint.
- Required states: SUPPORTED_FOR_REVIEW, INCONSISTENT, INSUFFICIENT_DATA, CONFLICTING_EVIDENCE, UNSUPPORTED_MODEL, REQUIRES_HUMAN_REVIEW. These are not pathogenicity classifications.

### C1.5 — ACMG/ClinGen evidence integration
- Implement PP1, BS4, PP4, PM3, PS2 and PM6 only against the current ACMG/AMP and ClinGen SVI/VCEP specifications applicable to the gene/disease.
- Preserve evidence strength, observations, meioses/relatives, phenotype consistency, phase, relationship verification, penetrance assumptions and reviewer rationale.
- Prevent duplicate evidence use and criterion double counting under the existing ACMG evidence engine.
- Require independent known-answer tests for each criterion and strength before clinical use.

## 5. Exomiser due-diligence findings

Exomiser is an established open-source prioritization tool and a candidate implementation to evaluate; it is not a clinical standard that all laboratories must use.

- The published 15.1.1 documentation describes offline VCF + HPO analysis and a data bundle with phenotype and assembly-specific genomic resources. Its installation documentation reports approximately 80 GB of downloads, Java 21+, and version-coupled phenotype / GRCh37 / GRCh38 data.
- The documented Exomiser inheritanceModes configuration lists AUTOSOMAL_DOMINANT, AUTOSOMAL_RECESSIVE, X_RECESSIVE and UNDEFINED. That documented set is insufficient as the sole engine for SIRALOOM's intended disease-specific model coverage.
- Jannovar's own inheritance documentation warns that larger pedigrees can lose specificity (reduced ability to exclude incompatible variants), although sensitivity is retained. This must be represented in any use/qualification.
- The Monarch Exomiser project page identifies the software as AGPL-3.0. Commercial SaaS deployment requires a legal review of the exact distribution, modification and network-use model before adoption.
- Therefore: evaluate Exomiser for phenotype ranking and as a comparison baseline only. Do not delegate complete C1.4 inheritance conclusions or ACMG/ClinGen criterion assignments to it. No Exomiser dependency is approved or added by this document.

References:
- Exomiser 15.1.1 installation and resource requirements: https://exomiser.readthedocs.io/en/development/installation.html
- Exomiser inheritance modes: https://exomiser.readthedocs.io/en/stable/advanced_analysis.html
- Jannovar pedigree/inheritance limitations: https://app.readthedocs.org/projects/jannovar/downloads/pdf/develop/
- Exomiser license listing: https://next.monarchinitiative.org/tools/exomiser

## 6. Current code assessment

| Code / area | Current behavior | Required disposition |
|---|---|---|
| backend/app/domain/phenotype_prioritization.py | Exact HPO match and patient-descendant-to-disease-term IS-A match; counts matched patient terms; deterministic ordering; retains NOT assertions and provenance. | Keep only as contextual navigation. Do not describe it as a standard semantic-similarity algorithm or clinical prioritizer. Qualify or replace the clinical ranking provider after Exomiser evaluation. |
| backend/app/domain/gene_disease_source_assertions.py | Preserves source-native G2P/ClinGen assertions; HGNC resolver gates namespace matching; ambiguous ClinGen MOI remains unmapped. | Retain. Add source-specific regression tests for all native labels, disease identity and conflicting assertions. |
| backend/app/domain/inheritance_review_context.py | Validates disease/family evidence shape, preserves source and family provenance, enumerates evidence gaps, returns no compatibility/segregation/de novo conclusion. | Retain as evidence contract. Do not expand it into an unreviewed rule engine. |
| backend/app/inheritance.py and pedigree workflow | Existing conservative sufficiency/review boundary; historical M10 heuristic retired. | Preserve. Do not restore M10 scores or heuristic status conclusions. |
| ACMG/ClinGen evidence engine | Existing classification architecture. | Add only criteria-specific, source-backed evidence adapters after their specifications and qualification fixtures are ready. |

## 7. Release gates

- Every rule has a source URL, exact version/date, source record or specification section, and implementation mapping.
- Every external resource is acquired, checksum-pinned, qualified and organization-approved before production use.
- Every algorithm and policy is versioned and reproducible.
- Positive, negative, boundary, missing-data and conflicting-source tests pass.
- Real public technical family data tests the actual end-to-end workflow.
- Clinical known-answer validation is separately reviewed by qualified independent reviewers.
- Tenant authorization, immutable snapshots, crash/replay and report provenance remain intact.
- No clinical-readiness claim is made until laboratory validation, SOP approval, qualified review and applicable regulatory/quality requirements are satisfied.

## 8. Authoritative references

- Richards et al. (2015), ACMG/AMP sequence variant interpretation: https://doi.org/10.1038/gim.2015.30
- ClinGen SVI PP1/BS4/PP4 recommendations: https://clinicalgenome.org/docs/clingen-guidance-for-use-of-the-pp1-bs4-co-segregation-and-pp4-phenotype-specificity-criteria-for-sequence-variant/
- ClinGen SVI PS2/PM6 recommendation, v1.1 (approved 2018; updated 2021): https://www.clinicalgenome.org/site/assets/files/3461/svi_proposal_for_de_novo_criteria_v1_1.pdf
- ClinGen Gene-Disease Validity framework: https://www.clinicalgenome.org/curation-activities/gene-disease-validity/
- HPO: https://hpo.jax.org/
- GA4GH Phenopackets v2: https://www.ga4gh.org/product/phenopackets/
- GA4GH Pedigree v1.0: https://www.ga4gh.org/product/pedigree/
- Exomiser documentation, prioritization and inheritance filters: https://exomiser.readthedocs.io/en/stable/
- Exomiser result interpretation: https://exomiser.readthedocs.io/en/latest/result_interpretation.html

**Final boundary:** this map specifies the implementation target. It does not certify SIRALOOM as clinically validated, nor does it imply that every laboratory follows an identical software pipeline. Each laboratory must approve its resource releases, validated software/policies, SOPs and clinical sign-out process.
