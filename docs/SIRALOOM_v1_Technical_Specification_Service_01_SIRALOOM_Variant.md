# SIRALOOM v1 Technical Specification
## Service 01 — SIRALOOM Variant

**Document status:** Architecture Baseline / Pre-Implementation  
**Version:** 1.0.0  
**Date:** 2026-09-06  
**Platform:** SIRALOOM  
**Service:** SIRALOOM Variant  
**Implementation state:** Not yet implemented  
**Authority:** SIRALOOM Master Operating Constitution + this specification

---

## 0. Executive Decision

SIRALOOM is the parent platform. **SIRALOOM Variant** is Service 01 and the permanent foundation for the variant interpretation/reporting domain.

Phase 1 begins at **VCF**, not FASTQ:

```text
VCF
 → validation
 → normalization
 → annotation
 → population context
 → evidence aggregation
 → ACMG/AMP + ClinGen decision support
 → human review
 → report
 → complete provenance/audit package
```

The architecture MUST support later expansion without redesigning the core:

```text
Phase 2: FASTQ → analysis pipeline → VCF → SIRALOOM Variant
Phase 3: local/on-prem resources and installer
Phase 4: reanalysis
Future: CNV / SV / RNA / somatic / phenotype / additional services
```

The first implementation MUST therefore be a **modular monolith with explicit domain boundaries and adapters**, not a collection of premature microservices.

---

# 1. Governing Principles

These are binding design principles inherited from the project constitution.

### 1.1 No silent assumptions

Unknowns MUST be classified as:

- Known
- Validated
- Documented
- Inferred
- Hypothesis
- Unknown
- Requires Research
- Requires User Decision
- Requires Experimental Validation

Foundational uncertainty MUST be resolved before implementation.

### 1.2 Dependency order

Work proceeds:

```text
Requirements
 → Domain architecture
 → Data architecture
 → Security architecture
 → Integration contracts
 → API contracts
 → Implementation design
 → Persistence
 → Backend
 → UI
 → End-to-end testing
 → Validation
```

### 1.3 Traceability

Every major requirement maps to:

```text
Requirement
 → Architecture
 → Design
 → Implementation
 → Test
 → Validation
```

### 1.4 No scientific conflation

SIRALOOM MUST distinguish:

```text
Raw data
Processed data
Observation
Finding
Evidence
Assertion
Interpretation
Recommendation
Computational artifact
```

Annotation MUST NOT be represented as interpretation.

Classification MUST NOT be represented as diagnosis.

Computational prediction MUST NOT be represented as pathogenicity by itself.

Population frequency MUST NOT be treated as disease causality.

### 1.5 Universal provenance

Every service added to SIRALOOM MUST automatically inherit:

- case identity
- analysis identity
- artifact lineage
- tool/version
- database/resource/version
- workflow version
- parameters
- actor
- timestamp
- action
- before/after state
- reason
- evidence links
- checksums
- report lineage

No future service may implement a separate, incompatible audit system.

---

# 2. Evidence and Standards Basis

This specification aligns its clinical-genomics concepts with established standards and current authoritative documentation.

### 2.1 ACMG/AMP

The ACMG/AMP sequence-variant framework defines the five standard Mendelian classification categories:

- Pathogenic
- Likely Pathogenic
- Uncertain Significance
- Likely Benign
- Benign

and evaluates evidence including population, computational, functional and segregation data.

Source:
https://pubmed.ncbi.nlm.nih.gov/25741868/

### 2.2 ClinGen

The broad ACMG/AMP framework requires gene/disease- and criterion-specific specifications for more consistent application of evidence. SIRALOOM MUST therefore support framework-specific and specification-specific rule versions rather than hard-coding a single undifferentiated "ACMG calculator."

Source:
https://pubmed.ncbi.nlm.nih.gov/31479589/

### 2.3 CAP / CLSI

CAP's NGS worksheets cover the lifecycle of clinical NGS, including test validation, quality management, bioinformatics/IT, interpretation, reporting and reanalysis. This specification therefore treats the VCF interpretation service as one controlled component inside a larger laboratory workflow.

Source:
https://www.cap.org/education/practice-hubs/next-generation-sequencing-ngs-worksheets/

### 2.4 HL7 FHIR

SIRALOOM's provenance model is designed to map to FHIR Provenance and AuditEvent concepts. FHIR distinguishes provenance about how a resource came to exist from AuditEvent records of events as they occur.

Sources:
https://hl7.org/fhir/provenance.html
https://fhir.hl7.org/fhir/auditevent-definitions.html

### 2.5 GA4GH Variation Representation

The canonical variant identity layer SHOULD remain compatible with GA4GH Variation Representation concepts where practical.

Source:
https://vrs.ga4gh.org/

### 2.6 GeneBe

GeneBe is an annotation provider, not the SIRALOOM domain model.

Current GeneBe documentation/site indicates:
- API access for programmatic annotation
- Python client / Java CLI resources
- ACMG-oriented annotation
- research and educational, non-commercial use
- explicit "not for clinical or diagnostic use" language

Therefore GeneBe MAY be used during permitted development/research workflows but MUST NOT be architecturally required as the permanent clinical backend.

Sources:
https://genebe.net/
https://genebe.net/api-showcase
https://docs.genebe.net/

---

# 3. Product Definition

## 3.1 Service name

**SIRALOOM Variant**

## 3.2 Purpose

A local-first, explainable variant annotation and interpretation-support service that transforms normalized VCF variants into:

1. structured annotations
2. population context
3. evidence records
4. ACMG/ClinGen evidence assessments
5. reviewer decisions
6. final interpretation state
7. human-readable report
8. machine-readable report
9. complete case provenance/audit package

## 3.3 Phase 1 boundary

### In scope

- VCF ingestion
- VCF validation
- genome-build verification
- reference-aware variant normalization for supported SNV/MNV/indel records
- canonical variant identity
- canonical variant identity
- transcript/consequence annotation
- GeneBe adapter for development/research
- future VEP adapter
- ClinVar adapter
- gnomAD adapter
- population hierarchy
- Middle Eastern population extraction where present in configured gnomAD resources
- optional country-specific/local population resources
- evidence store
- ACMG/AMP evidence model
- ClinGen specification model
- reviewer workflow
- decision history
- report generation
- Arabic/English localization
- audit/provenance
- artifact hashing
- exportable case history

### Explicitly out of scope for Phase 1

- structural/symbolic variant normalization
- multiallelic splitting inside SIRALOOM until a validated genotype-remapping implementation is added
- FASTQ alignment
- FASTQ QC
- variant calling
- CNV calling
- SV calling
- RNA-seq analysis
- somatic AMP/ASCO/CAP classification
- automated clinical sign-out
- regulatory certification claims
- central hosting of customer genomic datasets
- redistribution of third-party restricted databases
- automatic ethnicity inference used as clinical truth

---

# 4. Core Domain Model

The domain hierarchy is:

```text
Organization
  └── Case
       ├── Subject
       ├── Specimen
       ├── Assay
       ├── Analysis
       │    ├── Input Artifacts
       │    ├── Workflow
       │    ├── Tool Runs
       │    ├── Variants
       │    ├── Annotations
       │    ├── Population Observations
       │    ├── Evidence
       │    ├── ACMG Assessments
       │    ├── Review
       │    └── Reports
       │
       ├── Reanalysis
       └── Audit/Provenance History
```

## 4.1 Canonical entities

### Case

The permanent root of laboratory work.

### Analysis

A versioned execution state against a specific input and software/resource configuration.

### Artifact

A file or machine-readable object produced or consumed by an analysis.

### Variant

A canonical biological variation identity independent of provider output.

### Annotation

An observation supplied by an annotation resource/provider.

### Population Observation

Population-specific allele-frequency/allele-count observation.

### Evidence

A traceable evidentiary assertion about a variant.

### ACMG Assessment

An evaluation of an ACMG/AMP criterion for a specific variant under a specific rule/framework version.

### Review Action

A human or authorized system action affecting interpretation state.

### Report

An immutable rendered output derived from a specific analysis/interpretation state.

### Provenance Record

Relationship describing how a resource was generated or transformed.

### Audit Event

An event recording what happened operationally.

---

# 5. Architectural Style

## 5.1 Phase 1 architecture

Use a **modular monolith + worker architecture**.

```text
Web UI
  ↓
API Gateway / FastAPI
  ↓
Application Services
  ↓
Domain Modules
  ↓
PostgreSQL
  ↓
Artifact Store

Long-running tasks
  ↓
Task Queue
  ↓
Workers
  ↓
Tool/Provider adapters
```

Recommended initial stack:

```text
Frontend:
Next.js + TypeScript

Backend:
Python + FastAPI + Pydantic

Persistence:
PostgreSQL

Async execution:
Celery-compatible task interface
Redis as initial broker/result infrastructure

Artifacts:
Local filesystem in development/on-prem
S3-compatible object storage abstraction for future deployment

Containers:
Docker

Reporting:
HTML → PDF renderer, plus machine-readable JSON

Authentication:
OIDC-compatible architecture; local development auth may be simplified
```

The application MUST NOT expose infrastructure-specific details in the domain layer.

## 5.2 Why modular monolith first

This avoids:

- premature microservices
- duplicated models
- distributed transactions
- complex local deployment
- unnecessary network boundaries

Yet preserves bounded modules and explicit contracts so future extraction into services remains possible.

---

# 6. Exact Repository Structure

```text
siraloom/
├── README.md
├── LICENSE
├── pyproject.toml
├── package.json
├── .env.example
├── docker-compose.yml
├── Makefile
│
├── docs/
│   ├── architecture/
│   │   ├── context.md
│   │   ├── container.md
│   │   ├── domain-boundaries.md
│   │   └── decisions/
│   ├── contracts/
│   │   ├── openapi/
│   │   ├── json-schema/
│   │   └── events/
│   ├── scientific/
│   │   ├── acmg/
│   │   ├── clingen/
│   │   └── evidence/
│   ├── validation/
│   └── operations/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   │
│   │   ├── api/
│   │   │   ├── v1/
│   │   │   │   ├── cases.py
│   │   │   │   ├── analyses.py
│   │   │   │   ├── variants.py
│   │   │   │   ├── annotations.py
│   │   │   │   ├── populations.py
│   │   │   │   ├── evidence.py
│   │   │   │   ├── reviews.py
│   │   │   │   ├── reports.py
│   │   │   │   ├── resources.py
│   │   │   │   ├── audit.py
│   │   │   │   └── health.py
│   │   │   └── errors.py
│   │   │
│   │   ├── domain/
│   │   │   ├── case/
│   │   │   ├── analysis/
│   │   │   ├── variant/
│   │   │   ├── annotation/
│   │   │   ├── population/
│   │   │   ├── evidence/
│   │   │   ├── interpretation/
│   │   │   ├── review/
│   │   │   ├── report/
│   │   │   ├── provenance/
│   │   │   └── audit/
│   │   │
│   │   ├── application/
│   │   │   ├── commands/
│   │   │   ├── queries/
│   │   │   └── services/
│   │   │
│   │   ├── infrastructure/
│   │   │   ├── db/
│   │   │   ├── artifacts/
│   │   │   ├── events/
│   │   │   ├── auth/
│   │   │   └── logging/
│   │   │
│   │   └── adapters/
│   │       ├── annotation/
│   │       │   ├── base.py
│   │       │   ├── genebe.py
│   │       │   ├── vep.py
│   │       │   ├── clinvar.py
│   │       │   ├── gnomad.py
│   │       │   ├── spliceai.py
│   │       │   └── dbsnp.py
│   │       ├── population/
│   │       ├── evidence/
│   │       └── reporting/
│   │
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       ├── security/
│       └── fixtures/
│
├── frontend/
│   ├── app/
│   ├── components/
│   ├── features/
│   │   ├── cases/
│   │   ├── variants/
│   │   ├── evidence/
│   │   ├── review/
│   │   ├── population/
│   │   └── reports/
│   ├── lib/
│   ├── i18n/
│   │   ├── en.json
│   │   └── ar.json
│   └── tests/
│
├── schemas/
│   ├── api/
│   ├── events/
│   ├── variant/
│   ├── annotation/
│   ├── population/
│   ├── evidence/
│   ├── acmg/
│   ├── review/
│   ├── reports/
│   └── provenance/
│
├── migrations/
│
├── workflows/
│   └── variant/
│       └── v1.yaml
│
├── configs/
│   ├── development/
│   ├── testing/
│   └── onprem/
│
├── scripts/
│   ├── validate_resource.py
│   ├── verify_checksums.py
│   └── export_case.py
│
└── infra/
    ├── docker/
    └── deployment/
```

This directory structure is a contract. Changes to foundational locations require impact analysis.

---

# 7. Database Strategy

PostgreSQL is the system of record.

Large genomic files MUST NOT be stored as PostgreSQL byte blobs.

Store file metadata and hashes in PostgreSQL; store the physical artifact in an artifact store.

---

# 8. Database Schema — Core Tables

## 8.1 organizations

```sql
CREATE TABLE organizations (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    external_identifier TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
```

## 8.2 users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    external_subject TEXT,
    email TEXT,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
```

## 8.3 cases

```sql
CREATE TABLE cases (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    case_identifier TEXT NOT NULL,
    status TEXT NOT NULL,
    clinical_context JSONB,
    language TEXT NOT NULL DEFAULT 'en',
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    UNIQUE (organization_id, case_identifier)
);
```

## 8.4 specimens

```sql
CREATE TABLE specimens (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id),
    specimen_identifier TEXT,
    specimen_type TEXT,
    collection_datetime TIMESTAMPTZ,
    received_datetime TIMESTAMPTZ,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
```

## 8.5 assays

```sql
CREATE TABLE assays (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    assay_type TEXT NOT NULL,
    configuration JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```

## 8.6 analyses

```sql
CREATE TABLE analyses (
    id UUID PRIMARY KEY,
    case_id UUID NOT NULL REFERENCES cases(id),
    parent_analysis_id UUID REFERENCES analyses(id),
    analysis_type TEXT NOT NULL,
    workflow_id TEXT NOT NULL,
    workflow_version TEXT NOT NULL,
    status TEXT NOT NULL,
    reference_build TEXT NOT NULL,
    configuration JSONB NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL
);
```

No analysis row may be mutated to represent a different scientific run.

## 8.7 artifacts

```sql
CREATE TABLE artifacts (
    id UUID PRIMARY KEY,
    analysis_id UUID REFERENCES analyses(id),
    case_id UUID NOT NULL REFERENCES cases(id),
    artifact_type TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT,
    size_bytes BIGINT NOT NULL,
    sha256 TEXT NOT NULL,
    storage_uri TEXT NOT NULL,
    genome_build TEXT,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL
);
```

## 8.8 tool_runs

```sql
CREATE TABLE tool_runs (
    id UUID PRIMARY KEY,
    analysis_id UUID NOT NULL REFERENCES analyses(id),
    tool_name TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    container_digest TEXT,
    command_fingerprint TEXT,
    parameters JSONB,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    exit_code INTEGER,
    stdout_artifact_id UUID REFERENCES artifacts(id),
    stderr_artifact_id UUID REFERENCES artifacts(id),
    created_at TIMESTAMPTZ NOT NULL
);
```

Sensitive command-line content MUST NOT be logged if it contains credentials/secrets.

---

# 9. Canonical Variant Schema

Variant identity MUST be provider-independent.

```json
{
  "variant_id": "VAR-uuid",
  "genome": {
    "assembly": "GRCh38",
    "chromosome": "17",
    "position": 43000000,
    "reference": "C",
    "alternate": "T"
  },
  "representation": {
    "normalization_status": "NORMALIZED",
    "left_normalized": true
  },
  "identifiers": {
    "ga4gh_vrs": null,
    "dbsnp": null,
    "clinvar_variation_id": null
  }
}
```

Mandatory invariant:

```text
Same normalized genomic allele
+
same assembly
=
same canonical variant identity
```

Different provider representations MUST be normalized into the same internal identity where scientifically equivalent.

---

# 9A. Phase 1 Normalization Contract

SIRALOOM Variant now performs a real reference-aware normalization step when a validated FASTA + .fai index is configured. The normalizer:

1. validates that the VCF REF allele matches the reference sequence;
2. resolves `chr`/non-`chr` aliases and mitochondrial M/MT aliases where present;
3. performs minimal VCF representation without allowing an allele to become empty;
4. left-aligns supported simple indels in repetitive sequence contexts;
5. rejects symbolic/non-DNA alleles in this Phase 1 path;
6. rejects multiallelic records rather than silently changing sample genotype semantics;
7. emits a normalized VCF artifact and records the original representation;
8. creates a deterministic canonical key and stable SIRALOOM variant identity.

A missing reference FASTA or missing `.fai` is a workflow blocking condition, not an invitation to treat raw parsing as normalization.

# 10. Annotation Schema

Annotation is an observation, not an interpretation.

```json
{
  "annotation_id": "ANN-uuid",
  "variant_id": "VAR-uuid",
  "analysis_id": "ANL-uuid",

  "provider": {
    "name": "GeneBe",
    "adapter_version": "1.0.0"
  },

  "resource": {
    "name": "ClinVar",
    "version": "release-id",
    "source": "GeneBe"
  },

  "gene": {
    "symbol": "BRCA1",
    "entrez_id": null
  },

  "transcript": {
    "accession": "NM_007294.4",
    "source": "MANE",
    "is_canonical": true
  },

  "consequence": {
    "sequence_ontology_terms": [
      "missense_variant"
    ],
    "severity": "MODERATE"
  },

  "hgvs": {
    "coding": "NM_007294.4:c.X",
    "protein": "NP_009225.3:p.X"
  },

  "clinical": {},
  "population": {},
  "computational": {},
  "splice": {},

  "source_record": {},
  "created_at": "..."
}
```

The original provider payload MUST be retained when licensing/terms permit, or a sufficient normalized provenance record MUST be retained when raw payload retention is not permitted.

---

# 11. Annotation Provider Contract

All providers implement the same logical interface.

```python
class AnnotationProvider(Protocol):

    @property
    def provider_id(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    def capabilities(self) -> set[str]: ...

    def annotate(
        self,
        variants: list[CanonicalVariant],
        context: AnnotationContext,
    ) -> AnnotationBatchResult: ...
```

Provider types:

```text
GeneBeProvider
VEPProvider
ClinVarProvider
GnomADProvider
SpliceAIProvider
DbSNPProvider
```

The domain layer MUST NOT import GeneBe/VEP-specific classes.

---

# 12. GeneBe Provider Contract

Phase 1 development provider:

```text
Input:
normalized variants

Transport:
GeneBe API / supported client

Output:
SIRALOOM normalized annotation

Required provenance:
provider name
endpoint/API version where available
request timestamp
response timestamp
variant input hash
returned resource versions
adapter version
error/retry status
```

GeneBe API credentials MUST come from secrets/configuration, never source control.

The provider MUST use the documented batch endpoint and preserve the returned provider payload. GeneBe documents `omitNormalization`, transcript selection controls, ACMG output, and the current response fields including gnomAD-derived population frequency, ClinVar, consequence, splice and computational fields.

The provider MUST have a feature flag/configuration that allows disabling cloud annotation.

This allows:

```text
Research:
GeneBe enabled

On-prem:
GeneBe disabled
local providers enabled
```

---

# 13. Population Resource Model

Population is hierarchical:

```text
Global
  └── Broad ancestry
       └── Region
            └── Country
                 └── Laboratory cohort
```

Example:

```text
Global
Middle Eastern
GCC
Saudi Arabia
UAE
Qatar
Kuwait
Bahrain
Oman
Local laboratory cohort
```

Important distinction:

```text
gnomAD Middle Eastern
≠
Saudi Arabia
```

The gnomAD Middle Eastern value MUST never be stored under a Saudi country code.

---

# 13A. Current gnomAD Integration Strategy

Two population-access patterns are supported conceptually:

- GeneBe-derived global frequency during permitted development/research use. GeneBe currently documents `frequency_reference_population` as its current aggregate population frequency based on gnomAD total exome + genome data; SIRALOOM records this as provider-derived GLOBAL evidence and never labels it as Middle Eastern or country-specific.
- Direct gnomAD population lookup through the public GraphQL API for targeted Phase 1 development/reviewer workloads. The direct adapter extracts the `mid` ancestry group as population code `MID` / label `Middle Eastern` when returned by the configured dataset.

Bulk production annotation should use a validated local indexed gnomAD resource when the laboratory has an authorized resource. The local adapter targets bgzip + tabix indexed VCFs and uses allele-specific `AC/AN/AF/nhomalt` fields, including `*_mid` for the Middle Eastern group where present.

SIRALOOM never infers Saudi/UAE/Qatar/etc. frequency from the broad gnomAD Middle Eastern group. Country-specific resources are separate population resources.

# 14. Population Resource Schema

```json
{
  "resource_id": "POPRES-uuid",
  "name": "gnomAD",
  "provider": "gnomAD",
  "resource_type": "POPULATION_FREQUENCY",
  "version": "4.x",
  "genome_build": "GRCh38",
  "access_method": "LOCAL|API|SECURE_REMOTE",
  "license": "recorded-license",
  "population_definition": {
    "level": "ANCESTRY",
    "code": "MID",
    "label": "Middle Eastern"
  },
  "status": "AVAILABLE"
}
```

Resource status MUST support:

```text
AVAILABLE
NOT_CONFIGURED
NOT_AVAILABLE
ACCESS_DENIED
QUERY_FAILED
DISABLED
```

---

# 15. Population Observation Schema

```json
{
  "population_observation_id": "POBS-uuid",
  "variant_id": "VAR-uuid",
  "resource_id": "POPRES-uuid",

  "population": {
    "level": "ANCESTRY",
    "code": "MID",
    "label": "Middle Eastern"
  },

  "allele_count": 4,
  "allele_number": 120000,
  "allele_frequency": 0.0000333333,
  "homozygote_count": 0,

  "genome_build": "GRCh38",
  "resource_version": "4.x",

  "quality": {
    "status": "PASS"
  },

  "provenance": {
    "retrieved_at": "...",
    "source": "gnomAD"
  }
}
```

Critical invariant:

```text
NO DATA ≠ AF = 0
```

A missing population resource is represented by null/availability state, never by zero.

---

# 16. Population Query Contract

```http
POST /api/v1/populations/query
```

Request:

```json
{
  "analysis_id": "ANL-uuid",
  "variant_ids": [
    "VAR-uuid-1",
    "VAR-uuid-2"
  ],
  "requested_populations": [
    "GLOBAL",
    "MID",
    "SAU",
    "ARE"
  ]
}
```

Response:

```json
{
  "request_id": "POPQ-uuid",
  "status": "COMPLETED",
  "observations": [
    {
      "variant_id": "VAR-uuid-1",
      "population": "GLOBAL",
      "availability": "AVAILABLE",
      "allele_frequency": 0.00001
    },
    {
      "variant_id": "VAR-uuid-1",
      "population": "SAU",
      "availability": "NOT_CONFIGURED",
      "allele_frequency": null
    }
  ]
}
```

---

# 17. Evidence Model

Evidence is a separately versioned entity.

```json
{
  "evidence_id": "EVD-uuid",
  "variant_id": "VAR-uuid",
  "analysis_id": "ANL-uuid",

  "type": "POPULATION",

  "assertion": {
    "statement": "Variant is rare in configured population resource.",
    "direction": "SUPPORTS"
  },

  "source": {
    "name": "gnomAD",
    "version": "4.x",
    "record_id": "..."
  },

  "observations": [
    "POBS-uuid"
  ],

  "created_by": {
    "type": "system",
    "id": "population-engine"
  },

  "created_at": "..."
}
```

Evidence types MUST include, at minimum:

```text
POPULATION
CLINICAL_DATABASE
FUNCTIONAL
COMPUTATIONAL
SPLICING
SEGREGATION
DE_NOVO
CASE_LEVEL
GENE_DISEASE
LITERATURE
PHENOTYPE
LABORATORY
```

---

# 18. ACMG Assessment Schema

Each ACMG criterion is a separately versioned assessment.

```json
{
  "assessment_id": "ACMG-uuid",
  "variant_id": "VAR-uuid",
  "analysis_id": "ANL-uuid",

  "framework": {
    "name": "ACMG/AMP",
    "version": "2015"
  },

  "specification": {
    "provider": "ClinGen",
    "specification_id": null,
    "version": null
  },

  "criterion": "PM2",

  "automated_assessment": {
    "applicable": true,
    "strength": "MODERATE",
    "status": "PROPOSED",
    "reasoning": "...",
    "evidence_ids": [
      "EVD-uuid"
    ]
  },

  "reviewed_assessment": null,

  "final_assessment": null,

  "created_at": "...",
  "updated_at": "..."
}
```

Status values:

```text
NOT_ASSESSED
NOT_APPLICABLE
PROPOSED
ACCEPTED
REJECTED
MODIFIED
PENDING_REVIEW
```

Strength values:

```text
VERY_STRONG
STRONG
MODERATE
SUPPORTING
```

Additional criterion-specific metadata may be stored in a structured `details` field.

---

# 19. ACMG Classification Object

```json
{
  "classification_id": "CLS-uuid",
  "variant_id": "VAR-uuid",
  "analysis_id": "ANL-uuid",

  "framework": "ACMG/AMP",
  "framework_version": "2015",

  "result": "LIKELY_PATHOGENIC",

  "criteria": [
    {
      "criterion": "PVS1",
      "strength": "VERY_STRONG",
      "assessment_id": "ACMG-uuid"
    },
    {
      "criterion": "PM2",
      "strength": "MODERATE",
      "assessment_id": "ACMG-uuid"
    }
  ],

  "state": "PROPOSED",
  "review_status": "PENDING",

  "created_at": "..."
}
```

A proposed automated classification MUST be distinguishable from a human-approved final classification.

---

# 20. Evidence-to-Criterion Traceability

Every ACMG criterion MUST be traceable to supporting evidence.

```text
ACMG criterion
  ↓
Evidence ID
  ↓
Observation/source
  ↓
Database/version
  ↓
Raw/normalized value
```

The reviewer must be able to navigate:

```text
PM2
 ↓
gnomAD observation
 ↓
gnomAD release
 ↓
frequency data
```

without searching manually.

---

# 21. Reviewer Workflow

The review system is human-in-the-loop.

State machine:

```text
DRAFT
 ↓
AUTOMATED_ASSESSMENT
 ↓
PENDING_REVIEW
 ↓
IN_REVIEW
 ├── REQUEST_MORE_EVIDENCE
 │       ↓
 │   PENDING_REVIEW
 │
 ├── MODIFY_EVIDENCE
 │       ↓
 │   REASSESS
 │
 └── COMPLETE_REVIEW
         ↓
      APPROVED
         ↓
      REPORTABLE
```

A report SHOULD NOT be finalized from an unreviewed automated clinical interpretation state unless the laboratory explicitly configures and validates such a workflow.

---

# 22. Reviewer Actions

Minimum supported actions:

```text
OPEN_CASE
OPEN_VARIANT
ACCEPT_CRITERION
REJECT_CRITERION
MODIFY_CRITERION
ADD_EVIDENCE
REMOVE_EVIDENCE_FROM_ASSESSMENT
ADD_COMMENT
REQUEST_MORE_EVIDENCE
CHANGE_CLASSIFICATION
APPROVE_CLASSIFICATION
REJECT_CLASSIFICATION
FINALIZE_REPORT
SUPERSEDE_REPORT
REOPEN_CASE
REQUEST_REANALYSIS
```

Every action generates an audit event.

---

# 23. No Destructive Editing

Never:

```text
PM2 Supporting
→ overwrite with Moderate
```

Instead:

```text
Assessment v1
PM2 = Supporting

Reviewer action
PM2 changed

Assessment v2
PM2 = Moderate
Reason = ...
Reviewer = ...
Timestamp = ...
```

Historical records remain immutable.

---

# 24. Universal Event Schema

Every event MUST contain:

```json
{
  "event_id": "EVT-uuid",
  "event_version": "1.0",

  "event_type": "ACMG_CRITERION_MODIFIED",

  "case_id": "CASE-uuid",
  "analysis_id": "ANL-uuid",

  "actor": {
    "type": "HUMAN|SYSTEM|SERVICE|DEVICE",
    "id": "..."
  },

  "occurred_at": "...",
  "recorded_at": "...",

  "subject": {
    "type": "VARIANT|ARTIFACT|EVIDENCE|REPORT|CASE",
    "id": "..."
  },

  "action": {
    "operation": "UPDATE",
    "before": {},
    "after": {}
  },

  "reason": "...",

  "inputs": [
    {
      "artifact_id": "ART-uuid",
      "sha256": "..."
    }
  ],

  "outputs": [
    {
      "artifact_id": "ART-uuid",
      "sha256": "..."
    }
  ],

  "software": {
    "name": "SIRALOOM",
    "version": "1.0.0"
  },

  "workflow": {
    "id": "variant-v1",
    "version": "1.0"
  },

  "resource_versions": {},

  "correlation_id": "...",

  "metadata": {}
}
```

---

# 25. Audit Event Taxonomy

## Data events

```text
CASE_CREATED
SPECIMEN_REGISTERED
ARTIFACT_IMPORTED
ARTIFACT_HASHED
ARTIFACT_EXPORTED
ARTIFACT_DELETED_REQUESTED
```

## Computational events

```text
WORKFLOW_CREATED
WORKFLOW_STARTED
WORKFLOW_COMPLETED
WORKFLOW_FAILED
TOOL_STARTED
TOOL_COMPLETED
TOOL_FAILED
```

## Annotation events

```text
ANNOTATION_STARTED
ANNOTATION_COMPLETED
ANNOTATION_FAILED
RESOURCE_QUERIED
RESOURCE_UPDATED
```

## Evidence events

```text
EVIDENCE_CREATED
EVIDENCE_UPDATED
EVIDENCE_RETIRED
```

## Interpretation events

```text
ACMG_ASSESSMENT_CREATED
ACMG_CRITERION_PROPOSED
ACMG_CRITERION_MODIFIED
CLASSIFICATION_PROPOSED
CLASSIFICATION_CHANGED
```

## Review events

```text
REVIEW_STARTED
REVIEW_COMMENT_ADDED
REVIEW_DECISION_RECORDED
REVIEW_COMPLETED
```

## Reporting events

```text
REPORT_GENERATED
REPORT_APPROVED
REPORT_SIGNED
REPORT_SUPERSEDED
REPORT_EXPORTED
```

## Reanalysis events

```text
REANALYSIS_REQUESTED
REANALYSIS_STARTED
REANALYSIS_COMPLETED
REANALYSIS_REVIEW_REQUIRED
```

---

# 26. Provenance Model

Provenance captures:

```text
Entity
  ↓
Activity
  ↓
Agent
```

Example:

```text
Annotated VCF
  wasGeneratedBy
Annotation Run
  wasAssociatedWith
SIRALOOM Annotation Service
  used
Input VCF
  used
ClinVar release X
  used
gnomAD release Y
```

The model SHOULD be map-compatible with:

- FHIR Provenance
- FHIR AuditEvent
- W3C PROV concepts

---

# 27. Artifact Lineage

Every generated artifact MUST have a lineage chain.

```text
input.vcf
 ↓
normalized.vcf
 ↓
annotated.vcf
 ↓
evidence.json
 ↓
interpretation.json
 ↓
report.pdf
```

Each edge records:

```text
input artifact
activity
software
version
parameters
output artifact
```

---

# 28. Hashing Policy

Mandatory SHA-256 hashes for:

- imported VCF
- normalized VCF
- annotation output
- evidence package
- final report
- exported case package
- any externally supplied reference/resource artifact where practical

Checksum manifest:

```text
SHA256SUMS.txt
```

Example:

```text
abc123...  input.vcf
def456...  normalized.vcf
ghi789...  evidence.json
jkl012...  report.pdf
```

---

# 29. Resource Registry

All external resources used in scientific computation MUST be registered.

```json
{
  "resource_id": "RES-uuid",
  "name": "gnomAD",
  "provider": "gnomAD",
  "version": "4.x",
  "resource_type": "POPULATION_DATABASE",
  "genome_build": "GRCh38",
  "access_method": "LOCAL_DATABASE",
  "license": "...",
  "checksum": "...",
  "installation_path": "/resources/gnomad",
  "status": "VALIDATED",
  "validated_at": "...",
  "metadata": {}
}
```

No annotation run may rely on an unregistered production resource.

---

# 30. API Versioning

All public APIs start at:

```text
/api/v1/
```

Breaking changes require:

```text
/api/v2/
```

Existing API versions remain functional for their supported lifecycle.

---

# 31. Core API Contracts

## 31.1 Create case

```http
POST /api/v1/cases
```

Request:

```json
{
  "case_identifier": "LVP-000001",
  "language": "en",
  "clinical_context": {
    "indication": "..."
  }
}
```

Response:

```json
{
  "case_id": "CASE-uuid",
  "status": "DRAFT",
  "created_at": "..."
}
```

---

## 31.2 Upload/import artifact

```http
POST /api/v1/cases/{case_id}/artifacts
```

Response:

```json
{
  "artifact_id": "ART-uuid",
  "artifact_type": "VCF",
  "sha256": "...",
  "validation_status": "PENDING"
}
```

---

## 31.3 Create analysis

```http
POST /api/v1/cases/{case_id}/analyses
```

Request:

```json
{
  "analysis_type": "VARIANT_INTERPRETATION",
  "input_artifact_id": "ART-uuid",
  "workflow_id": "variant-v1",
  "workflow_version": "1.0",
  "reference_build": "GRCh38",
  "configuration": {}
}
```

Response:

```json
{
  "analysis_id": "ANL-uuid",
  "status": "CREATED"
}
```

---

## 31.4 Start analysis

```http
POST /api/v1/analyses/{analysis_id}/start
```

Response:

```json
{
  "analysis_id": "ANL-uuid",
  "status": "QUEUED"
}
```

---

## 31.5 Get analysis

```http
GET /api/v1/analyses/{analysis_id}
```

Returns:

```text
analysis metadata
workflow
status
artifacts
tool runs
annotation status
population status
evidence status
review status
report status
```

---

## 31.6 List variants

```http
GET /api/v1/analyses/{analysis_id}/variants
```

Query parameters:

```text
classification
gene
consequence
population
review_status
page
page_size
```

---

## 31.7 Get variant

```http
GET /api/v1/variants/{variant_id}
```

Response combines:

```text
canonical identity
annotations
population observations
evidence
ACMG assessments
review state
```

---

## 31.8 Get evidence

```http
GET /api/v1/variants/{variant_id}/evidence
```

---

## 31.9 Get ACMG assessment

```http
GET /api/v1/variants/{variant_id}/acmg
```

---

## 31.10 Modify ACMG criterion

```http
POST /api/v1/variants/{variant_id}/acmg/{criterion}/review
```

Request:

```json
{
  "decision": "MODIFY",
  "strength": "MODERATE",
  "reason": "Reviewed population-specific evidence.",
  "evidence_ids": [
    "EVD-uuid"
  ]
}
```

The API MUST reject modifications without:

```text
authorized reviewer
reason
valid evidence/state
version context
```

---

## 31.11 Generate report

```http
POST /api/v1/analyses/{analysis_id}/reports
```

Request:

```json
{
  "report_type": "CLINICAL_INTERPRETATION",
  "language": "en",
  "include_full_evidence": false
}
```

Response:

```json
{
  "report_id": "RPT-uuid",
  "status": "GENERATING"
}
```

---

## 31.12 Export case history

```http
POST /api/v1/cases/{case_id}/exports
```

Request:

```json
{
  "format": "FULL_CASE_PACKAGE",
  "include_artifacts": true,
  "include_reports": true,
  "include_evidence": true,
  "include_audit": true,
  "include_provenance": true
}
```

Response:

```json
{
  "export_id": "EXP-uuid",
  "status": "QUEUED"
}
```

---

# 32. Error Contract

All API errors use:

```json
{
  "error": {
    "code": "RESOURCE_NOT_CONFIGURED",
    "message": "The requested Saudi population resource is not configured.",
    "request_id": "REQ-uuid",
    "details": {}
  }
}
```

Error codes are stable API contracts.

---

# 33. Idempotency

Operations that create expensive or persistent work MUST support idempotency.

Examples:

```text
POST /analyses
POST /analysis/start
POST /reports
POST /exports
POST /population/query
```

Use:

```http
Idempotency-Key: <client-generated-key>
```

Repeated requests with the same key MUST NOT create duplicate scientific analyses.

---

# 34. Concurrency Rules

A case may have multiple historical analyses, but:

- only one analysis may hold a given active workflow lock unless explicitly supported
- artifact writes must be content-addressed or uniquely versioned
- review state transitions must be transactionally protected
- finalization must use optimistic concurrency/version checks

Example:

```text
review_version = 7
```

A reviewer submitting version 6 against version 7 MUST receive a conflict, not silently overwrite the newer state.

---

# 35. Report Schema

A final report object:

```json
{
  "report_id": "RPT-uuid",
  "case_id": "CASE-uuid",
  "analysis_id": "ANL-uuid",

  "report_version": 1,
  "supersedes_report_id": null,

  "language": "en",

  "patient": {},
  "specimen": {},
  "test": {},

  "summary": {
    "overall_result": "..."
  },

  "findings": [
    {
      "variant_id": "VAR-uuid",
      "gene": "BRCA1",
      "hgvs_c": "NM_007294.4:c.X",
      "hgvs_p": "NP_009225.3:p.X",
      "zygosity": "HETEROZYGOUS",
      "classification": "LIKELY_PATHOGENIC",
      "interpretation": "..."
    }
  ],

  "evidence_summary": [],
  "methodology": "...",
  "limitations": "...",
  "recommendations": "...",
  "references": [],

  "provenance": {
    "analysis_id": "ANL-uuid",
    "workflow_version": "1.0",
    "database_versions": {}
  },

  "approval": {
    "status": "APPROVED",
    "reviewer_id": "USER-uuid",
    "approved_at": "..."
  }
}
```

---

# 36. Report Layers

SIRALOOM MUST produce different representations.

## A. Reviewer view

Detailed:

```text
variant
annotation
population
evidence
ACMG
literature
review history
```

## B. Clinical report

Concise and readable:

```text
result
interpretation
supporting evidence
method
limitations
references
sign-out
```

## C. Machine-readable report

Stable JSON structure for integrations.

## D. Complete case history

Full audit/provenance export.

---

# 37. Arabic / English Architecture

The clinical data model remains language-independent.

Localization:

```text
frontend/i18n/en.json
frontend/i18n/ar.json
```

Reports:

```text
English
Arabic
Bilingual
```

The following MUST NOT be translated in a way that changes machine semantics:

- HGVS
- gene symbol
- transcript identifier
- database ID
- ACMG criterion code
- genome build
- artifact hash
- version identifiers

Clinical Arabic terminology requires controlled terminology review before claiming clinical deployment.

---

# 38. Security Baseline

Phase 1 MUST include:

### Authentication

- authenticated users
- session/token expiry
- password-based authentication only as a temporary development mechanism
- OIDC-compatible architecture

### Authorization

RBAC minimum:

```text
ADMIN
LAB_MANAGER
ANALYST
REVIEWER
MEDICAL_REVIEWER
AUDITOR
READ_ONLY
```

### Case isolation

Every query MUST be scoped to organization/tenant.

### Secrets

Never store:

```text
GeneBe API key
database passwords
signing keys
cloud credentials
```

in source control.

### Encryption

- TLS in transit
- encrypted storage where deployment platform supports it
- encrypted backups

### Audit security

Audit records SHOULD be append-only and should reject ordinary UPDATE/DELETE operations.

FHIR documentation describes AuditEvent as event-oriented record keeping and recommends access controls around such records. https://hl7.org/fhir/R5/

---

# 39. Privacy Rules

SIRALOOM should minimize patient identifiers.

Preferred model:

```text
Case ID
Specimen ID
local pseudonymous identifiers
```

rather than unnecessary direct identifiers.

Clinical data sent to external annotation services MUST be prohibited by default unless the deployment explicitly enables it and the applicable contractual/privacy requirements are satisfied.

For the development GeneBe provider:

```text
No patient names
No direct identifiers
No unnecessary clinical narrative
```

Only the minimum variant information required for the permitted research/educational use should be sent.

---

# 40. Resource / Provider Capability Model

Each provider declares:

```json
{
  "provider_id": "genebe",
  "capabilities": [
    "ANNOTATION",
    "ACMG_CRITERIA_SUPPORT",
    "POPULATION"
  ],
  "access_mode": "API",
  "genome_builds": ["GRCh38"],
  "status": "ENABLED"
}
```

This enables dynamic resource selection.

Example:

```text
GeneBe enabled
VEP disabled
Local ClinVar enabled
Local gnomAD enabled
Saudi resource not configured
```

The system must still operate.

---

# 41. Resource Selection Policy

For each annotation category, the system resolves:

```text
1. explicitly configured local resource
2. institution-approved remote service
3. approved development provider
4. unavailable
```

The selected source MUST be recorded in provenance.

Never silently substitute a different resource.

---

# 42. Population Selection Policy

Requested population levels are determined by case context and configured resources.

Example Saudi context:

```text
GLOBAL
MID
SAU
LOCAL
```

If SAU is missing:

```text
GLOBAL
MID
SAU = NOT_CONFIGURED
LOCAL = NOT_CONFIGURED
```

The pipeline continues.

---

# 43. Reanalysis Foundation

Reanalysis is not a separate data model.

It uses:

```text
Case
 ├── Analysis v1
 └── Analysis v2
```

where v2 points to the prior analysis:

```text
parent_analysis_id
```

The reanalysis engine compares:

```text
old tool versions
new tool versions
old resource versions
new resource versions
old evidence
new evidence
old ACMG
new ACMG
old reviewer decisions
new reviewer decisions
old report
new report
```

---

# 44. Reanalysis Difference Object

```json
{
  "difference_id": "DIFF-uuid",
  "old_analysis_id": "ANL-old",
  "new_analysis_id": "ANL-new",

  "changes": [
    {
      "subject": "ACMG_CRITERION",
      "variant_id": "VAR-uuid",
      "criterion": "PM2",
      "before": "SUPPORTING",
      "after": "MODERATE",
      "reason": "New resource/evidence"
    }
  ]
}
```

This makes future reanalysis explainable rather than merely generating a new report.

CAP's NGS worksheets explicitly include considerations for variant reclassification and reanalysis strategies. https://www.cap.org/education/practice-hubs/next-generation-sequencing-ngs-worksheets/

---

# 45. Workflow Definition

Phase 1 workflow:

```yaml
id: variant-v1
version: "1.0"

steps:
  - id: validate_input
  - id: normalize
  - id: annotate
  - id: population
  - id: build_evidence
  - id: acmg_assessment
  - id: review
  - id: report
  - id: export_provenance
```

Each step has:

```yaml
id:
type:
input_contract:
output_contract:
retry_policy:
timeout:
provenance_required: true
```

No workflow step may produce a scientific artifact without registering the event and output artifact.

---

# 46. Workflow Failure Policy

Failures MUST be explicit.

Allowed statuses:

```text
PENDING
RUNNING
SUCCEEDED
FAILED
CANCELLED
BLOCKED
REQUIRES_REVIEW
```

A failed step MUST record:

```text
error code
error message
tool
version
input artifact
parameters fingerprint
timestamp
log artifact
```

A partial result MUST be labeled partial.

The UI MUST NEVER display a failed workflow as "complete."

---

# 47. Observability

Every request/task should carry:

```text
request_id
trace_id
case_id
analysis_id
actor_id
```

Logs MUST be structured JSON.

Example:

```json
{
  "timestamp": "...",
  "level": "INFO",
  "event": "ANNOTATION_COMPLETED",
  "case_id": "...",
  "analysis_id": "...",
  "duration_ms": 10234,
  "provider": "genebe",
  "adapter_version": "1.0.0"
}
```

Logs and audit events are related but not identical.

- Logs support operations/debugging.
- Audit events support accountable historical reconstruction.
- Provenance supports scientific lineage.

---

# 48. Testing Strategy

## Unit tests

Cover:

- VCF parsing
- normalization
- canonical variant identity
- population calculations
- evidence creation
- ACMG data model
- state transitions
- report transformation
- localization

## Contract tests

Cover:

- provider adapters
- API request/response schema
- event schema
- report schema

## Integration tests

Cover:

```text
VCF
→ DB
→ annotation provider
→ population
→ evidence
→ ACMG
→ review
→ report
```

## End-to-end tests

At least one complete synthetic/public test case must run from input VCF through downloadable report and provenance package.

## Security tests

Cover:

- tenant isolation
- unauthorized case access
- role enforcement
- secret leakage
- audit immutability
- malicious file upload
- path traversal
- oversized upload handling

---

# 49. Scientific Validation Strategy

Phase 1 MUST NOT be declared clinically validated simply because the software executes successfully.

Validation needs separate evidence for:

### Input validation

- accepted VCF versions
- required fields
- genome build
- malformed records
- missing sample information

### Variant normalization

- SNV
- indel
- multiallelic variants
- symbolic alleles where supported
- normalization edge cases

### Annotation validation

Known truth sets / independently verified examples.

### Population validation

Known variants with independently verified population frequencies.

### ACMG validation

Curated benchmark variants with expert-reviewed criterion assignments.

### Report validation

Verify every report field maps to the correct source record.

### Reproducibility validation

Same inputs + same workflow/resource snapshot → same result.

### Change validation

New versions MUST be demonstrably different only where expected.

---

# 50. Acceptance Criteria for Phase 1

Phase 1 is not complete until all are true:

```text
[ ] Valid VCF accepted
[ ] Invalid VCF rejected with actionable error
[ ] Genome build verified
[ ] Variant normalization completed
[ ] Canonical IDs created
[ ] Annotation provider works through adapter
[ ] Provider source/version preserved
[ ] gnomAD global population represented
[ ] gnomAD Middle Eastern population represented where available
[ ] Country-specific resource can be added without code changes
[ ] Missing population resource does not break analysis
[ ] Missing data is not treated as zero
[ ] Evidence records have source/version
[ ] ACMG criteria are versioned
[ ] Proposed vs reviewed classification separated
[ ] Reviewer edits create history
[ ] Report versions are immutable
[ ] English report works
[ ] Arabic report works
[ ] Audit events generated
[ ] Provenance lineage generated
[ ] SHA-256 artifact hashes generated
[ ] Full case package exported
[ ] API contract tests pass
[ ] Security tests pass
[ ] End-to-end test passes
[ ] Scientific benchmark validation completed for claimed scope
```

---

# 51. Non-Goals for v1

Do not add these because they "might be useful":

```text
microservices
Kubernetes requirement
central patient-data lake
AI clinical diagnosis
automatic ethnicity inference
automatic final clinical sign-out
massive embedded genomic database distribution
real-time cloud dependence
```

Each would require its own decision record.

---

# 52. Key Architectural Decisions

## ADR-001 — VCF-first boundary

**Decision:** Phase 1 starts at VCF.

**Reason:** Allows validation and completion of interpretation/reporting before adding upstream FASTQ complexity.

**Future compatibility:** FASTQ workflow terminates at VCF and feeds the same core.

**Reversibility:** High.

---

## ADR-002 — Provider abstraction

**Decision:** GeneBe/VEP/ClinVar/gnomAD/etc. are adapters.

**Reason:** Prevent vendor lock-in and support local laboratory resources.

**Reversibility:** High.

---

## ADR-003 — Modular monolith

**Decision:** One deployable application with clear bounded modules initially.

**Reason:** Lower operational complexity and safer on-prem deployment.

**Future:** Modules may become services only when justified.

---

## ADR-004 — PostgreSQL as system of record

**Decision:** Relational DB for metadata, domain state, evidence, review and audit indexes.

**Reason:** Strong consistency, transactions, queryability and mature tooling.

Large files remain external artifacts.

---

## ADR-005 — Immutable analyses/reports

**Decision:** Never overwrite historical scientific state.

**Reason:** Reanalysis, traceability and defensible history.

---

## ADR-006 — Universal audit/provenance

**Decision:** Platform-wide event/provenance layer.

**Reason:** Every future service must inherit consistent history.

---

## ADR-007 — Population resource abstraction

**Decision:** Population datasets are pluggable resources with explicit access/version/license metadata.

**Reason:** Different regions and laboratories have different resources and access mechanisms.

---

## ADR-008 — Arabic/English from foundation

**Decision:** Internationalization is built into the first release.

**Reason:** Retrofitting localization later creates data/UI inconsistencies.

---

# 53. Risks

## R1 — GeneBe dependency

**Risk:** Terms/API availability may change.

**Mitigation:** provider adapter + local provider path.

## R2 — Database licensing

**Risk:** "downloadable" does not necessarily mean "redistributable."

**Mitigation:** resource registry tracks license; do not bundle resources without verified rights.

## R3 — Clinical overclaim

**Risk:** Software could be mistaken for a certified diagnostic system.

**Mitigation:** explicit labeling; validation remains laboratory-specific; automated interpretation separated from human review.

## R4 — Silent resource drift

**Risk:** same case produces different results due to changed databases.

**Mitigation:** immutable resource versions, hashes, workflow versions.

## R5 — Audit tampering

**Risk:** historical review record can be modified.

**Mitigation:** append-only event model, restricted permissions, hash chaining/tamper-evidence where appropriate.

## R6 — Population misinterpretation

**Risk:** broad ancestry group treated as country-specific.

**Mitigation:** hierarchical population model and strict population codes.

## R7 — PHI leakage

**Risk:** patient information sent to external provider.

**Mitigation:** external-provider data minimization and off-by-default cloud annotation for clinical deployments.

---

# 54. Definition of Done

SIRALOOM Variant v1 is complete only when:

1. Requirements are implemented.
2. Domain boundaries are respected.
3. API contracts are versioned.
4. Database migrations are reproducible.
5. Scientific resources are versioned.
6. Annotation is traceable.
7. Evidence is traceable.
8. ACMG state is reviewable and versioned.
9. Human decisions are preserved.
10. Reports are reproducible.
11. Audit/provenance exports work.
12. English and Arabic rendering work.
13. Security controls are tested.
14. Scientific validation has been performed for the actual claimed scope.
15. Known limitations are documented.
16. Documentation matches implementation.
17. No untracked critical TODO remains.
18. The project ledger is updated.

---

# 55. Project Ledger — Current Baseline

## COMPLETED / APPROVED CONCEPTUALLY

- SIRALOOM is the platform name.
- SIRALOOM Variant is Service 01.
- Phase 1 is VCF → report.
- Phase 2 will be FASTQ → VCF → SIRALOOM Variant.
- Future deployments will support local/on-prem databases.
- GeneBe is a provider, not the permanent architecture.
- Population context is a first-class domain.
- gnomAD Middle Eastern ancestry is represented separately from country-specific GCC data.
- Country-specific population resources are optional.
- Arabic + English are foundation capabilities.
- Human review is part of the workflow.
- Audit + provenance are platform-wide foundations.
- Historical analyses/reports are immutable.
- Future services inherit the same case/provenance/versioning system.

## FROZEN

- Provider abstraction
- Case/Analysis/Artifact lineage
- Immutable analysis/report history
- Population hierarchy
- Universal event model
- VCF-first Phase 1 boundary
- Modular-monolith-first deployment strategy

## IN PROGRESS

- This technical specification

## NOT YET IMPLEMENTED

Everything in code.

## IMMEDIATE NEXT TASK

Convert this approved specification into the **Phase 1 implementation brief and repository scaffold**, then implement the smallest foundation in dependency order:

```text
1. Repository scaffold
2. Domain IDs + enums
3. PostgreSQL schema + migrations
4. Artifact/hash subsystem
5. universal event/provenance subsystem
6. VCF ingestion/validation contract
7. canonical variant model
8. provider interfaces
9. GeneBe research provider
10. population model/engine
11. evidence model
12. ACMG model
13. reviewer state machine
14. report model
15. end-to-end test fixture
```

No production annotation code should be written before the schema/contracts and migration baseline are created.

---

# 56. Immediate Validation Gate Before Coding

Before implementation begins, the following must be explicitly verified:

### Scientific

- Current GeneBe API contract and permitted use
- Exact gnomAD release/field mapping used for the development adapter
- ACMG/AMP criterion semantics
- applicable ClinGen specifications for the initial benchmark scope
- population-resource semantics

### Engineering

- PostgreSQL schema
- API contracts
- event schema
- artifact contract
- provider interface
- state machine

### Security

- secret management
- file upload limits
- tenant isolation
- audit access controls

### Product

- first supported VCF dialect
- supported genome build(s)
- exact initial report fields
- exact user roles

No downstream implementation should silently invent these.

---

# 57. First Test Case Strategy

Before using real clinical data, the initial test corpus should be:

```text
public / synthetic variants
+
known annotation expectations
+
known ACMG benchmark cases where licensing permits
```

The test corpus should include:

```text
SNV
multiallelic site
indel
rare variant
common variant
variant with ClinVar record
variant absent from population resource
variant present in Middle Eastern group
variant with missing country-specific resource
variant requiring reviewer modification
```

The test must demonstrate the critical invariant:

```text
No Saudi resource
→ pipeline still works
→ Saudi value = NOT_AVAILABLE
→ global/Middle Eastern evidence remains usable
```

---

# 58. Final System Vision

SIRALOOM Variant v1 is deliberately small in input scope but large in architectural responsibility.

```text
                       SIRALOOM
                          │
                  SIRALOOM Variant
                          │
         ┌────────────────┼─────────────────┐
         ▼                ▼                 ▼
      Variant          Population        Evidence
       Core              Core              Core
         │                │                 │
         └────────────────┼─────────────────┘
                          ▼
                    Interpretation
                          │
                          ▼
                       Review
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
           Report             Audit/Provenance
```

Later:

```text
SIRALOOM Pipeline
FASTQ → VCF
         │
         ▼
SIRALOOM Variant
```

Later:

```text
SIRALOOM Reanalysis
Historical Analysis
        ↓
new knowledge/resources
        ↓
difference
        ↓
review
        ↓
new report
```

The architecture is therefore designed so that:

> **Adding capability does not require sacrificing or rewriting the capabilities that already work.**

---

## Source Basis

1. ACMG/AMP sequence variant interpretation consensus:
   https://pubmed.ncbi.nlm.nih.gov/25741868/

2. ClinGen/ACMG specification overview:
   https://pubmed.ncbi.nlm.nih.gov/31479589/

3. CAP NGS Worksheets / CLSI MM09 context:
   https://www.cap.org/education/practice-hubs/next-generation-sequencing-ngs-worksheets/

4. HL7 FHIR Provenance:
   https://hl7.org/fhir/provenance.html

5. HL7 FHIR AuditEvent:
   https://fhir.hl7.org/fhir/auditevent-definitions.html

6. GA4GH Variation Representation:
   https://vrs.ga4gh.org/

7. GeneBe:
   https://genebe.net/
   https://genebe.net/api-showcase
   https://docs.genebe.net/

# 59. Long-Running Execution Foundation

Long-running analysis is asynchronous and durable. The browser is never the execution owner.

```text
UI -> API -> durable analysis/job -> scheduler -> worker -> artifacts + DB
```

The API returns an analysis ID immediately. Closing/reloading the browser does not stop analysis. Current status is reconstructed from persisted state. Each workflow step records status, attempt, timestamps, heartbeat and artifacts.

A worker failure MUST not erase a completed analysis. Completed steps MUST NOT be rerun unnecessarily. Resource limits, queueing, cancellation, retry and recovery are backend concerns.

# 60. Resource-Aware Concurrency

Workers are admitted according to declared CPU/RAM/disk requirements and available capacity. Multiple laboratory users therefore share a durable queue rather than competing directly for host resources.

# 61. Local Resource Manager

Laboratory tools and databases are registered with version, genome build, path/endpoint, access method, license metadata, checksum where applicable, and validation status. Workflows resolve only compatible resources.

# 62. Licensing / Entitlement Foundation

Billing is separate from scientific execution. SIRALOOM licensing uses signed entitlements/leases tied to installation identity, plan, features and limits. Local installations do not require a cloud call for every scientific operation. Expired licenses MUST NOT delete historical case/report/audit data.

# 63. Implementation Gate

The repository intentionally refuses to mark unvalidated downstream scientific steps as complete. Reference-aware normalization, pinned gnomAD `mid` extraction, complete ACMG/ClinGen rules, clinical review authorization, and production deployment validation remain gated until their evidence and benchmark tests are completed.

---

# 59. Criterion-Specific Evaluator Extension

This extension supersedes any implication that generic threshold heuristics may be used for PM2, BA1, BS1, PP3/BP4, or PVS1.

## 59.1 Rule requirements

Criterion automation MUST require an explicit, versioned rule profile. The engine MUST fail closed when a required parameter is absent.

## 59.2 PM2

PM2 automation requires at minimum:

- maximum allele-frequency threshold
- minimum allele-number threshold
- explicit population scope
- explicit strength

Absence of a population resource is indeterminate and MUST NOT be represented as allele frequency zero.

ClinGen's 2024 gnomAD v4 guidance states that VCEPs need to reassess PM2/BA1/BS1 thresholds when specifications were based on strict absence or comparator AFs, and notes that gnomAD v4 filtering allele frequency is used for BA1/BS1. Therefore SIRALOOM MUST NOT hard-code a universal clinical PM2 threshold. [Current guidance: ClinGen, June 2025 update and prior gnomAD v4 guidance.]

## 59.3 BA1/BS1

BA1 and BS1 require explicit specification-level thresholds. A resource-wide universal threshold is prohibited.

## 59.4 PP3/BP4

PP3/BP4 requires an explicitly calibrated predictor and score interval. SIRALOOM MUST NOT implement a generic rule such as `REVEL > 0.7 => PP3` without a specification that identifies the predictor, calibration dataset/approach, threshold, scope, and strength.

ClinGen's computational calibration work supports predictor-specific, evidence-calibrated strength assignments. 

## 59.5 PVS1

PVS1 requires an explicit assertion that loss of function is an established disease mechanism and an explicit supported consequence set. This evaluator is intentionally conservative and does not claim to implement the complete ClinGen PVS1 decision tree.

ClinGen's PVS1 recommendation specifically notes that ACMG/AMP 2015 did not fully specify the required considerations for variant type, location, likelihood of a true null effect, relative strengths, and gene applicability.

## 59.6 Specification registry

Criterion evaluators consume `CriterionSpecification` records. A future production implementation MUST register approved ClinGen/VCEP specifications separately, including:

```text
specification_id
provider
version
gene_scope
disease_scope
criterion
thresholds
population_scope
predictor_scope
allowed_variant_classes
exceptions
references
status
```

A specification that is not explicitly registered as `VALIDATED_FOR_USE` cannot be used for clinical automation.

## 59.7 Current status

Implemented in development:

- PM2 evaluator
- BA1 evaluator
- BS1 evaluator
- PP3 evaluator
- BP4 evaluator
- conservative PVS1 gate
- specification registry boundary
- evaluator unit tests

Not yet implemented/validated:

- production ClinGen VCEP specification ingestion
- full PVS1 decision tree
- disease-specific PM2/BA1/BS1 rules
- predictor-specific PP3/BP4 catalogue
- PS3/BS3 functional evidence calibration
- PP1/BS4 segregation
- PP4 phenotype
- PS2/PM6 de novo
- PM3 compound heterozygosity
- PS1/PM5 amino-acid/residue evidence
- clinical benchmark validation

## ClinGen CSpec Integration

SIRALOOM integrates with the public ClinGen Criteria Specification Registry (CSpec) through its documented JSON REST API. The current CSpec service identifies itself as a beta service and exposes entity types including `RuleSet`, `CriteriaCode`, `Gene`, `Disease`, and `SequenceVariantInterpretation`; its documentation defines identity/list endpoints, paging, IDs, and `detail` levels. CSpec is therefore treated as an external, versioned knowledge source, not as SIRALOOM's database.

SIRALOOM uses only documented endpoints and fails closed on unknown response shapes. A fetched `RuleSet` is stored as an immutable snapshot with its identifier, version, source IRI, modified timestamp, gene/disease scope, structured criteria when available, and raw response payload where retention is permitted.

**Activation rule:** importing a ClinGen specification does not make it active for automated clinical classification. `validated_for_automation` remains false until SIRALOOM performs its own controlled validation/approval process. This prevents accidental use of an unreviewed external ruleset.

The current authoritative ClinGen guidance index was last updated July 2025 and lists general and criteria-specific recommendations. ClinGen's Criteria Specification Registry also provides machine-readable specifications and maintains versioned VCEP records.

Sources: ClinGen Variant Classification Guidance; ClinGen File Downloads & APIs; CSpec API documentation.


# 59. ClinGen Specification Selection and Activation — v1.0

The ClinGen specification layer now has two separate responsibilities:

1. **Selection:** determine whether a previously imported, explicitly validated specification applies to a gene/disease context.
2. **Activation:** record that a specification snapshot has undergone SIRALOOM's structural/configuration review and is approved for automation in the deployment.

Selection is fail-closed:

```text
no applicable validated specification → NOT_FOUND
multiple equally specific validated specifications → AMBIGUOUS
single validated specification → SELECTED
```

Specificity order:

```text
gene + disease > gene-only
```

A disease-scoped specification does not match a different requested disease.

An unvalidated snapshot can never be selected for automation.

Activation records:

```text
validation_status
validated_by
validation_reason
validation_reference
validated_at
```

Structural/configuration activation is **not** a claim of clinical validation of the SIRALOOM implementation or of the laboratory assay.

Current implementation provides:

```http
GET  /api/v1/clingen/specifications/select?gene=...&disease=...
POST /api/v1/clingen/specifications/{id}/validate
```

The validation endpoint is an administrative development endpoint until the platform authentication/RBAC layer is production-ready. It MUST NOT be exposed as an unrestricted clinical-production endpoint.

---

# 59. Phase 1 UI / Execution Integration Addendum

## 59.1 User-facing workflow

The Phase 1 web interface provides a single laboratory-facing flow:

```text
Case
 → VCF intake
 → persistent artifact registration
 → durable analysis submission
 → server-side workflow monitoring
 → variant inspection
 → evidence inspection
 → human review
 → classification approval
 → report generation/finalization
 → case-history export
```

## 59.2 Browser-disconnect invariant

The browser MUST NOT own scientific execution state.

A browser refresh, navigation event, temporary network outage, or closed browser MUST NOT cancel a running analysis.

The database/workflow layer remains authoritative. The UI polls/reconnects to persisted state.

## 59.3 Large-upload invariant

The artifact ingestion path MUST stream uploads into persistent storage and calculate SHA-256 incrementally. It MUST NOT call `UploadFile.read()` to materialize a large VCF in application memory.

## 59.4 Export download

Case-history exports are asynchronous and expose:

```text
POST /api/v1/cases/{case_id}/exports
GET  /api/v1/exports/{export_id}
GET  /api/v1/exports/{export_id}/download
```

Only a completed export may be downloaded.

## 59.5 Artifact download

Persisted report and case artifacts can be retrieved through:

```text
GET /api/v1/artifacts/{artifact_id}/download
```

The local artifact store resolves only its own registered artifact URIs.

## 59.6 Review/report gate

The reviewer UI only enables classification approval after a review is explicitly started. The user-facing report generation action is gated on an approved classification.

## 59.7 Development authentication boundary

The Phase 1 UI uses the existing development identity layer and MUST NOT be considered production authentication/RBAC. Production deployment requires the dedicated identity and authorization implementation plus security validation.

## 59.8 Frontend dependency validation

The frontend source has been TypeScript-checked with temporary declaration stubs in this execution environment because Next.js/React packages are not installed locally and npm registry installation timed out. A real `next build` remains a deployment-environment validation requirement. No frontend production-build success is claimed by this addendum.
