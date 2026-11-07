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
