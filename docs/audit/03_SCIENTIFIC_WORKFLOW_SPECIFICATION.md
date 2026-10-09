# Scientific workflow specification — acceptance contract

## Intended boundary

Phase 1 begins with VCF/VCF.GZ intake and does not claim FASTQ alignment, variant calling or joint genotyping. It supports a case-centered tertiary-analysis workflow. Clinical interpretation and sign-out remain human-governed.

## Stage contract

| Stage | Required inputs / checks | Persisted evidence and outputs | Failure / gate |
|---|---|---|---|
| Accession / case | Tenant, case, specimen/test context, authorized user | Case and specimen identity, source metadata | Reject unauthorized or inconsistent identity |
| Intake | Original VCF, file hash, size, build declaration, sample/header metadata | Immutable source artifact and validation record | Malformed/oversized/unsupported files fail visibly |
| Structural validation | VCF syntax, header/columns, records, contigs, REF/ALT, INFO/FORMAT cardinality, sample fields | Validator/tool version, warnings/errors, record counts | Never equate accepted filename with valid VCF |
| Build/reference preflight | Explicit GRCh37/GRCh38; exact reference package, FASTA/FAI and checksums | Assembly identity, contig manifest, reference hash | Build mismatch or REF mismatch blocks normalization |
| Normalization | Qualified BCFtools version/command + exact reference FASTA | Original-to-normalized lineage, tool version, command policy, output/index hashes | Do not publish partial output; fail unsupported classes explicitly |
| Annotation | Approved provider/resource contract compatible with build | Provider/version/config, input identity, transcript/consequence payload, source provenance | Timeout/rate limit retryable; semantic mismatch non-retryable/review |
| Population | Dataset/release/API selector and request/response provenance | Population-specific AC/AN/AF and availability state | Missing data is not AF=0; populations are not relabeled |
| Phenotype/context | HPO term identifiers/version, source, negation/context where supported | Phenotype observations and matching rationale | Decision support only; no fabricated phenotype |
| Evidence | Source assertion ID/version, observation, date, linked variant/gene/disease | Evidence records with provenance and eligibility | Duplicate/contradictory/untraceable evidence requires review |
| ACMG/ClinGen proposal | Applicable versioned specification and eligible evidence IDs | Criterion, direction, strength, rationale, evidence links, evaluator version | Missing/ambiguous spec or ineligible evidence cannot become support |
| Human review | Reviewer authorization, rationale, conflict/role controls | Versioned decision, actor, timestamp, audit event | Automated proposal remains distinct from expert decision |
| Reportability | Authorized role, indication/context, lab policy | Explicit reportability decision/version | Pathogenicity classification is not reportability |
| Report/sign-out | Approved decisions and complete provenance | Immutable report version, approver, timestamp, artifact hash | No final report if mandatory gates are unresolved |
| Export/reanalysis | Authorized request, stable source/result versions | Export manifest/hash; reanalysis candidate/change event | Never mutate historic signed-out results |

## Variant-class support matrix to establish

For each class below, test **accepted → validated → normalized → annotated → evidence-supported → reportable** independently. A class accepted at intake is not necessarily supported downstream.

- SNVs, MNVs, simple insertions/deletions.
- Multiallelic records, including genotype and INFO/FORMAT allele-index remapping after splitting.
- Symbolic alleles such as `<DEL>`, `<DUP>`, `<INS>`, CNV/SV records.
- Breakends and mate/breakpoint representation.
- Star allele (`*`) and spanning-deletion semantics.
- GVCF reference-confidence blocks and non-variant records.
- Phased genotypes, haplotypes, missing genotypes, multiple samples.
- Duplicate records, contig aliases, malformed headers, invalid REF and decompression failures.

The current repository contains both strict validation and BCFtools-related code, while older validation documentation says multiallelic records are rejected and symbolic/SV alleles are outside normalization scope. This must be reconciled through a code-path trace and fixtures before making a support claim.

## Required golden-case outputs

Every golden case must pin input hash, reference package hash/build, tool versions/command, expected normalized records, annotation/provider release, resource plan, evidence IDs, expected workflow states and report/export hashes where deterministic. Differences across provider/resource releases must be reviewed rather than silently overwritten.
