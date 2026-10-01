# SIRALOOM external scientific-resource governance

SIRALOOM must never treat a discovered URL as automatically authentic, licensed,
reproducible, or suitable for clinical use. Every external scientific resource
passes the same provider-neutral governance contract.

## Required source contract

Every discovery provider must identify:

- **publisher** — the organization that actually publishes/maintains the resource;
- **canonical_source_url** — the publisher's authoritative landing/documentation page;
- **artifact_url** — the exact artifact/API endpoint being consumed;
- **release_identity** — the publisher's own release/version/dataset identity;
- **authority_evidence_url** — authoritative documentation proving that the artifact
  belongs to the stated resource and release;
- **access_mode** — PUBLIC, AUTHENTICATED, LICENSE_REQUIRED, or LOCAL_ONLY;
- **license_status** — VERIFIED, NOT_REQUIRED, REVIEW_REQUIRED, RESTRICTED, or UNKNOWN;
- **license_url / terms_url** — exact terms when applicable;
- **checksum_status** — PUBLISHED_AND_VERIFIED, TRANSPORT_DIGEST_ONLY,
  NOT_PUBLISHED, or UNKNOWN.

A syntactically valid HTTPS URL is not proof of authenticity. Provider code and
resource qualification must establish that the endpoint is the publisher's
official endpoint and that its content matches the declared resource.

## Resource-specific source policy

| Resource/tool | Authoritative source family | Identity required | Access/licensing gate |
|---|---|---|---|
| ClinVar | NCBI ClinVar / NCBI FTP | archived monthly release or explicitly identified rolling feed | NCBI data-use review; attribution; never call rolling feed an immutable release |
| GRCh37/GRCh38 reference | Genome Reference Consortium / NCBI | assembly accession.version + exact FASTA/FAI checksums + contig manifest | verify source and redistribution terms for the exact package |
| BCFtools | official samtools/bcftools project | exact executable version | software license recorded separately from scientific-data licenses |
| Ensembl VEP | official Ensembl VEP distribution | exact VEP release + matching cache release + assembly | verify Ensembl/third-party data constraints; do not mix cache/tool releases |
| gnomAD | official gnomAD release/download/API service | exact dataset/release selector; release identity where publisher supplies one | record current data-use policy; API selectors are not invented immutable releases |
| ClinGen Allele Registry | official ClinGen services | endpoint + observed API/resource version semantics | public read access and authenticated write operations must remain distinct |
| ClinGen CSpec | official ClinGen CSpec Registry | specification ID + version + status | only released/approved specifications may qualify for governed automation |
| HPO | official HPO/JAX distribution | exact ontology release | record ontology release and current license/terms |
| PharmGKB / ClinPGx | official ClinPGx/PharmGKB service | exact API/data release semantics | record current Data Usage Policy and license; do not assume unrestricted commercial redistribution |
| OMIM | official OMIM service | exact release/access identity | license/access approval is mandatory before any automated use that requires restricted access |
| UCSC chain files | official UCSC downloads | exact source/target assembly + chain file checksum | commercial use may require a UCSC license; do not activate without the organization's entitlement |
| HGNC/NCBI gene identifiers | official HGNC/NCBI resources | exact release/API semantics | source and release provenance required |
| dbSNP | NCBI | exact build/release identity | NCBI source/usage policy and exact artifact provenance required |

## No generic downloader

A future provider may not simply accept an arbitrary URL and call it a scientific
resource. It must implement a source-specific adapter that knows:

1. how the publisher identifies a release;
2. how the exact artifact is located;
3. whether the artifact is mutable or archived;
4. how integrity is established;
5. what authentication is required;
6. what license/terms apply;
7. what resource-specific qualification checks are required;
8. what downstream analyses are affected by a new version.

## Activation rule

Discovery and staging never activate a resource.

The minimum lifecycle is:

DISCOVERED -> CANDIDATE -> STAGED -> QUALIFIED -> APPROVAL_PENDING
-> ORGANIZATION DECISION -> ACTIVE / REJECTED / DEFERRED

If source authenticity, licensing, access, or integrity cannot be established,
the resource remains blocked from production activation.

## Reproducibility rule

Every analysis stores the exact resource version/identity and checksum used.
A later release can generate a reanalysis candidate but cannot overwrite the
resource identity attached to an existing signed analysis.

## Current verified source families

The implementation work should use the publisher's current documentation rather
than stale blog posts or third-party download mirrors. Examples include:

- NCBI ClinVar release/download documentation
- NCBI data-use policy
- Genome Reference Consortium human assembly pages
- official samtools/bcftools repository and documentation
- official Ensembl VEP release/cache documentation
- official gnomAD release/changelog/download resources
- official ClinGen downloads/API/CSpec resources
- official ClinPGx API and data-use policy
- official HPO/JAX distribution
- official UCSC download/license pages

These source references are intentionally kept at the authoritative landing/documentation
level; provider adapters must record the exact artifact endpoint and release identity
they actually consume.
