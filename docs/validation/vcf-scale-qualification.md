# VCF processing scale qualification

## Purpose and boundary

Use this harness against a staging deployment's matching worker environment or an explicitly approved, disposable Linux laboratory workspace. It measures the repository's actual VCF intake path over a lab-supplied, de-identified VCF:

1. Upload-format validation and pinned BCFtools/HTSlib attestation.
2. REF-allele and reference-span verification against the exact selected FASTA.
3. Exclusive source-record routing and reconciliation.
4. Reference-aware normalization, sorting, CSI creation and source-to-child reconciliation.
5. Streaming iteration of normalized variants for the explicitly specimen-mapped sample.

The harness records input/reference hashes, counts, wall-clock time, Python-process CPU time, child-process CPU time (including BCFtools subprocesses), Python-process peak RSS, largest child-process peak RSS, output hashes, tool versions, routing dispositions and index/reconciliation evidence. It re-hashes the source VCF and all selected reference artifacts after processing and fails if they changed during the run. These process-level RSS values are not an aggregate container/cgroup memory peak; collect container/cgroup memory metrics separately during qualification. It stores no sample names or raw VCF records in its JSON report. The output directory is created with mode 0700; treat the VCF and generated routed/normalized artifacts as clinical data regardless of the de-identification status.

A completed run is always RUN_COMPLETE_REVIEW_REQUIRED. It is not an automatic performance PASS, clinical validation, caller qualification, GIAB concordance result, accreditation, or evidence that every WES/WGS workload fits a deployment. The laboratory must define intended-use-specific performance limits before execution and approve the observed results.

## Preconditions

- Use a de-identified or otherwise specifically approved VCF from a representative WES/WGS workload.
- Use the exact GRCh37 or GRCh38 reference FASTA used by the deployment, including its .fai and (when applicable) .gzi index.
- Run inside the same pinned Linux worker image/toolchain intended for laboratory operation. The validator enforces the repository's configured BCFtools/HTSlib versions.
- Confirm the specimen-to-sample mapping independently. The script requires the exact sample name but never records it in the report.
- Ensure the output filesystem has enough free space for routed artifacts, normalized BGZF VCF, CSI index and temporary normalization files. Normalization stages temporary files on the destination filesystem.
- Record deployment commit, resource profile, container image digest, worker CPU/memory limits, scratch-volume size, persistent storage configuration, and the laboratory's preapproved acceptance-policy ID separately in the validation record.
- Do not run on production patient data unless the laboratory has explicitly authorized the exercise and retention/cleanup.

## Run

From the repository root in the configured Linux environment:

\`\`\`bash
python scripts/validation/run_vcf_scale_benchmark.py \\
  --vcf /secure/staging/input.vcf.gz \\
  --reference-fasta /secure/references/GRCh38.fa \\
  --reference-build GRCh38 \\
  --output-dir /secure/validation-runs/vcf-scale-run-001
\`\`\`

The script obtains the specimen-mapped sample name through a hidden prompt. For a non-interactive controlled runner, set it in the environment without placing it in command arguments:

\`\`\`bash
export SIRALOOM_BENCHMARK_SAMPLE_NAME='the-exact-vcf-sample'
python scripts/validation/run_vcf_scale_benchmark.py \\
  --vcf /secure/staging/input.vcf.gz \\
  --reference-fasta /secure/references/GRCh38.fa \\
  --reference-build GRCh38 \\
  --output-dir /secure/validation-runs/vcf-scale-run-001
unset SIRALOOM_BENCHMARK_SAMPLE_NAME
\`\`\`

Use a new or empty output directory. The script refuses to overwrite prior evidence. It writes:

- vcf-scale-benchmark.json after all stages complete.
- vcf-scale-benchmark.failure.json if a stage fails; the failure report records the stage and exception class, not the exception message.
- routed/ with the immutable routing outputs and disposition manifest.
- normalized.vcf.gz and normalized.vcf.gz.csi.

A zero exit code means all measured software stages completed and internal reconciliation checks passed. It does not mean the lab's performance thresholds passed.

## Required acceptance review

Review the JSON and generated artifacts against the acceptance policy approved before the run. At minimum assess:

- Source record count equals the sum of exclusive routing dispositions; delta is zero.
- Reference validation and contig/build identity match the declared reference.
- The sequence route contains only in-scope SNV/small-INDEL candidates; unsupported CNV, SV, mitochondrial, repeat-expansion and gVCF reference-confidence records remain preserved and disclosed.
- Normalization publishes a non-empty BGZF VCF and CSI; index validation and source-child reconciliation report success.
- Selected-sample variant iteration completes without sample substitution or genotype reinterpretation.
- Wall time, CPU time, peak RSS, temporary/persistent disk use, queue impact and concurrency meet the lab's predeclared thresholds on the target worker profile.
- Repeated runs against identical immutable inputs/reference/toolchain produce the same normalized record hash and equivalent routing/reconciliation counts.
- A failure or resource shortage is recorded with its stage/reason and can be recovered without duplicate or partially published artifacts.

Run at least one representative WES and one representative WGS input per caller/version/build combination included in the lab's intended use. Include small, typical, and upper-percentile file sizes, high-multiallelic regions, indel-rich regions, gVCF input if accepted by the lab's workflow, and concurrent uploads/analyses. The sample name, input hash, reference hashes, caller/version, workflow profile, resource profile and review decision must be linked in the laboratory's controlled validation record, not copied into a public issue.

## Standards alignment

- **GA4GH/HTS specifications:** VCF format syntax and semantics are governed by the version-specific VCF specifications, including VCFv4.5. The implementation's supported version range is VCFv4.0–VCFv4.5; format recognition is not proof that every caller-specific extension is qualified. See https://samtools.github.io/hts-specs/.
- **ISO 15189:2022:** the laboratory remains responsible for its quality system, competence, controlled procedures, records, review and authorization. This software harness is evidence for a defined process step, not an accreditation claim. See https://www.iso.org/standard/15189.
- **CLSI MM09, 3rd edition:** informs the design, validation, implementation, reporting and continual quality management of clinical sequencing tests. See https://clsi.org/shop/standards/mm09/.
- **CLSI MM01, 4th edition:** provides hereditary genetic testing guidance, including specimen identification, variation types, validation, QA and reporting. See https://clsi.org/shop/standards/mm01/.

These standards do not provide one universal performance threshold for every laboratory, caller, assay or deployment. The laboratory must predefine and approve acceptance criteria for its intended use and local regulatory/accreditation requirements.

## Evidence boundary

This harness measures the actual validation, reference-check, routing, normalization and sample-iteration code. It does not measure ingress/proxy multipart spooling or concurrent upload capacity; use docs/validation/upload-capacity.md for that separate test. It does not establish GIAB concordance; use docs/validation/GIAB_HG001_GRCh38_BENCHMARK.md with a separately pinned truth VCF, confident regions, reference and hap.py toolchain. It does not validate upstream assay/caller performance or downstream clinical interpretation/sign-out.
