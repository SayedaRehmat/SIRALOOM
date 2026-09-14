# SIRALOOM Variant — ACMG/ClinGen Foundation Status

Date: 2026-09-07

## Implemented
- Versioned ACMG/AMP 2015 baseline combination engine.
- Explicit criterion/strength/direction validation.
- BA1 standalone handling.
- Explicit conflict handling: pathogenic + benign evidence yields `VUS` with `REQUIRES_REVIEW`, never silent resolution.
- Persistable criterion assessment contract with evidence IDs and reasoning.
- API endpoint for versioned baseline assessment.

## Deliberately not claimed
- This is not a complete biological evidence evaluator for all 28 criteria.
- No universal PM2/BA1/BS1 frequency thresholds are hard-coded.
- No universal PVS1 decision tree is hard-coded.
- No generic PP3/BP4 score thresholds are hard-coded.
- ClinGen gene/disease VCEP specifications are not yet loaded into the production rule registry.
- No clinical validation or certification is claimed.

## Scientific basis
ACMG/AMP 2015 provides the baseline classification framework. ClinGen maintains criteria-specific and VCEP-specific recommendations; these modify or constrain application by criterion and disease context.
