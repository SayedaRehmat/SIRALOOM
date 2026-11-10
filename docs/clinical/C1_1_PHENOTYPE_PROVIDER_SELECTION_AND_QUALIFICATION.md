# C1.1 phenotype-prioritization provider selection and qualification

**Status:** Candidate evaluation specification; no clinical provider selected or approved  
**Scope:** Germline SNV/INDEL phenotype capture and disease/gene candidate prioritization  
**Owner workflow:** Existing SIRALOOM evidence workflow and governed resource registry; no parallel execution framework.

## 1. Decision

Do not enable the current SIRALOOM exact/ancestor term-count method as a clinical prioritizer. Retain it only as transparent contextual navigation.

Do not select a clinical phenotype provider from popularity, a single publication, or synthetic tests. Evaluate established implementations on a reproducible public known-diagnosis corpus, then require laboratory-specific validation before clinical activation.

The current candidates are:

1. **Phen2Gene** — primary commercial-integration candidate for phenotype-only gene ranking, subject to verification of the HPO2Gene Knowledgebase (H2GKB) data terms and current release reproducibility. The command-line repository declares MIT licensing. It consumes HPO terms and returns ranked genes using a precomputed HPO2Gene knowledgebase and a probabilistic weighting/ranking method.
2. **Exomiser** — benchmark comparator and possible separately licensed provider. Evaluate its PHENOTYPE_ONLY mode separately from its VCF/genotype/ACMG pipeline. The software is AGPL-3.0; the data/predictor stack has additional restrictions, including non-commercial terms for some predictors. No commercial deployment is approved.
3. **LIRICAL** — benchmark comparator and possible separately licensed provider. Its likelihood-ratio method reports per-phenotype contributions and can run phenotype-only or phenotype+genotype. The repository's current LICENSE is a Jackson Laboratory non-commercial-use agreement; commercial use requires a separate license. No commercial deployment is approved.
4. **PhenoGenius / GADO** — optional phenotype-only benchmark comparators if their exact release, source data, software/data license and reproducibility can be pinned.

No provider is approved by this document. A license for software does not automatically grant rights to redistribute or commercially use its knowledgebase, ontology annotations, model data, predictors or reference datasets.

## 2. Scientific input contract

The provider input must be built from the SIRALOOM clinical record, not re-inferred from VCF or family status:

- GA4GH Phenopackets v2-compatible patient and phenotype representation.
- HPO identifiers resolved against the exact qualified HPO release.
- Explicit PRESENT, ABSENT/EXCLUDED, UNKNOWN and NOT_ASSESSED semantics. A missing record is not a negative observation.
- Preserve onset, severity, frequency, laterality and other supported modifiers, evidence, source, subject and observation time.
- Proband phenotype profile is kept separate from relatives' phenotype profiles. Relatives may be used only when the provider's documented model explicitly supports pedigree/family phenotypes and the relevant laboratory policy permits it.
- Preserve disease annotation source, release, identifier namespace, evidence, frequency and NOT qualifier.
- Preserve all raw provider output, version, model/data release, parameters, input fingerprint and output digest.
- Execute phenotype providers inside the governed SIRALOOM environment. Do not send identifiable patient phenotypes, pedigree details or VCF data to public demonstration websites or unapproved third-party APIs. Any remote provider requires explicit organizational approval, data-processing/security review and an appropriate contract before PHI is transmitted.

Do not silently discard negative/excluded phenotypes or convert them to positive terms. Do not merge sibling/parent findings into the proband profile. A provider's probability, likelihood ratio or score is not a diagnosis and is not an ACMG evidence code by itself.

## 3. Public benchmark

Use the published PhEval framework and its public Phenopacket corpora as the primary reproducible benchmark candidate:

- Zenodo DOI: 10.5281/zenodo.14679713, version v3, published 2025-01-17.
- Corpus archive: pheval-paper-corpora.tar.gz, publisher-listed MD5 0bebaaa74fa92d02110d1a71f53a0699, listed size 5.7 MB.
- Precomputed results archive: pheval-paper-results.tar.gz, publisher-listed MD5 ace8c0fc7b886f3f31bac6df462e89b7, listed size 5.6 GB.
- The publication compares phenotype-only Exomiser 14.0.2, GADO 1.0.4, Phen2Gene 1.2.3 and PhenoGenius 1.1.1, and phenotype+genomic Exomiser 14.0.2, LIRICAL 2.0.2 and AI-MARRVEL 0.1.0.
- Reproduce only the scope relevant to SIRALOOM's SNV/INDEL phenotype stage. Do not run or interpret structural-variant results as validation of the initial product scope.
- The paper's results are comparative evidence for those versions and cohorts, not a universal winner or proof of GCC/Middle Eastern population performance.
- Zenodo's visible metadata does not establish the license/redistribution terms for every corpus component. Verify the dataset and embedded source-record terms before downloading into controlled SIRALOOM storage, retaining, redistributing or using in commercial validation.

Acquisition record: the 5.7 MB corpus archive download was attempted during this audit but did not complete in the current execution environment. No corpus files have been added to the repository and no benchmark has been claimed as run.

## 4. Evaluation design

### 4.1 Comparators and modes

- Phen2Gene: exact release and H2GKB release pinned; HPO-only mode.
- Exomiser: exact application and phenotype-data release pinned; PHENOTYPE_ONLY preset and documented phenotype prioritisers only. No variant ACMG or inheritance filtering is allowed in the phenotype-only comparison.
- LIRICAL: exact release and background-data release pinned; phenotype-only command.
- PhenoGenius/GADO: include only after exact dependencies, licensing and offline reproducibility are verified.

Where the benchmark has an existing published result for the same exact tool/data version, retain it as a reference result; do not treat it as a substitute for re-execution.

### 4.2 Metrics

Report per-corpus and per-stratum:
- causal gene rank: top-1, top-3, top-5, top-10;
- mean reciprocal rank (MRR);
- recall and precision at predeclared cutoffs;
- candidate-list coverage / cases where causal gene is absent;
- runtime, peak RSS, CPU and data footprint;
- deterministic reproducibility across repeated runs;
- missing/invalid phenotype handling and provider error rate.

Do not optimize a score or threshold against the final test cases. Keep development and held-out case sets separated. Record every excluded case and reason.

### 4.3 Stratification and bias

Report phenotype term count, disease category, age/onset availability, family structure if present, and source cohort. Assess ancestry only where the source explicitly supplies it and the dataset terms permit it.

The PhEval corpus is not a GCC/consanguinity validation cohort. Do not claim that its results establish performance in Saudi, GCC, Middle Eastern or consanguineous families. Obtain a separate appropriately governed local validation cohort before making those claims.

### 4.4 Acceptance

A candidate provider is eligible for adoption only when:
- exact software and data releases are pinned and reproducibly acquired;
- software, model, ontology, annotations and dependency licenses are reviewed for the intended commercial SaaS use;
- all inputs and outputs conform to the SIRALOOM phenotype contract;
- known-answer and adversarial tests pass;
- performance, coverage and failure behavior are measured on the public benchmark;
- output provenance is preserved end-to-end;
- the lab can approve the exact version and parameters;
- no candidate rank is automatically converted into diagnosis, pathogenicity or PP4.

If no provider satisfies both scientific and commercial requirements, do not invent a replacement score. Keep the function as contextual navigation and obtain a suitable commercial license or approved alternative.

## 5. Findings that affect provider selection

### Exomiser
- Version 15.1.1 supports a documented PHENOTYPE_ONLY preset and HPO-based disease/gene prioritisation.
- Its documented variant-analysis configuration includes autosomal dominant, autosomal recessive homozygous/compound-heterozygous, X-dominant, X-recessive homozygous/compound-heterozygous and mitochondrial modes. This is broader than the earlier summary of its supported modes, but is not a complete model for all mechanisms in clinical genetics (e.g. Y-linked, imprinting, mosaic and other special mechanisms).
- Its combined output includes phenotype, variant and inheritance scoring, plus a logistic-regression combined score trained on UK 100,000 Genomes solved cases. Do not use that combined score as a phenotype-only score or assume calibration transfers to GCC populations.
- Its 15.1.1 automated ACMG module is explicitly partial. The current documentation says PP1 and BS4 are not assigned automatically, PM6 is not assigned, PM3 is limited to a phased trans observation with a ClinVar pathogenic variant in a recessive disorder, and PP4 is assigned from a phenotype-match threshold. These behaviors are not a substitute for SIRALOOM's criterion-specific ClinGen/VCEP implementation.
- The application is AGPL-3.0. Its documentation also identifies non-commercial restrictions for REVEL, AlphaMissense and SpliceAI model resources. The exact commercial license position must be reviewed before use.

### LIRICAL
- Its documented phenotype model computes per-observation likelihood ratios from disease phenotype annotations and background Mendelian disease frequencies, and exposes individual phenotype contributions.
- It can run phenotype-only or combine phenotype and genotype.
- Its repository LICENSE grants non-commercial use only and prohibits derivative works under that agreement; commercial use requires a separate agreement. This is a hard deployment gate, not an implementation detail.

### Phen2Gene
- The command-line repository declares MIT licensing.
- Its published method uses the HPO2Gene Knowledgebase (H2GKB) and probabilistic weighting/ranking of HPO terms to return ranked genes.
- The H2GKB is a separately distributed data artifact. Its license, source-data terms, update process and commercial redistribution/use rights must be verified independently. MIT on the code does not establish rights to the knowledgebase.
- It is gene-ranking rather than a complete disease-level likelihood or family inheritance engine.

## 6. Current SIRALOOM code disposition

backend/app/domain/phenotype_prioritization.py:
- Keep as a provenance-rich contextual evidence projection only.
- Its exact and patient-descendant-to-disease-term ancestor match count is not a published semantic-similarity algorithm, likelihood ratio or calibrated clinical score.
- Do not increase its weights, add IC formulas or tune thresholds in SIRALOOM.
- Replace clinical ranking only through an approved, pinned provider adapter after benchmark and license qualification.

The existing ProviderRegistry, resource execution contracts, resource qualification and immutable analysis resource snapshots are the integration path. Do not create a parallel provider registry or bypass resource execution with an ungoverned subprocess/API call. Provider execution must use the exact approved provider version and data release and must be recorded in the analysis provenance.

## 7. Implementation dependencies and next tasks

1. Verify PhEval corpus archive license and component provenance; acquire to controlled benchmark storage and calculate local SHA-256.
2. Reproduce the published baseline versions where feasible; pin containers, Java/Python runtimes, application releases and data releases.
3. Qualify Phen2Gene/H2GKB data licensing and run the same phenotype-only cases.
4. Run phenotype-only Exomiser and LIRICAL comparators only under permitted evaluation terms; seek written commercial licenses before production consideration.
5. Produce a per-case result matrix and stratified report; select only if performance, coverage, explainability, reproducibility and commercial rights are acceptable.
6. Implement the chosen provider as a resource-registry provider using existing execution/qualification contracts. Keep current contextual output available as an explicitly non-clinical audit view, not a fallback clinical score.
7. Execute end-to-end workflow tests and independent known-answer review before laboratory activation.

## 8. References

- PhEval paper and public corpus/results: https://doi.org/10.5281/zenodo.14679713
- PhEval code and documentation: https://github.com/monarch-initiative/pheval and https://monarch-initiative.github.io/pheval/
- Exomiser 15.1.1 analysis and phenotype-only preset: https://exomiser.readthedocs.io/en/latest/advanced_analysis.html
- Exomiser 15.1.1 result interpretation: https://exomiser.readthedocs.io/en/latest/result_interpretation.html
- Exomiser 15.1.1 ACMG limitations: https://exomiser.readthedocs.io/en/latest/acmg_assignment.html
- Exomiser license: https://github.com/exomiser/Exomiser
- LIRICAL algorithm and documentation: https://thejacksonlaboratory.github.io/LIRICAL/stable/
- LIRICAL current license: https://github.com/TheJacksonLaboratory/LIRICAL/blob/master/LICENSE
- Phen2Gene publication: https://doi.org/10.1093/nargab/lqaa032
- Phen2Gene source and declared MIT license: https://github.com/WGLab/Phen2Gene
- GA4GH Phenopackets v2: https://www.ga4gh.org/product/phenopackets/

**Release boundary:** this is a provider-selection and validation plan. It does not claim that any candidate has passed SIRALOOM qualification or is approved for clinical/commercial deployment.
