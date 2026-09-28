# SIRALOOM Scientific & Laboratory Workflow Specification v1

**Status:** Controlled workflow specification  
**Scope:** VCF intake through interpretation, review, reporting, and reanalysis

SIRALOOM operationalizes validated genomic methods, reference resources, evidence sources, and human review. It does not replace established genomic algorithms, standards, or clinical sign-out.

## Controlled workflow

ACCESSION → VCF_INTAKE → VCF_VALIDATION → BUILD_VERIFICATION → NORMALIZATION → ANNOTATION → POPULATION_EVIDENCE → PHENOTYPE → EVIDENCE → ACMG/CLINGEN → HUMAN_REVIEW → REPORT → REANALYSIS

Every stage requires explicit inputs, outputs, durable state, provenance, retry policy, failure class, and next-step semantics.

## Analytical boundary

Initial intake supports VCF/VCF.GZ, genome build, assay/test context, case metadata, phenotype/HPO, pedigree/inheritance where available, and upstream QC/provenance metadata. FASTQ, alignment, variant calling, joint genotyping, and assay-specific upstream QC remain outside the initial SIRALOOM analytical boundary.

## Stage requirements

### 0. Accessioning
Record accession/case context, specimen/test information, ordering context, analysis purpose, organization, timestamps, operator, and upstream provenance. Accession context is immutable.

### 1. VCF intake
Preserve the original artifact. Record SHA-256, size, compression, header, samples, contigs, FORMAT/INFO definitions, VCF version, and caller/pipeline metadata where present. Never overwrite the original VCF.

### 2. Structural and semantic validation
Validate syntax, required columns, POS, REF/ALT, contigs, INFO/FORMAT consistency, genotype consistency, duplicate samples/contigs, malformed records, unsupported symbolic alleles, multiallelic structure, compression/index state where applicable, and reference-build compatibility. Permanent scientific/data failures must not become generic infrastructure failures.

### 3. Genome-build verification
Supported production builds are GRCh37 and GRCh38. Production interpretation requires an explicit build. Each immutable reference package contains FASTA, FAI, manifest, checksums, assembly/provider/release metadata, construction/indexing software, contig dictionary, aliases, and validation status.

### 4. Reference normalization
Use a validated standard implementation, currently BCFtools norm, with a pinned reference package. Freeze the exact command policy only after golden-dataset validation. Do not introduce atomization, REF substitution, duplicate removal, or other transformations without scientific validation. VCF normalization and GA4GH VRS canonicalization remain separate layers.

### 5. Annotation
Use provider abstraction. Trial GeneBe is permitted; production must support local VEP/cache and laboratory resources. Record provider/version/configuration/build/input identity/output/timestamp/hash/failure metadata.

### 6. VEP/resource strategy
Production VEP uses a pinned local cache. VEP software, cache, reference build/FASTA, and annotation configuration form one versioned resource package.

### 7. Population evidence
Keep global, ancestry/population-specific, laboratory-internal, and cohort frequencies distinct. Never relabel a global frequency as a population-specific frequency.

### 8. Phenotype
Store HPO terms, negation where supported, onset/context, source, provenance, and mapping/version information separately from genomic evidence.

### 9. Pedigree/inheritance
Represent family structure, affected status, relationships, genotype observations, segregation, de novo observations, and inheritance models. Automated criterion assignment remains constrained by applicable specifications.

### 10. Evidence
Evidence records contain type, source, identifiers, observation, interpretation, access date, source version, strength, linked variant/gene/disease, curator/operator, and provenance. ClinVar is an evidence/archive source, not SIRALOOM's clinical decision engine.

### 11. ACMG/AMP
Represent criterion, direction, strength, evidence IDs, reason, status, and metadata explicitly. Annotation scores do not directly become clinical classifications. Flow: raw annotation → evidence extraction → criterion assessment → combination logic → proposed classification → human review.

### 12. ClinGen
Where a validated ClinGen VCEP specification applies, it supersedes generic baseline behavior for applicable criteria. Ambiguous or unavailable validated specifications fail closed or require review. Silent specification selection is prohibited.

### 13. Human review
States: PROPOSED, REQUIRES_REVIEW, APPROVED, REJECTED, SUPERSEDED. Capture reviewer, timestamp, evidence reviewed, criteria decisions, rationale, before/after classification, report version, workflow version, and resource versions.

### 14. Reporting
Reports must reconstruct case, analysis, variant, evidence, interpretation, and provenance, including original/normalized artifact hashes, reference hash, resource/cache versions, software/container version, workflow version, and configuration hash.

### 15. Reanalysis
Never overwrite historical interpretations. New analyses may use newer ClinVar, gnomAD, VEP, ClinGen, phenotype, or laboratory resources while preserving prior reproducibility.

## Reference-service architecture

Production normalization must not depend on Ensembl REST. Reference packages are supplied from controlled object storage to an ephemeral worker filesystem, used by the pinned normalization tool, and removed according to retention policy. Public services may be diagnostic/development dependencies only.

## Failure model

| Class | Examples | State | Retry |
|---|---|---|---|
| Scientific/data | invalid VCF, unsupported allele, reference mismatch, unsupported build | BLOCKED / INVALID_INPUT | No |
| Transient infrastructure | 503, storage timeout, temporary DB/queue interruption | RETRYING | Bounded exponential backoff |
| Resource | memory/disk exhaustion, worker termination | RESOURCE_FAILURE | Controlled re-execution |
| Human gate | ambiguous specification, conflicting evidence | REQUIRES_REVIEW | Human action |

A transient infrastructure failure must never become a scientific conclusion.

## Durable execution

Browser closure, API restart, and worker restart must not lose analysis state. Completed steps are not unnecessarily repeated. Artifacts are immutable. Retries are idempotent. Durable step state, leases, and input/output artifacts prevent duplicate concurrent execution.

## Provider/resource abstraction

External scientific resources are accessed through ReferenceProvider, AnnotationProvider, PopulationProvider, EvidenceProvider, ClinGenSpecificationProvider, and ArtifactStore abstractions. Provider implementation is not the scientific workflow.

## Scientific validation gate

The golden dataset must include SNVs, insertions, deletions, repetitive indels, multiallelics, MNVs, symbolic alleles, chromosome X/Y, supported mitochondrial variants, contig aliases, reference mismatches, and malformed VCFs. Expected outputs are frozen/versioned. Every change to normalization, reference, VEP, annotation, ACMG logic, or ClinGen specifications must execute the relevant validation suite.

## Laboratory-readiness gate

SIRALOOM is not laboratory-ready until validated VCF intake, explicit build control, pinned reference, validated normalization, reproducible annotation, versioned evidence, controlled ACMG/ClinGen interpretation, human review, immutable provenance, reproducible reanalysis, golden-dataset validation, and failure-injection testing are demonstrated.

## Engineering rule

No implementation change may silently alter the scientific meaning of a variant representation, evidence source, classification rule, resource version, or workflow transition. Changes require deterministic tests and must preserve backward reproducibility where scientifically appropriate.
