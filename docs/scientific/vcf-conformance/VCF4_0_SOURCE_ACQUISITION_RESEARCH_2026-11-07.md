# VCFv4.0 historical source acquisition research

**Research date:** 2026-11-07  
**Branch:** `research/vcf-conformance-phase-a-20261105`  
**Disposition:** `HISTORICAL_SOURCE_CANDIDATE_CORROBORATED — IMMUTABLE_ORIGINAL_BYTES_NOT_CAPTURED — NOT_QUALIFIED`

## Findings

### 1. IGSR/1000 Genomes core VCFv4.0 page

Two currently discoverable routes expose the same VCFv4.0 core specification content:

- Primary candidate route: https://www.internationalgenome.org/wiki/Analysis/vcf4.0/
- Alternate descriptive route: https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/vcf-variant-call-format-version-40/
- Test-site copy: https://test.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/vcf-variant-call-format-version-40/

The rendered page explicitly identifies itself as describing VCF version 4.0 and directs readers to a separate page for 1000 Genomes structural-variation conventions/extensions. It contains the core meta-information, header, fixed-field, INFO, FORMAT, genotype and haplotype-representation sections. The alternate route exposes a full rendered text view with stable line anchors in the retrieval surface.

The test-site copy is corroborating evidence that the content is available at a second IGSR hostname; it is not evidence of an independent normative source or an immutable historical revision. No revision identifier, original source repository commit, source-byte archive, or cryptographic digest for the original publication was established in this research pass.

### 2. VCFtools historical specification index

The VCFtools specification index states that older VCF 4.0 documents were hosted on the 1000 Genomes wiki and that the specification is now maintained by GA4GH:

- https://vcftools.github.io/specs.html

This independently corroborates the IGSR/1000 Genomes page as the historical location for the older VCFv4.0 document. It does not itself provide the original VCFv4.0 source bytes or a revision hash.

### 3. Historical poster and secondary references

A VCFtools poster dated approximately 16 years ago includes VCFv4.0 example headers, INFO/FORMAT examples, and records:

- https://vcftools.github.io/VCF-poster.pdf

This is useful as contemporaneous contextual evidence, but it is a poster and not the complete normative specification. It must not be substituted for the core VCFv4.0 source.

Other contemporary/secondary references found in search results cite or demonstrate VCFv4.0, including 1000 Genomes project tutorials and Ensembl VEP documentation. They corroborate historical use of the version but are not authoritative source replacements.

### 4. Separation of 1000 Genomes SV conventions

The following page is explicitly identified by the core VCFv4.0 page as a separate 1000 Genomes Project conventions/extensions document:

- https://www.internationalgenome.org/wiki/Analysis/Variant%20Call%20Format/VCF%20%28Variant%20Call%20Format%29%20version%204.0/encoding-structural-variants/

It must remain a separate producer/project-convention source. Its rules must not be silently imported into the VCFv4.0 core requirements.

## Acquisition status

| Evidence item | Status | Permitted use |
|---|---|---|
| IGSR core page | Corroborated historical source candidate | Discovery and provisional context only |
| Alternate IGSR descriptive route | Same-content route observed | Corroboration; not independent authority |
| IGSR test-site copy | Same-content copy observed | Corroboration only |
| VCFtools historical index | Confirms historical hosting location | Provenance corroboration |
| VCFtools poster PDF | Contemporaneous but incomplete | Historical context only |
| 1000 Genomes SV conventions page | Separate project-specific extension | Separate source scope only |
| Original immutable source bytes and SHA-256 | Not captured | Required before source qualification |

## Next acquisition steps

1. Obtain an authoritative archival capture or original publication/export for the IGSR core VCFv4.0 document, preserving exact response bytes and retrieval metadata.
2. Determine whether the historical wiki exposes a verifiable page revision identifier or an authoritative source export; do not treat a current rendered page or test-site copy as a revision pin.
3. Search historical archive snapshots and the original VCFtools/1000 Genomes documentation distribution for a source artifact whose identity can be independently corroborated.
4. Capture the selected artifact byte-for-byte, record URL, retrieval timestamp, HTTP metadata, archive/revision identifier and SHA-256, and independently recompute the digest.
5. Compare the captured text with the currently rendered IGSR page and the contemporaneous VCFtools poster. Record differences rather than silently reconciling them.
6. Keep the core VCFv4.0 source and the separate 1000 Genomes SV conventions source in distinct manifest entries and requirement namespaces.
7. Until these steps pass, retain `SOURCE_NOT_PINNED` for every VCFv4.0 applicability cell.

## Non-claims

- No original VCFv4.0 source bytes were acquired in this pass.
- No SHA-256 was computed for the original VCFv4.0 specification.
- The IGSR page has not been promoted from a corroborated candidate to a qualified normative source.
- No VCFv4.0 requirement is promoted to source-pinned status.


## 5. Targeted VCFv4.0 FORMAT source-context review — 2026-11-07

A direct inspection of the detailed IGSR VCFv4.0 page returned 245 rendered lines. The page remains a mutable rendered HTML candidate, not an immutable source capture. The following exact rendered-page locations were reviewed for the VCFv4.0 FORMAT tests now present on the PR merge base:

| Rendered line(s) | Source statement | Validation consequence |
|---|---|---|
| 0–2 | Page identifies VCFv4.0 and points to a separate 1000 Genomes SV conventions page | Keep core VCF and 1000 Genomes SV extensions separate |
| 23–26 | Example header declares GT as Number=1/String, GQ as Number=1/Integer, DP as Number=1/Integer and HQ as Number=2/Integer | Historical examples support these reserved field cardinalities/types |
| 43 | INFO/FILTER/FORMAT metadata lines are optional, but if present must be completely well-formed | Absence of redundant declarations is not itself invalid |
| 54–58 | FORMAT fields are described with ID, Number, Type and Description; supported Types are Integer, Float, Character and String | FORMAT declaration syntax/type domain |
| 108 | First FORMAT sub-field must always be GT | GT ordering is required when genotype data are present |
| 112 | All samples must have GT call information; missing calls are represented with missing allele tokens | VCFv4.0 sample genotype data require a GT field |
| 115–116 | DP is Integer; FT is an alphanumeric String | DP/FT implicit field typing |
| 117 | GL consists of three floating-point log10 likelihoods for AA, AB and BB and is not applicable when the site is not biallelic | VCFv4.0 GL is Number=3/Float and populated GL is not valid on multiallelic records |
| 118–119 | GQ is Numeric; HQ is two comma-separated phred qualities and Numeric | With no explicit header declaration, accept numeric values; when a declaration is supplied, enforce its declared Integer/Float type |
| 120 | Trailing fields may be dropped except GT, which should always be present | Preserve GT as a non-droppable FORMAT value |

The current PR merge-base tests cover five VCFv4.0 failures: one multiallelic GL case and four reserved FORMAT header-definition mismatches. Their expected behavior is supported by the rendered source passages above. The GQ/HQ prose says “Numeric” while the example header uses Integer; the tests use decimal values in the absence of explicit declarations. The validator therefore uses an internal Numeric type for implicit GQ/HQ values and accepts Integer or Float in explicit GQ/HQ declarations. This interpretation remains provisional pending an immutable historical source.

### VCFv4.5 Number=P cardinality dependency

The pinned repository source `VCFv4.5.tex` lines 195–200 defines Number=LA/LR/LG and states at line 198 that a Number=P field has one value for each allele value defined in GT. The populated-Number=P-without-GT validator guard is treated as a strict cardinality-validation dependency: without GT, a populated Number=P value cannot be checked against the source-defined cardinality. A missing Number=P value remains unresolved and is not rejected solely because GT is absent. This guard is not promoted as a separate source-level statement that every VCFv4.5 sample must globally contain GT.

### Implementation disposition

A narrowly scoped validator patch has been committed on this research branch:
- VCFv4.0 implicit reserved FORMAT definitions for GT, DP, FT, GL, GQ and HQ;
- VCFv4.0 header Number/Type checks for those reserved fields;
- VCFv4.0 rejection of populated GL on non-biallelic records;
- VCFv4.0 requirement for FORMAT/GT whenever sample genotype columns are present, with explicit missing-allele tokens accepted;
- VCFv4.5 rejection of populated Number=P values when GT is absent, while allowing a missing Number=P value to remain unresolved.

The implementation change is provisional until the historical VCFv4.0 source bytes are captured and hashed, the full test run passes, and independent standards review is completed. A dedicated branch test now covers mandatory GT presence and explicit missing-allele representation. It does not change the source qualification status or claim VCFv4.0 laboratory conformance.
