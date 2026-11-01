# Specimen ploidy evidence and caller policy contract

## Why this is required

The existing SIRALOOM data model has case-level specimens and pedigree members with a \`sex\` field, but no dedicated, typed, provenance-backed specimen ploidy assessment. Pedigree sex is not a karyotype and must not be converted into chromosome copy number. VCF GT establishes the number of alleles encoded in that call; it does not establish the biological copy number expected for the specimen.

The existing VCF validator derives FORMAT \`Number=G\` cardinality from each sample's GT ploidy. That is a structural VCF check. Whether the GT ploidy is consistent with the specimen and the validated caller/assay is a separate qualification check.

## Contract implemented

This change adds a pure domain contract and resolver. It does not yet persist evidence in the database or connect it to the VCF workflow.

### Specimen-level evidence

A versioned evidence object is scoped to a specimen UUID and exact reference build. It contains explicit integer copy-number assertions for:

- \`PAR\`: total copy number across the homologous pseudoautosomal region.
- \`X_NON_PAR\`: X-specific non-PAR copy number.
- \`Y_NON_PAR\`: Y-specific non-PAR copy number.

Every VERIFIED assertion requires:
- Evidence source type.
- Traceable evidence reference (for example, a controlled artifact/LIS reference; do not embed raw clinical documents).
- Reviewer identity.
- Timezone-aware review timestamp.
- Exact assembly identity (GRCh37 or GRCh38 family).

Evidence status can be VERIFIED, UNVERIFIED, CONFLICTED, or MOSAIC_OR_COMPLEX. Only VERIFIED evidence is eligible for resolution. Missing, complex, or conflicted evidence remains unresolved.

The schema rejects unrecognized fields. It does not accept \`sex\`, \`karyotype\`, GT, or allele balance as ploidy evidence.

### Caller/assay policy

A separate policy is bound to exact caller ID, caller version, assay ID, policy version, and reference build. It maps an explicit region copy number to either:
- A positive expected GT ploidy, or
- \`NOT_CALLABLE\`, for a region/copy-number combination where that caller/assay does not emit a genotype.

A policy is usable only when its status is QUALIFIED and it carries validation evidence, a qualified-by identity, and a timezone-aware qualification timestamp. A different caller version, assay, assembly, or unsupported copy-number mapping does not inherit the policy.

### Resolver behavior

\`resolve_expected_gt_ploidy\` returns one of:
- \`RESOLVED_CALLABLE\`: expected GT ploidy is explicit and supported by the exact qualified caller policy.
- \`RESOLVED_NOT_CALLABLE\`: the exact policy declares the region/copy-number combination non-callable.
- \`UNRESOLVED\`: evidence/policy is absent, unverified, conflicted, malformed, mismatched, or unsupported.

It never guesses. It is intentionally not called by the VCF workflow yet.

## Important limitations

1. This is a domain contract, not yet a persisted database entity or user-facing intake workflow.
2. PAR copy number is represented as one combined region because X and Y PAR sequences are homologous; representation/duplicate handling remains caller- and reference-package-specific.
3. Mosaic/complex states are explicitly unresolved; a single integer copy number is insufficient.
4. Mitochondrial ploidy and heteroplasmy are outside this sex-chromosome contract.
5. Caller policies must be built from actual versioned assay validation evidence. Test fixtures are software tests, not clinically qualified production policies.
6. Before workflow enforcement, persist immutable evidence revisions, audit who entered/reviewed them, bind them to the specimen and assay, and include exact policy/evidence versions in analysis provenance.

## Standards and scientific basis

- GA4GH/HTS VCF v4.5 defines genotype representation and likelihood ordering; GT allele count informs per-sample genotype ploidy and FORMAT \`Number=G\` cardinality. It does not define a patient's karyotype or a laboratory's assay-specific expected ploidy policy.
- ACMG NGS technical standards require sample/data integrity monitoring and validation of the complete assay/pipeline for its intended use.
- The Genome Reference Consortium defines build-specific human PAR intervals; region classification must use the exact reference assembly.

## References

- GA4GH/HTS VCF specification: https://samtools.github.io/hts-specs/VCFv4.5.pdf
- ACMG 2021 NGS technical standard: https://www.nature.com/articles/s41436-021-01139-4
- GRC human assembly/PAR definitions: https://www.ncbi.nlm.nih.gov/grc/human
- Ensembl human PAR definitions: https://www.ensembl.org/info/genome/genebuild/human_PARS.html
