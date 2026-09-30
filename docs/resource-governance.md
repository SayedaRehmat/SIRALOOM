# SIRALOOM scientific resource governance

SIRALOOM treats software, reference packages, annotation databases, population resources, evidence resources, and classification specifications as versioned scientific resources.

## Lifecycle

```text
DISCOVERED / ONBOARDED
        |
        v
     CANDIDATE
        |
        v
    QUALIFICATION
        |
        v
     QUALIFIED
        |
        v
       ACTIVE
        |
        v
   SUPERSEDED
```

Discovery never activates a resource. A resource can become ACTIVE only after a recorded successful qualification. Historical analyses retain their resource snapshots.

## Automatic provider discovery

Provider adapters are loaded through the Python entry-point group `siraloom.resource_providers`. A provider implements `discover()` and returns immutable candidate descriptors. Celery Beat runs the discovery scan daily.

This supports future integrations without editing the database or core workflow for every release. A future SIRALOOM release can ship an adapter for a new source; once installed, its releases are discovered into the registry as CANDIDATE resources.

An arbitrary external database cannot be safely interpreted merely because it exists. Its adapter must declare its identity, version semantics, access method, assembly scope where applicable, checksum/provenance, and qualification contract. This is deliberate: automatic discovery is not automatic clinical adoption.

## Laboratory resources

Resources can be organization-scoped. Labs can onboard their own resources as CANDIDATE records. Platform-wide resources remain organization-independent. Tenant visibility is enforced by the resource API.

Examples include a laboratory's validated local population database, local annotation snapshot, reference package, or licensed evidence source.

## Production activation

Production activation requires:

1. the exact resource identity/version to be registered;
2. integrity verification, including checksum where applicable;
3. the resource-specific qualification suite and golden data where applicable;
4. a recorded qualification result and actor;
5. explicit activation;
6. immutable analysis provenance retaining the activated resource identity.

Software upgrades and database releases therefore follow the same governance model, while their qualification tests remain resource-specific.

## Compatibility examples

- BCFtools: executable version plus command contract and golden VCF/reference qualification.
- VEP: executable version plus compatible cache/release and reference assembly.
- ClinVar: archived release identity and file/API provenance.
- gnomAD: dataset/release or API selector plus request/response provenance.
- Reference packages: assembly identity, FASTA/FAI checksums, exact contig manifest, and package checksum.
- Future sources: the same registry/lifecycle, with a source-specific adapter and qualification contract.

## Why activation is controlled

Scientific resources change at different rates and have different semantics. ClinVar publishes weekly updates and monthly archived releases, while Ensembl documents that VEP cache versions should correspond to the VEP installation version. These differences are why SIRALOOM has a common governance lifecycle but does not use one generic qualification algorithm for every resource.