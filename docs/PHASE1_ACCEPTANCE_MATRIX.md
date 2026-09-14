# SIRALOOM Variant — Phase 1 Acceptance Matrix

| Requirement | Implementation | Automated evidence | Live validation | Status |
|---|---|---|---|---|
| Valid VCF accepted | VCF parser + artifact ingestion | Backend tests | Required | PARTIAL |
| Invalid VCF rejected with actionable error | VCF validation + workflow failure state | Backend tests | Required | PARTIAL |
| Genome build explicit/verified | GRCh37/GRCh38 artifact metadata + normalization | Backend tests | Required | PARTIAL |
| Reference-aware normalization | Streaming normalizer | Backend tests | Required | PARTIAL |
| Canonical IDs created | Stable canonical key/UUID | Backend tests | Required | PARTIAL |
| Annotation through adapter | GeneBe adapter | Adapter/workflow tests | Required | PARTIAL |
| Provider source/version preserved | Annotation + audit provenance | Backend tests | Required | PARTIAL |
| Global population represented | Population observation model | Backend tests | Required | PARTIAL |
| Middle Eastern context represented when available | gnomAD MID adapter | Backend tests | Required | PARTIAL |
| Country resource can be added without core rewrite | Population provider architecture | Architecture/tests | Required for connector | PARTIAL |
| Missing population resource does not break analysis | Availability states | Backend tests | Required | PARTIAL |
| Missing ≠ zero | Population availability semantics | Backend tests | Required | PARTIAL |
| Evidence source/version preserved | Evidence model | Backend tests | Required | PARTIAL |
| ACMG criteria versioned | ACMG assessment/review history | Backend tests | Required | PARTIAL |
| Proposed vs reviewed classification separated | Review state machine | Backend tests | Required | PARTIAL |
| Reviewer edits create history | Versioned review/classification | Backend tests | Required | PARTIAL |
| Report versions immutable | Report version/supersession model | Backend tests | Required | PARTIAL |
| English report | Report renderer | Backend tests | Required | PARTIAL |
| Arabic report | RTL/localization foundation | Backend tests | Required | PARTIAL |
| Audit events generated | Audit service/hash chain | Backend tests | Required | PARTIAL |
| Provenance lineage generated | Artifact/workflow/resource lineage | Backend tests | Required | PARTIAL |
| SHA-256 artifact hashes | Artifact store | Backend tests | Required | PARTIAL |
| Full case package export | Export service | Backend tests | Required | PARTIAL |
| API contract tests | FastAPI/backend suite | CI | Required | PARTIAL |
| Security tests | Tenant/RBAC/auth tests | CI | Required | PARTIAL |
| End-to-end VCF → report | Workflow + UI | Integration tests | Required | NOT VALIDATED |
| Scientific benchmark validation | Validation corpus + expected outputs | Harness | Required | NOT VALIDATED |
| Live frontend/backend deployment | Vercel/public backend | CI/deployment | Required | NOT VALIDATED |

## Release rule

The GitHub repository may describe the software as a **Phase-1 release candidate** only while the rows marked PARTIAL/NOT VALIDATED remain explicitly disclosed. It may be described as a clinically validated diagnostic system only after separate laboratory validation, which is outside this software release gate.
