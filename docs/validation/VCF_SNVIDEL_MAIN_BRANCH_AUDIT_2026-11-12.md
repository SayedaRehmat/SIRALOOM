# SIRALOOM VCF stage audit for clinical germline SNV/indel reanalysis

**Audit date:** 2026-11-12  
**Audited baseline:** main at fc0ac8487b54dcdd615496e0e5bdc55d01e7e2b5, immediately after merge of PR #297  
**Scope:** VCF intake, validation, preservation, normalization, caller-aware evidence handling, and routing for the VCF-to-report reanalysis product.  
**Out of scope for this audit:** building a FASTQ-to-report sequencing pipeline or claiming analytical qualification of upstream variant callers.

## 1. Executive determination

SIRALOOM main already contained substantial VCF and small-variant infrastructure. It was not a blank VCF parser and did not need a rewrite.

The main gaps at the audit baseline were:

1. Durable artifact validation and recovery. This was recovered from PR #297 and merged into main before this caller-profile work.
2. A caller-aware provenance and semantic compatibility layer for GATK HaplotypeCaller, DeepVariant, and DRAGEN. This is implemented on the current feature branch and awaits CI/merge.
3. Caller-specific INFO/FORMAT header declaration checks for documented fields. This is implemented on the current feature branch and awaits CI/merge.
4. Actual caller-generated fixtures and analytical qualification for the exact caller release/model/assay combinations. This remains open because GATK and licensed DRAGEN were not executed in this environment; the GATK/DRAGEN fixtures are documentation-derived, and the DeepVariant fixture is an upstream software test fixture rather than a clinical truth-set validation.
5. Authenticated run-level provenance. VCF headers are declarations, not cryptographic proof of the executable, caller mode, model, reference, or assay. A controlled caller-run manifest is still needed for lab-owned upstream pipelines.

The required VCF scope is not an implementation of every VCF construct for every conceivable application. It is correct conformance for supported VCF versions and the constructs actually accepted by the clinical germline SNV/indel workflow, plus explicit preservation and safe routing of unsupported constructs.

## 2. Product boundary

SIRALOOM's first product is VCF-to-report reanalysis. It receives upstream caller output. It does not itself perform FASTQ base calling, read alignment, or GATK/DeepVariant/DRAGEN variant calling.

Therefore:

- SIRALOOM must validate the VCF artifact and the semantics it consumes.
- SIRALOOM must preserve original caller evidence and identify caller provenance when available.
- SIRALOOM must not claim it validated the upstream caller's analytical sensitivity or specificity merely because it parses that caller's VCF.
- If SIRALOOM later executes callers from FASTQ/BAM/CRAM, that becomes a separate upstream analytical validation program.

## 3. Production VCF-stage requirements mapped to main

| Production requirement | Main at audited baseline | Evidence / implementation location | Assessment |
|---|---|---|---|
| Immutable original artifact | Implemented | Durable artifact intake, object-store identity, SHA-256 and byte-size verification | Meets intake preservation requirement |
| Durable validation lifecycle | Recovered and merged in #297 | Artifact validation dispatch, outbox, worker state, retries and audit events | Implemented; recheck main CI after merge |
| TBI/CSI index validation | Implemented in #297 | Worker validates paired index against exact VCF record stream | Implemented |
| VCF version declaration | Implemented | Strict validator recognizes supported VCFv4.0–4.5 declarations | Version recognition is not complete normative conformance |
| Header/record syntax | Substantial implementation | Strict validator checks fixed columns, header declarations, records and types | Implemented for current supported profile |
| INFO/FORMAT cardinality and types | Substantial implementation | Strict validator uses declared definitions and version-aware rules | Core implementation present; caller-specific profile checks added by this branch |
| GT allele indexes and ploidy | Implemented | Strict GT and genotype-cardinality validation | Essential SNV/indel requirement present |
| Missing genotype values | Implemented | Explicit missing/partial-call handling | Present |
| Phasing and phase sets | Implemented | GT phase separators and PS/PGT/PID retention | Present; specialized constructs remain scope-dependent |
| Multiallelic handling | Implemented | BCFtools split policy and source allele/genotype lineage | Present |
| VCFv4.5 local alleles (LA/LR/LG, LAA and projection/equivalence) | Implemented | Strict validator local-allele cardinality and projection/equivalence checks; tests in tests/test_vcf_validation.py | Present; retain for VCFv4.5 multiallelic small-variant inputs |
| VCFv4.4/4.5 phase-set list semantics (PSL/PSO/PSQ) | Implemented | Strict validator phase-set and phase-observation handling; tests in tests/test_vcf_validation.py | Present; relevant to phased SNV/indel records |
| VCFv4.5 Number=M base-modification cardinality | Partially implemented | Validator includes base-modification cardinality and allele-context checks | Additional assay/strandedness qualification is outside ordinary SNV/indel scope |
| Breakend/PSO structural validation | Present at VCF semantic level | Validator checks BND/PSO relationships and record structure | Full derivative-chromosome reconstruction is not an SNV/indel completion gate |
| Reference identity and REF checks | Implemented | Approved reference packages, contig/build checks and reference-aware validation | Present |
| Normalization | Implemented | BCFtools 1.25, reference FASTA, strict REF check and multiallelic splitting | Present; original source artifact remains separate |
| Caller identity | Missing at baseline; added by this branch | New caller profile inspection for GATK, DeepVariant and DRAGEN | Implemented as unverified header provenance |
| Caller release extraction | Missing at baseline; added by this branch | GATK command-line Version, DeepVariant_version, DRAGENVersion | Implemented when declared; missing/conflicting values remain explicit |
| Caller-specific field semantics | Missing at baseline; added by this branch | Family-level documented semantics for AD, DP, AF/VAF, GQ, PL/GL/GP, PS and caller annotations | Implemented as descriptive semantics, not thresholds |
| Caller-specific header Number/Type checks | Missing at baseline; added by this branch | Expected declarations checked only when a documented field is present | Implemented; mismatch is distinct from malformed VCF |
| Unknown caller behavior | Missing at baseline; added by this branch | No inference from common FORMAT names; unknown caller remains structurally processable | Implemented |
| Conflicting caller metadata | Missing at baseline; added by this branch | Conflict status; no precedence rule | Implemented |
| Caller-specific field preservation | Present in parser; expanded by this branch's tests | sample_calls.format_values retains caller-specific FORMAT values | Implemented and tested |
| GVCF distinction | Implemented with limits | Reference-confidence markers and dedicated routing | Do not treat GVCF as ordinary variant-only VCF or claim joint genotyping |
| Structural variant / CNV / repeat / mitochondrial workflows | Separate routing/capability boundary | Existing specialized routing | Not a prerequisite for SNV/indel completion |
| Caller analytical performance | Not established | Existing GIAB concordance tooling exists, but exact caller-run benchmark evidence is not present for all three callers | Open qualification work |
| Run-level authenticated provenance | Not established | Header metadata is unverified; no signed or controlled caller-run manifest is attached to the VCF intake | Open provenance work |

## 4. What the three caller profiles mean

The new profile layer recognizes only explicit caller-specific evidence:

- GATK HaplotypeCaller: GATKCommandLine with HaplotypeCaller ID, legacy GATKCommandLine.HaplotypeCaller, and/or source=HaplotypeCaller.
- DeepVariant: DeepVariant_version, with optional model-type metadata.
- Illumina DRAGEN small variant caller: source=DRAGEN_SNV and DRAGENVersion.

The layer does not identify callers from VCFv4.2 or common fields such as GT, AD, DP, GQ and PL.

For each recognized profile it records:

- caller family and exact declared release when uniquely available;
- observed GATK pipeline stages;
- declared INFO, FORMAT, FILTER and ALT identifiers;
- documented semantic notes for caller-specific fields present in the header;
- documented Number/Type declaration checks for known fields;
- GVCF/reference-confidence markers;
- a digest of command-line header lines, not the raw command line;
- explicit statuses for caller identity, release, assay mode and clinical qualification.

A header match is not an authenticated caller identity. A DRAGEN_SNV marker does not prove germline rather than somatic mode. A GATK GenotypeGVCFs stage alone does not prove HaplotypeCaller was the upstream caller. Missing or conflicting metadata is retained as missing or conflicted.

### Important field differences

- GATK AD is unfiltered allele depth in REF/ALT order, excluding uninformative reads; GATK FORMAT/DP is filtered sample depth.
- DeepVariant declares VAF per ALT allele and has its own GQ and read-evidence conventions.
- DRAGEN FORMAT/DP is informative depth, while INFO/DP is unfiltered site depth; DRAGEN AD/AF are based on informative reads.
- QUAL, GQ, DP, AD, AF/VAF and FILTER must not be treated as numerically interchangeable across callers.

The caller profile layer introduces no universal thresholds and does not use caller metrics as ACMG/AMP evidence by itself.

## 5. VCF versions: required scope versus universal conformance

Main recognizes VCFv4.0–4.5. For the VCF-to-report SNV/indel product, the required implementation is:

1. Correct version detection and version-specific rules for accepted inputs.
2. Correct GT, ploidy, allele indexing, INFO/FORMAT cardinality, missing-value and multiallelic semantics.
3. Correct reference identity and normalization.
4. Correct handling of caller-declared fields that SIRALOOM consumes.
5. Preservation of unknown fields without guessing their meaning.
6. Explicit unsupported/routing results for constructs outside the supported SNV/indel workflow.

Main already contains VCFv4.5 local-allele projection/equivalence checks, phase-set list semantics, and base-modification cardinality handling. Local-allele handling is retained because it can represent multiallelic small variants. Phase-set semantics are retained because they can affect phased SNV/indel interpretation. Full assay-specific base-modification/strandedness qualification, PSO/BND derivative-chromosome reconstruction, CNV, repeat expansion, mitochondrial interpretation, and every possible INFO annotation are not prerequisites for the declared small-variant caller intake scope.

However, if a file uses a construct outside the supported capability, SIRALOOM must preserve it and return a durable unsupported/unresolved result rather than silently misinterpreting it.

The VCFv4.0 historical source provenance remains a separate standards-ledger issue. Recognizing VCFv4.0 and testing its reserved FORMAT behavior does not imply that every historical VCFv4.0 normative statement has been independently re-adjudicated.

The focused VCFv4.0 genotype conformance tests now enforce GT for every sample-bearing record, explicit missing-allele representation, the historical biallelic-only GL cardinality, DP/FT/GL reserved definitions, and GQ/HQ numeric semantics (GQ Number=1; HQ Number=2; Integer or Float declarations accepted). The IGSR historical VCFv4.0 guidance describes all-sample GT calls and the numeric GQ/HQ fields; it is not being substituted for the still-open historical source-byte/hash provenance task.

## 6. Previous PR work: selective recovery decisions

| PR | Work | Decision |
|---|---|---|
| #297 | Durable artifact validation, validation outbox/worker, SHA-256 recheck, TBI/CSI validation, worker recovery, VCFv4.0 and Number=P fixes | Merged into main as fc0ac8487b54dcdd615496e0e5bdc55d01e7e2b5 |
| #299 | Additional VCFv4.0 reserved FORMAT and VCFv4.5 Number=P regression tests | Test coverage carried into this caller-compatibility branch; overlapping implementation fix was already recovered through #297 |
| #287 | GIAB concordance harness | Already merged into main; useful for later caller-generated truth-set comparisons |
| #288 | DeepVariant GIAB 30x benchmark workflow | Not merged as completed qualification: branch is based on an old qualification branch and requires a self-hosted high-memory runner; no executed caller benchmark result was established in this audit |
| #282 | Broad normalization-resource governance and VCF conformance framework; 522 commits and roughly 17k additions in the reviewed branch | Not merged wholesale: too broad for this focused VCF-stage closure and not established as a current-main tested delta |
| #292 | VCF feature registry refactor stacked on #282 | Not merged independently because it depends on the unmerged #282 architecture |
| #276 | Version-conformance corpus tests | Not merged wholesale; some test assumptions conflict with SIRALOOM's BGZF/indexed intake contract and need adjudication |
| #275 | Repository/standards audit material | Research/documentation, not a missing runtime capability |
| #293 | VCFv4.5 source-to-requirement research plus code/tests for local alleles, Number=M, phase sets, BND semantics and GT behavior | Much of its semantic code overlaps functionality already present in audited main. Do not merge the draft wholesale: it has no successful CI evidence and includes out-of-scope policy changes. The VCFv4.0 GT-required behavior and focused GT ploidy tests were selectively carried into this branch. |
| #317 | Semantic/profile reconciliation research | Retain as research; no standalone runtime capability to merge |
| #321 | Broad integration including durable artifact work and unrelated clinical workflow changes | Not merged wholesale; #297's VCF-relevant work was extracted and merged separately |

## 7. Implementation and test coverage added on the caller-compatibility branch

The branch adds:

- caller-aware provenance inspection and version extraction;
- family-level documented semantic profiles for GATK HaplotypeCaller, DeepVariant and DRAGEN SNV;
- Number/Type declaration checks for documented INFO/FORMAT fields when present;
- explicit unknown, partial and conflicting metadata outcomes;
- persistence of caller provenance in strict validation and ingestion metadata;
- a DeepVariant r1.10 upstream golden VCF fixture;
- documentation-derived GATK and DRAGEN fixtures with explicit provenance labels;
- tests for caller identity, caller release, GATK stage discrimination, GVCF routing, conflicting metadata, unknown caller handling, semantic declaration mismatch and caller-field preservation;
- a DRAGEN-style multiallelic BCFtools normalization test for Number=A/R/G fields, phasing and original genotype/ALT lineage;
- additional VCFv4.0 and VCFv4.5 Number=P regression cases.

The fixtures have deliberately different evidence grades. The DeepVariant file is an upstream software-test fixture. The GATK and DRAGEN files are documentation-derived compatibility fixtures. None is represented as a clinical validation dataset.

## 8. Remaining acceptance gates

The VCF SNV/indel intake stage must not be declared laboratory-qualified until the following are completed:

1. CI passes on the final merged main commit, including backend, frontend and PostgreSQL integration.
2. The exact caller-produced GATK, DeepVariant and DRAGEN outputs intended for the laboratory are ingested and tested, not only documentation-derived fixtures.
3. A controlled caller-run manifest records exact caller release, model/mode, configuration, reference assembly/checksum, assay/platform, alignment provenance, input BAM/CRAM identity and output VCF checksum.
4. Actual caller-generated VCF/GVCF files are compared to GIAB truth sets over declared confident regions, with SNV and indel metrics reported separately.
5. The lab's acceptance criteria, limitations, review and approval are documented for each exact caller-release/assay combination.
6. GVCF acceptance scope is explicitly decided: preserve/route only, or full validated joint-genotyping workflow.
7. VCFv4.0 historical source provenance and any remaining source-ledger ambiguity are closed or explicitly excluded from the approved compatibility scope.

## 9. Acceptance decision

The correct implementation target is a production-grade, multi-caller-aware VCF intake and normalization boundary for supported germline SNV/indel records—not a universal implementation of every VCF feature and not an assertion that SIRALOOM has analytically qualified upstream callers.

PR #297 closes the durable intake gap. The caller-compatibility branch closes the initial GATK/DeepVariant/DRAGEN provenance and documented-field compatibility gap, subject to CI. Actual caller-run manifests and analytical truth-set qualification remain separate, explicit gates.


## 10. Standards references used for this audit

- GA4GH HTS specifications (VCF versions and canonical specifications): https://github.com/samtools/hts-specs
- IGSR / 1000 Genomes VCFv4.0 format guidance (sample genotype data use GT first and every sample has GT call information; unavailable alleles are represented explicitly as missing): https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- GATK HaplotypeCaller algorithm and output: https://gatk.broadinstitute.org/hc/en-us/articles/360036359552-HaplotypeCaller
- GATK VCF structure and FORMAT/AD, DP, GQ, PL semantics: https://gatk.broadinstitute.org/hc/en-us/articles/360035531692-VCF-Variant-Call-Format
- DeepVariant upstream germline caller and r1.10 golden VCF fixture: https://github.com/google/deepvariant
- DRAGEN v4.3 small-variant output, depth, QUAL/GQ and phasing semantics: https://help.dragen.illumina.com/dragen-v4.3/product-guide/dragen-v4.3/dragen-dna-pipeline/small-variant-calling
