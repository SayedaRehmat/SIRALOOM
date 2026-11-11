# SIRALOOM Stage 1 implementation matrix

**Status:** engineering checkpoint; not clinical validation or accreditation.

This matrix distinguishes software controls from laboratory procedures and from independent laboratory validation. A software PASS means only that the corresponding software control exists and is tested. It does not prove that a laboratory has performed the required physical procedure or validated the assay.

| ID | Production laboratory requirement | Current SIRALOOM control | Status | Remaining evidence / work |
|---|---|---|---|---|
| S1-01 | Unique case/accession identity and tenant ownership | Organization-scoped case identifier, case creation authorization, audit trail, legacy reconciliation status | Implemented in software; verify CI | PostgreSQL tenant-isolation and concurrent accession tests |
| S1-02 | Clinical request, external referrer, request revisions and accession decision | Append-only request revisions and decisions; verification before acceptance; approved-procedure exception with two-person approval | Implemented in software; verify CI | Complete qualification governance and independent lab procedure validation |
| S1-03 | Patient/requester/referrer traceability | Case creator, request creator, external referrer identity/contact/professional identifier, verification evidence, decision actor and audit events; coded pedigree members/relationships and family phenotype subject assignment | Partial | Add/verify controlled patient identity and requester provenance; confirm evidence retention and audit review procedure |
| S1-04 | Specimen identity, receipt and history | Case-scoped specimen identifier, specimen type/date fields, VCF sample mapping, registration audit and immutable ploidy evidence revisions | Partial | Make collection/receipt evidence and identity verification mandatory for clinical intake; add specimen lifecycle events and independently evidenced identity checks |
| S1-05 | Exact VCF sample-to-specimen mapping | VCF artifact must link to a specimen; explicit vcf_sample_name; single-sample or exact mapped-sample check; dispatch/worker recheck | Implemented in software; verify CI | Add broader specimen identity and cross-sample adversarial tests |
| S1-06 | Assay identity and version | Organization-scoped unique name/version; immutable assay identity/configuration; clinical analyses require an active assay with QC rules; analysis stores and rechecks the exact assay snapshot | Implemented in software; verify CI | Add assay validation scope and performance evidence under S1-07; validate governance in a laboratory QMS |
| S1-07 | Assay validation provenance and scope | Immutable assay-validation submissions; protocol/version, intended use, specimen/variant/reference/workflow scope, pipeline component digests, per-class performance specifications, study summary/sample count, controlled evidence manifest; separate lab-director decision with independent submitter/approver, approval evidence, effective/expiry dates, append-only decisions; clinical creation/dispatch/worker gates recheck current approval and exact scope | Implemented in software; verify CI | Validate the evidence model with a qualified laboratory; independently verify source evidence, competence/authorization, wet-lab and bioinformatics performance, complete runtime pipeline identity, change-control and ongoing monitoring. SIRALOOM records and enforces evidence but does not perform analytical validation itself |
| S1-08 | Original VCF integrity and provenance | Original bytes retained; SHA-256 and size; durable worker verifies stored bytes before validation; audit trail | Strong software foundation | Validate storage backup/restore, retention and recovery with laboratory operations |
| S1-09 | VCF structural validation | Strict VCF 4.0–4.5 validation, BCFtools/HTSlib, sample/header/cardinality checks, durable asynchronous validation | Implemented in software; verify CI | Maintain independent conformance fixtures and tool-version validation evidence |
| S1-10 | Reference assembly and REF consistency | Declared/detected build checks, selected reference package, contig resolution, REF allele and coordinate checks | Partial | Require reference package identity/digest in the final immutable analysis snapshot and expand independent fixtures |
| S1-11 | Sample-level analytical QC | Analysis-linked QC observations and assessments; source-artifact lineage, assay profile/version, reviewer and exact observation snapshot are recorded and currentness is checked | Partial | Capture and govern upstream sequencing/calling and specimen-level QC metrics, thresholds, review, exceptions and evidence provenance; enforce the complete clinical gate |
| S1-12 | SNV/small-indel workflow eligibility | Fail-closed eligibility assessment; blocks structural symbolic alleles, breakends, GVCF markers, telomere sentinels, unresolved spanning deletions and missing eligibility evidence | Implemented in software; verify CI | Benchmark edge cases and confirm reports disclose all accepted limitations |
| S1-13 | Rejection, quarantine and exceptions | Invalid artifact states, accession rejection/needs-information, immutable decisions, procedure approval and withdrawal audit | Partial | Complete quarantine/release controls and operational exception review/expiry procedure |
| S1-14 | Clinical readiness and authorization gate | Accepted request/revision/decision snapshot; immutable assay snapshot; artifact, specimen, sample mapping and VCF-scope rechecks; resource/toolchain preflight | Partial | Integrate approved assay-validation evidence, QC review, confirmation requirements, qualified human review and final report sign-out |

## Clinical request and accession invariants

1. A clinical analysis cannot be created from a draft, rejected, needs-information, reassessment-required or legacy-unreconciled request.
2. Acceptance applies to one exact immutable request revision and records the exact accession decision.
3. A material new request revision invalidates the prior acceptance for new analyses; historical decisions remain preserved.
4. External referrer verification is required before acceptance unless an effective, approved laboratory procedure explicitly permits an exception.
5. Procedure registration is pending. The submitter cannot approve the same procedure version. Procedure-document evidence and approval evidence are separate.
6. Capability assignment does not establish professional qualification. Clinical-attestation capability remains disabled until a governed qualification-verification workflow exists.
7. An active assay record or QC rule set is not proof of validation. Clinical analysis requires a current, independently approved validation submission whose intended-use scope covers specimen type, SNV and small-indel classes, reference build, and exact Variant workflow/version. Expired, suspended, withdrawn, rejected or superseded approvals cannot authorize new or running clinical work.
7. Research workflows must be explicitly identified and justified as non-clinical; they cannot be represented as clinically authorized analyses.

## Initial Variant product scope

The initial clinical Variant workflow is SNV and small-indel interpretation only. Structural variants, breakends, GVCF/reference blocks, telomere sentinels and unresolved spanning deletions are not supported by this workflow. A parser accepting valid VCF syntax does not make those records eligible for the SNV/small-indel pipeline.

## Validation boundary

The software matrix is not evidence of ISO 15189 accreditation, regulatory clearance, analytical performance validation or clinical validity. Before patient-care use, a qualified laboratory must validate the complete intended-use workflow on representative samples, document performance characteristics and acceptance criteria, approve procedures, qualify personnel, and maintain ongoing quality management.
