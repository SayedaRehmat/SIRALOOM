# SIRALOOM Variant — Criterion-Specific Evaluator Status

## Status

Implementation milestone: criterion-specific ACMG/AMP evidence evaluators

Validated locally: yes for unit-level behavior only

Clinical validation: NOT CLAIMED

## Implemented evaluators

- PM2: requires an explicit rarity specification containing a maximum allele-frequency threshold and minimum allele-number requirement; missing population resources remain indeterminate.
- BA1: requires an explicit standalone allele-frequency threshold and minimum allele-number requirement.
- BS1: requires an explicit allele-frequency threshold and minimum allele-number requirement.
- PP3/BP4: require an explicitly calibrated predictor and score interval; SIRALOOM provides no generic predictor cutoff.
- PVS1: conservative gate requiring explicit confirmation that LoF is an established disease mechanism and an explicit allowed consequence set. This is not a full PVS1 decision tree.

## Explicit non-goals

The implementation does not infer clinical criterion strengths from arbitrary annotations, does not invent gene/disease thresholds, and does not treat missing population data as zero frequency.

## Scientific basis

ClinGen's current Variant Classification Guidance page (last updated July 2025) provides the authoritative index for current general and criteria-specific ACMG/AMP recommendations. ClinGen's guidance to VCEPs regarding gnomAD v4 states that PM2/BA1/BS1 thresholds may need review when moving to gnomAD v4 and that disease-specific specifications remain important. ClinGen's PP3/BP4 work supports calibrated predictor-specific thresholds rather than generic cutoffs. ClinGen's PVS1 recommendation establishes that LoF interpretation requires considerations beyond simply observing a truncating consequence.

## Tests

- Criterion evaluator tests: 8/8 PASS
- Full existing SIRALOOM test suite: 32/32 PASS
- Python compile check: PASS

## Next scientific milestone

Build a versioned ClinGen specification registry and criterion evaluators backed by approved specification records/benchmark cases, then integrate those outputs into the ACMG assessment API with explicit specification IDs, versions, evidence IDs, and audit events.
