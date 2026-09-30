# SIRALOOM Reanalysis and Change-Aware Analysis Contract

## Purpose

SIRALOOM must support both:

1. **Lab-requested reanalysis** of a previously completed case.
2. **Change-aware reanalysis** when a validated knowledge resource, interpretation rule, phenotype input, or bioinformatics component changes and an existing case may be affected.

A completed analysis is immutable. Reanalysis creates a new child `Analysis` linked by `parent_analysis_id`. Previous reports, classifications, evidence, artifacts, provenance, and audit history remain intact.

## Scientific distinction

SIRALOOM distinguishes:

- **Variant-level reevaluation:** reassess a previously recognized variant.
- **Case-level reanalysis:** reassess the case using all relevant variants and current knowledge; where justified, reprocess appropriate upstream pipeline stages.

This follows the ACMG distinction between reevaluation and case-level reanalysis.

## Reanalysis triggers

Supported trigger classes:

- `MANUAL` — laboratory explicitly requests reanalysis.
- `ANNOTATION_UPDATE` — annotation provider/resource changed.
- `POPULATION_UPDATE` — population-frequency resource changed.
- `EVIDENCE_UPDATE` — clinical/literature/evidence resource changed.
- `ACMG_RULE_UPDATE` — ACMG/ClinGen specification or interpretation methodology changed.
- `PHENOTYPE_UPDATE` — case phenotype/family history changed.
- `BIOINFORMATICS_UPDATE` — validated analysis software/workflow changed.
- `REFERENCE_UPDATE` — selected reference package changed.
- `PERIODIC` — laboratory policy-driven periodic reanalysis.

## Change-aware behavior

A resource update must not blindly rerun every old case.

SIRALOOM should:

1. Register the new resource/version/checksum before use.
2. Compare the new resource identity/version against immutable provenance snapshots from completed analyses.
3. Identify analyses that actually consumed the changed resource.
4. Determine the earliest affected workflow stage.
5. Create a durable reanalysis candidate/notification.
6. Avoid duplicate candidates for the same analysis + change event.
7. Allow the laboratory to approve/start the reanalysis according to its policy.
8. Create a child analysis with a new immutable version.
9. Reuse unchanged upstream artifacts/steps where scientifically valid.
10. Re-run the affected stage and every downstream dependent stage.
11. Never overwrite the previous classification or report.
12. Require fresh human review when the affected evidence could alter interpretation/reportability.
13. Produce an amended/new report only through the existing reportability and sign-out gates.
14. Record the change trigger, old/new resource versions, affected stages, parent analysis, child analysis, and final disposition in the audit trail.

## Dependency rules

| Change | Earliest affected stage | Upstream reuse |
|---|---|---|
| Annotation resource/provider | annotation | validated normalized VCF |
| Population resource | population | annotation + normalized VCF |
| Evidence source | evidence | population + annotation + normalized VCF |
| ACMG/ClinGen rule/specification | ACMG assessment | evidence + population + annotation + normalized VCF |
| Phenotype/family-history update | evidence/interpretation | sequence-derived stages |
| Bioinformatics annotation/filtering update | annotation or earlier, according to validated change | only unaffected validated stages |
| Reference package update | normalization | VCF validation only if contract permits |
| Periodic policy reanalysis | laboratory-defined | dependency policy decides |

These are dependency rules, not an instruction to silently reuse results. Reuse is permitted only when the original artifact/resource/provenance identity is unchanged and the current workflow contract declares the stage compatible.

## Notification semantics

A detected change is **not automatically a new clinical result**.

The laboratory notification must state:

- case identifier
- previous completed analysis/version
- reason for change
- affected resource and old/new version
- affected workflow stage
- whether reanalysis is recommended/required under laboratory policy
- current notification status

A notification must not silently change a signed report or clinical classification.

## Reanalysis versioning

Example:

`Analysis v1` → `Analysis v2` → `Analysis v3`

The parent/child chain remains queryable. Each version has independent workflow state and provenance. Prior reports remain reproducible.

## Human review

Automated reanalysis may identify a changed classification, new candidate, or changed reportability. It must not silently replace an approved clinical interpretation.

The child analysis therefore returns through:

`ACMG assessment -> human review -> reportability -> report -> sign-out -> provenance`

## Operational requirements

- Reanalysis must be durable and resumable.
- Duplicate triggers must be idempotent.
- Worker loss must not create duplicate child analyses.
- A failed reanalysis must not alter the successful parent analysis.
- Notifications must survive browser closure and worker restart.
- All resource versions/checksums and software versions used by the child analysis must be recorded.
- The system must distinguish "resource changed" from "clinical interpretation changed"; only the latter becomes a new clinical result after review/sign-out.

## Source basis

This contract is based on ACMG guidance distinguishing variant-level reevaluation from case-level reanalysis, ACMG recommendations for laboratory policies and communication of clinically significant changes, ClinGen's versioned curation/resource-change practices, and published laboratory experience with automated change-triggered reanalysis.
