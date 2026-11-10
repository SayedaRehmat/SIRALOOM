# C1.3 — Family Known-Answer Corpus Qualification

**Status:** Corpus design and source-acquisition audit; **not yet clinically qualified**.  
**Dependency gate:** C1.2 real-source HGNC/G2P/ClinGen technical qualification passed on 2026-11-10.  
**Scope:** SNV/INDEL family evidence only. This corpus does not qualify variant pathogenicity classification or clinical sign-out.

## 1. Purpose and safety boundary

C1.3 establishes an independently reviewed, source-backed family known-answer corpus before any disease-specific inheritance compatibility conclusion is implemented.

The corpus must test whether SIRALOOM correctly distinguishes:
- observed genotype evidence from inferred inheritance;
- 0/0 from no record, no-call, partial no-call, and low-quality calls;
- trans, cis, and unresolved phase;
- confirmed parentage/relatedness from pedigree relationships recorded by a user;
- de novo evidence from mere absence of an alternate call;
- sex and specimen ploidy evidence from locus-specific, assembly-aware ploidy;
- disease-specific penetrance and age context from simplistic unaffected-carrier contradictions.

The corpus expected answer is a reviewed evidence interpretation state, not an ACMG classification and not a diagnostic probability. The corpus must never convert a phenotype or genotype pattern into a clinical conclusion without the required disease-specific source, technical QC, and human review.

## 2. Current repository inventory

The current repository contains four PAVS Phenopackets:
- PAVS:A0000001 — SUMF1, homozygous, AR.
- PAVS:A0000003 — RNASEH2B, homozygous, AR.
- PAVS:A0000005 — PIEZO2, homozygous, AR.
- PAVS:A0000007 — G6PD, hemizygous, X-linked.

The PAVS manifest pins source repository commit ca56e453b9090f7b90ef256c5aca8e8c672c18b4, source attribution, CC-BY-4.0 licence, case-level file hashes and published labels. It explicitly records that these are proband-only records and contain no parental/relative genotype calls. They are useful for proband phenotype/disease/variant regression; they are **not family known answers** and cannot validate segregation, phase, de novo status, penetrance, or sex-chromosome family transmission.

Current family-corpus baseline:
- Proband-only PAVS cases: 4.
- Independently reviewed family known-answer cases: 0.
- Cases with parental segregation/phase evidence in the PAVS corpus: 0.
- Clinical inheritance qualification: not performed.

Do not relabel the four PAVS records as family cases or infer parental genotypes from their published allelic state.

## 3. Source acquisition audit and candidate datasets

A source is eligible only when its access terms, data-use permissions, provenance, and exact data artifacts are documented. A publication describing a cohort is not itself a downloadable family VCF.

| Candidate source | Evidence available from source | Access / limitations | C1.3 disposition |
|---|---|---|---|
| PAVS Phenopackets | Four repository-pinned proband Phenopackets; CC-BY-4.0 attribution and source hashes are already in the repository manifest. | No parent/relative genotype calls or pedigree transmission evidence in these four records. | Retain for proband-only tests; exclude from family inheritance qualification. |
| Undiagnosed Diseases Network (UDN), dbGaP phs001232.v8.p3 | Published studies describe trio/quad genome analyses, de novo and compound-heterozygous cases, and an independently applied clinical evaluation protocol. The current dbGaP study release is phs001232.v8.p3; a public browser exposes rare SNV/INDEL and HPO information. | Full genotype/phenotype data require dbGaP Authorized Access and an approved Data Use Certification. The current release supersedes the phs001232.v7.p3 release cited in earlier publications. Public browser data alone do not establish family sample identity, parental callability, or all raw genotype evidence required for this corpus. | **Primary candidate** for real family cases after approved access, artifact inventory, and per-case independent review. |
| GREGoR family-genomics dataset, dbGaP phs003047.v5 (R05) | The official GREGoR R05 release (May 2026) includes family structure, phenotype, case status, genetic findings, short-read WES/WGS, and a joint SNV/short-INDEL callset. A separate 2026 duoNovo study using an earlier GREGoR release reports 104 trios and evaluates de novo calls against full-trio classifications, with more than 10,000 de novo variants in its trio truth set. | R05 is distributed through controlled access on AnVIL via dbGaP. The duoNovo paper's phs003047.v4 data version must not be conflated with the current R05/v5 release. De novo technical labels are not automatically disease-diagnosis or clinical inheritance truth. | **Primary candidate** for real family SNV/INDEL cases after approved access and per-case review. The duoNovo publication may provide a separate technical de novo cross-check; do not treat its de novo labels alone as clinical diagnosis truth. |
| EGA EGAD00001016417 — Families Affected by Rare Developmental Disorders WGS | EGA describes trio WGS from mother, father and offspring in families with developmental disorders caused by de novo mutations. | EGA page identifies a Data Access Committee and request-access process. Listed files are CRAMs, not ready-to-ingest SIRALOOM VCF fixtures; raw-read alignment/calling is outside SIRALOOM scope. | Secondary candidate only if an authorized project supplies a qualified, provenance-pinned SNV/INDEL VCF callset. Do not add CRAM processing to SIRALOOM. |

### Source references

- UDN current dbGaP study release and Authorized Access: https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs001232.v8.p3. Earlier UDN/RaMeDiES study and clinical evaluation: https://pmc.ncbi.nlm.nih.gov/articles/PMC12328722/ (the publication used the earlier phs001232.v5.p2 release).
- GREGoR official dataset release inventory and access: https://gregorconsortium.org/data (R05, dbGaP phs003047.v5, May 2026; controlled access on AnVIL). duoNovo publication: https://pmc.ncbi.nlm.nih.gov/articles/PMC12987547/ (publication data accession phs003047.v4).
- EGA dataset: https://www.ega-archive.org/datasets/EGAD00001016417.
- Existing PAVS source: https://github.com/bio-ontology-research-group/pavs-phenopackets.

**Access rule:** do not download, commit, or redistribute controlled family genomic data until the relevant data-access approval, consent/data-use terms, and repository storage policy are confirmed. Do not place identifiable or re-identifiable family data in public Git history. Prefer de-identified, minimized, source-hash-pinned fixtures; keep restricted source bytes in approved access-controlled storage.

**Population-representation boundary:** UDN and GREGoR are candidate family-genomics sources, not presumed GCC/Middle East or consanguinity-representative cohorts. Each selected case must preserve only source-recorded ancestry/population context and explicit consanguinity evidence (or record NOT_REPORTED). Never infer consanguinity from a homozygous genotype, surname, geography, or phenotype. The generic inheritance-mechanics corpus and the target-market validation stratum must be reported separately. Before making GCC/consanguineous-population performance claims, add an independently reviewed GCC/consanguineous family stratum with source-supported family structure and consented genotype evidence.

## 4. Required case coverage and expected answers

Every case must identify which hypothesis it tests and the exact evidence that makes its expected answer determinate. Each category needs at least one informative case and an adversarial/insufficient-evidence control. Multiple categories may be represented by one family only when the evidence independently supports each assertion.

| Case family | Required positive/known-answer evidence | Required negative or insufficient-evidence control |
|---|---|---|
| AR homozygous | Proband homozygous alternate; source-bound parental calls and verified family/sample identity; disease association explicitly AR with compatible mechanism. | Homozygosity without adequate gene-disease validity, callability, or relationship evidence must not become causal or inheritance compatibility. |
| AR compound heterozygous — trans | Two distinct heterozygous variants; phase established by parental origin or qualified read-backed phasing; each variant and source record independently identified. | Missing/low-quality parental call or unverified phase must not be promoted to trans. |
| AR compound heterozygous — cis | Both variants on the same haplotype, supported by qualified phase evidence. | Cis must not be called biallelic/trans or treated as satisfying an AR two-allele requirement. |
| AR compound heterozygous — unresolved | Two heterozygous variants without adequate phase evidence. | Expected state remains unresolved/insufficient; no trans assumption. |
| AD inherited | Disease-specific AD association; proband and affected transmitting relative have compatible source-bound calls; relevant relatives and age/phenotype context are recorded. | Unaffected relatives without age/penetrance context, or unverified relationships, cannot be treated as definitive contradiction. |
| X-linked recessive | Disease-specific XLR association; sex-chromosome calls, locus ploidy, PAR status, and maternal/paternal origin evidence are qualified. | Do not infer hemizygosity from sex alone or use diploid assumptions outside validated locus policy. |
| X-linked dominant | Disease-specific XLD association and documented sex-specific transmission with qualified locus ploidy and family evidence. | A generic X_LINKED label is insufficient; XLD and XLR must not be collapsed. |
| De novo | Proband alternate call; both biological parents independently identity/relationship-qualified; explicit reference genotypes at the locus; parental callability and genotype QC pass under a versioned lab policy; source records and assay provenance retained. | A missing parent, no-record, no-call, partial call, low-quality call, unverified relationship, or inadequate callability must not be called confirmed de novo. |
| Incomplete penetrance / unaffected relatives | Disease-specific penetrance and age-dependent/sex-dependent context are sourced; unaffected carrier status and age at last assessment are documented. | An unaffected carrier must not automatically negate the hypothesis where penetrance or age of onset is incomplete/unknown. |
| Sex-chromosome ploidy | Reference build, PAR interval release, specimen ploidy evidence, sex as recorded, genotype representation, and locus-specific policy are explicit. | Missing/conflicting ploidy or PAR uncertainty must return review/unsupported, not normalize to diploid or haploid by assumption. |
| Missing and low-quality genotypes | Distinct no-record/no-call/partial-no-call and low DP/GQ/allele-balance cases; raw FORMAT values retained. | Missing is never reference. Low-quality parental evidence cannot support de novo, trans, or segregation. |
| Uncertain family relationships | Relationship assertion, evidence state, and sample identity are preserved separately. | Recorded parent-child edges without independently reviewed biological relationship evidence cannot support confirmed de novo or biological segregation. |

Mitochondrial, Y-linked, imprinting, mosaic, oligogenic, and structural-variant cases are outside this initial C1.3 SNV/INDEL corpus unless a separately approved qualification plan and validated source/policy set are added. Their absence must be reported as unsupported, not silently generalized from autosomal rules.

## 5. Per-case evidence package

Each family case must have an immutable manifest entry with, at minimum:

1. **Identity and source**
   - Unique non-identifying case ID.
   - Dataset accession, publication/record identifier, exact source URL or controlled-access reference.
   - Data-use/consent permission, licence, attribution, and permitted redistribution status.
   - Source release/version, source commit where applicable, acquisition date, original artifact SHA-256 and byte size.
2. **Technical input**
   - Reference assembly and exact FASTA/FAI/GZI resource identity.
   - Original and normalized VCF artifact hashes, VCF sample names, caller/version, normalization provider/version, and normalization provenance.
   - Exact family-member ↔ specimen ↔ analysis ↔ VCF sample binding IDs and fingerprints.
   - Per-variant GT, phased/unphased state, phase set, DP, GQ, AD/allele balance, FILTER, and source-record hash.
   - Explicit callability and QC state from a named, versioned laboratory policy. If absent, preserve as not assessed and block the relevant conclusion.
   - Sex as recorded, specimen ploidy evidence, assembly-specific PAR resource, and locus-specific ploidy-policy identity where relevant.
3. **Clinical and disease context**
   - Proband and relative phenotype observations with subject attribution and explicit PRESENT/ABSENT/EXCLUDED/UNKNOWN/NOT_ASSESSED semantics.
   - Gene identity via the qualified HGNC release and disease identity via exact MONDO identifier.
   - Approved gene-disease assertion resource/version, source record ID, validity status, disease-specific molecular mechanism, inheritance mode, and penetrance/age/sex context.
   - Family relationships and the independent evidence status for biological relatedness.
4. **Expected answer**
   - Expected genotype/phase/transmission/de novo state, separately.
   - Expected inheritance-review state and the exact supporting and blocking evidence.
   - Expected handling of missing, low-quality, discordant, or unverified data.
   - Explicit statement that this answer does not assign ACMG classification or establish pathogenicity unless a separate, independently reviewed variant-classification case is provided.
5. **Independent review**
   - Two distinct reviewer attestations from qualified clinical genetics / molecular diagnostics professionals.
   - Reviewer role/credential category, opaque reviewer ID, review date, review scope, source material reviewed, decision, rationale, and signed/immutable attestation reference.
   - Reviewers must not be the case author or implementation author for the expected result they are validating; they must independently adjudicate before seeing SIRALOOM output.
   - Disagreement requires a third independent adjudicator and a preserved adjudication record. Unresolved disagreement leaves the case unqualified.
   - Review must cover the expected outcome and the evidence sufficiency, not merely confirm that the JSON schema is valid.

A case without the original evidence bytes or a permitted reproducible source reference cannot be a qualified known answer. A paper abstract, gene-level inheritance label, ClinVar assertion alone, or proband-only Phenopacket is not sufficient to establish family transmission.

## 6. Reviewer workflow and qualification states

The corpus lifecycle is:

1. DISCOVERED — candidate source/case identified; not used in tests as a scientific truth.
2. ACCESS_REVIEWED — licence, consent, data-use, and permitted storage/distribution documented.
3. ACQUIRED — permitted source artifacts preserved and hashed.
4. TECHNICALLY_RECONSTRUCTED — family sample identity, genotype, phase, callability, ploidy, and source provenance are reconstructed without filling missing data.
5. INDEPENDENT_REVIEW_PENDING — blinded expected outcome prepared for two independent reviewers.
6. ADJUDICATED — any reviewer disagreement resolved by a third reviewer with rationale preserved.
7. QUALIFIED — all source, technical, clinical, and reviewer gates pass.
8. REJECTED or WITHDRAWN — provenance, access, technical integrity, or expected answer is invalid; reason and history retained.

Only QUALIFIED cases may count toward C1.3 scientific qualification. Synthetic fixtures may be used for deterministic software unit/regression tests, but must be explicitly labelled SYNTHETIC and cannot substitute for independent real-family clinical validation. A synthetic fixture's reviewer attestation must review the scenario and expected logic, not imply that it represents an observed patient family.

## 7. Qualification exit criteria

C1.3 is complete only when:

- Every required case family in Section 4 has at least one qualified informative case and an adversarial/insufficient-evidence control.
- Trans, cis, and unresolved compound-heterozygous phase are separately represented.
- De novo positive cases include both parents with independently qualified biological relationship, sample identity, locus callability, and passing genotype QC.
- Incomplete penetrance and age-dependent unaffected relatives have explicit disease-specific evidence.
- Sex-chromosome cases use assembly/PAR/locus-specific ploidy evidence; no generic diploid/haploid assumption is accepted.
- Missing, low-quality, and uncertain-relationship cases explicitly test fail-closed behavior.
- Every case has byte-level provenance, source permissions, exact resource versions, expected outputs, two independent reviews, and adjudication if needed.
- The corpus runner verifies file hashes and refuses any case whose review/access/technical status is incomplete.
- The complete corpus is run on an exact commit; test results, source manifest, reviewer attestations, and qualification report are retained as CI artifacts.

**C1.4 inheritance compatibility remains blocked until these criteria pass.** No clinical inheritance conclusions are enabled by the C1.2 source qualification result.

## 8. Immediate next work

1. Preserve the successful C1.2 real-source artifacts and qualification report from workflow run 42776452798.
2. Start the GREGoR AnVIL/dbGaP data-access review for phs003047.v5 and the UDN dbGaP Authorized Access review for phs001232.v8.p3; request only the minimum family SNV/INDEL callset, genotype, pedigree, phenotype, and callability metadata needed for approved known-answer cases.
3. Evaluate the GREGoR/duoNovo phs003047.v4 source for the de novo technical subset; do not treat technical truth as clinical diagnosis truth.
4. Do not start with EGA CRAM processing. Use it only if an approved external pipeline provides a source-bound VCF callset; FASTQ/CRAM alignment and calling are not SIRALOOM responsibilities.
5. Obtain two independent qualified reviewers and define the adjudication owner before accepting any expected result.
6. Implement the corpus manifest validator/runner only after the case schema and approved data-access route are confirmed; do not commit empty or fabricated family cases to make the gate appear complete.

---

**Current decision:** C1.2 is technically qualified against the official source snapshots. C1.3 is now the active milestone, but its family-level truth set is not yet available or independently reviewed. Inheritance compatibility must remain disabled and review-only.
