# Family Genotype Matrix and Inheritance Review Contract

**Status:** Implemented on the family identity work branch; awaiting current-branch CI and clinical/laboratory qualification.  
**Scope:** SNV/INDEL variant review only. This contract does not qualify an inheritance algorithm.

## 1. Architectural boundary

The family genotype matrix is a deterministic, provenance-preserving projection of already normalized, per-analysis sample calls. It is not a second VCF parser and does not infer reference genotypes, callability, biological relatedness, segregation compatibility, inheritance, pathogenicity or ACMG/ClinGen criteria.

Family members can have separate specimens, assays, analyses and source VCFs. The matrix composes those separate analysis call sets only through active, reviewed PedigreeSampleBinding records. Each binding pins:
- Case and pedigree member.
- Specimen.
- Analysis.
- Source VCF artifact and SHA-256.
- Exact VCF sample-column name.
- Binding revision and independent reviewer provenance.
- Accepted chain-of-custody and sample-identity QC evidence.

The sample-column mapping is not proof of biological identity or parentage. Pedigree relationships remain explicitly AS_RECORDED_NOT_INDEPENDENTLY_VERIFIED until separate relationship evidence is reviewed.

## 2. Matrix call contract

Each member/variant row preserves:
- Source, normalized and projected genotype representations.
- Zygosity, per-ALT dosage, reference/other-ALT dosage and missing-allele count.
- Phase and phase set.
- Source-record SHA-256 and digest validity state.
- DP, GQ, AD, PL, GL and FT values exactly as received from normalized sample-call evidence.
- Call state: NO_RECORD, GENOTYPE_UNAVAILABLE, NO_CALL, PARTIAL_NO_CALL, CALL_PRESENT, OTHER_ALT_PRESENT, OTHER_ALT_AND_MISSING, or invalid-call states.
- Callability and genotype-quality assessment status.

Absence from a variant-only VCF is NO_RECORD, never 0/0. Missing GT is never converted to reference. Malformed source-record hashes invalidate the call projection. A call with a missing source-record hash remains visible as an observed genotype but makes the matrix provenance status `INCOMPLETE_REQUIRES_REVIEW`; it cannot be attached to an inheritance assessment. A call with low GQ remains an observed call with its source metrics preserved; the matrix does not silently apply an unapproved threshold.

Callability remains NOT_ASSESSED until a laboratory-approved, versioned policy establishes target-region coverage, assay-specific thresholds, sex-chromosome handling, mapping/allele-balance requirements and no-call semantics. Genotype quality likewise remains NOT_ASSESSED_REQUIRES_LAB_QC_POLICY.

## 3. Ploidy contract

The matrix preserves the latest specimen-scoped ploidy evidence revision and its version, status, reference build, revision fingerprint, copy-number map, source type and evidence reference.

The projection distinguishes:
- NOT_ASSESSED.
- UNVERIFIED_OR_CONFLICTED.
- REFERENCE_BUILD_MISMATCH.
- VERIFIED_RECORDED_LOCUS_POLICY_REQUIRED.

Even a verified specimen-level ploidy record does not establish locus-specific ploidy. The matrix therefore always marks ploidy_interpretation_status=REQUIRES_LOCUS_SPECIFIC_LAB_POLICY until a validated locus-aware policy consumes the evidence. No diploid assumption is introduced.

## 4. Reproducibility and immutable snapshots

The canonical matrix fingerprint covers the schema version, case, requested canonical variants, ordered family samples, member/specimen/analysis/artifact provenance, source digest, exact sample name, binding fingerprint, identity evidence, normalization provenance, ploidy evidence, genotype/quality/phase/callability states, provenance-completeness state and recorded relationship snapshot. `COMPLETE` requires a valid source-artifact SHA-256, a successful normalization attempt whose source input and normalized partition input artifacts are represented in its output provenance, and a valid source-record SHA-256 for every observed record (a genuine `NO_RECORD` has no record digest to require). Otherwise the matrix is `INCOMPLETE_REQUIRES_REVIEW`. The inheritance endpoint rejects an incomplete matrix instead of creating source-bound inheritance evidence from it.

Inheritance review can accept explicit binding IDs. The API requires exactly one active verified proband binding from the analysis being reviewed. It rebuilds the matrix from current source-bound records and persists the complete matrix payload in family_genotype_matrix_snapshots, keyed by (case_id, matrix_fingerprint).

Snapshots are immutable. The inheritance assessment stores both the matrix fingerprint and snapshot ID. The corresponding contextual evidence stores the same pointers and selected binding IDs. Repeating the same request reuses the same snapshot and assessment; a changed matrix fingerprint creates a new snapshot and assessment rather than rewriting history.

Migrations:
- 0065_inheritance_family_matrix_fingerprint
- 0066_family_genotype_matrix_snapshots

The snapshot migration installs PostgreSQL and SQLite update/delete rejection triggers and refuses downgrade when snapshots exist.

## 5. Inheritance review contract

SegregationObservation remains a manually reported clinical review note. Its genotype, zygosity and phase fields are excluded from source-derived family-call evidence. The evidence payload lists those manual observation IDs separately and does not place them in the source-derived evidence observation-ID collection.

When verified family bindings are supplied:
- The inheritance assessment references the immutable matrix snapshot and fingerprint.
- The selected proband binding must belong to the target analysis.
- The result remains REQUIRES_REVIEW.
- No compatibility score, consistent/contradicted conclusion, de novo conclusion, or ACMG/ClinGen criterion is generated.

Without a matrix, the endpoint remains review-only and explicitly records that manual observations are not source evidence.

Before inheritance compatibility can be implemented, the clinical engine must have qualified, versioned inputs for gene-disease validity, disease-specific mechanism, penetrance, variable expressivity, age dependency, sex/ploidy, phase, locus callability, relationship confidence, de novo confirmation policy and disease-specific inheritance rules. These inputs must be included in the consumed evidence fingerprint.

## 6. Qualification coverage

The current fixture/test additions cover:
- Three-member proband/father/mother family calls from separate VCFs, routed through the production source-lineage router.
- A CI integration test that runs the pinned BCFtools normalizer against the repository GRCh38 reference fixture, verifies source-to-normalized ALT reconciliation, checks the exact source-record SHA-256, and builds the matrix from the normalized output (skipped only when the pinned executable/reference fixture is unavailable).
- Exact sample-column selection and sample-swap rejection.
- Source/normalized genotype, multiallelic projection and other-ALT states.
- No-record, no-call and partial no-call distinctions.
- Phased genotype and phase-set preservation.
- Low DP/GQ calls preserved without an unapproved quality threshold.
- Parent-child relationships explicitly marked as reported, not independently verified.
- Accepted sample identity/chain-of-custody evidence without inferring parentage.
- Verified, unverified and reference-build-mismatched ploidy evidence boundaries.
- Invalid source-record SHA-256 rejection.
- Matrix fingerprint order stability and inheritance assessment replay/invalidation when the fingerprint changes.
- PostgreSQL immutability and uniqueness tests for matrix snapshots.

Remaining qualification work includes real laboratory family datasets under approved de-identification, assay-specific callability and ploidy policies, sample-swap and relationship-discordance known answers, independent review of de novo/phase cases, and current CI execution. Synthetic fixtures do not establish clinical validity.

## 7. Explicit non-goals

This milestone does not implement inheritance scoring, de novo confirmation, compound-heterozygous phase resolution, penetrance-aware contradiction rules, automated gene-disease mechanism selection, clinical sign-out or laboratory accreditation claims. It does not enable CNV, SV, mitochondrial or repeat-expansion interpretation.
