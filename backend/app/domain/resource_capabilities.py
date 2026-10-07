"""Capability and deployment policy model for governed SIRALOOM resources.

A resource being present in the global catalog does not make it executable for an
organization. Execution requires a qualified provider implementation plus an
organization-approved binding (or the explicit SIRALOOM trial policy).

GeneBe is intentionally a trial/evaluation provider in SIRALOOM. It is never a
laboratory execution provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ResourceCapability(StrEnum):
    REFERENCE = "REFERENCE"
    NORMALIZATION = "NORMALIZATION"
    ANNOTATION = "ANNOTATION"
    POPULATION_FREQUENCY = "POPULATION_FREQUENCY"
    CLINICAL_VARIANT = "CLINICAL_VARIANT"
    GENE_DISEASE = "GENE_DISEASE"
    PHENOTYPE = "PHENOTYPE"
    COMPUTATIONAL = "COMPUTATIONAL"
    SPLICING = "SPLICING"
    LITERATURE = "LITERATURE"
    FUNCTIONAL = "FUNCTIONAL"
    FAMILY_SEGREGATION = "FAMILY_SEGREGATION"
    ACMG_SPECIFICATION = "ACMG_SPECIFICATION"


class ResourceExecutionAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    PROVIDER_NOT_IMPLEMENTED = "PROVIDER_NOT_IMPLEMENTED"
    INCOMPATIBLE = "INCOMPATIBLE"
    NOT_EXECUTABLE = "NOT_EXECUTABLE"


TRIAL_ONLY_PROVIDERS = frozenset({"GeneBe"})


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: ResourceCapability
    required: bool = False
    execution_when: str = "ALWAYS"
    description: str = ""


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    capabilities: frozenset[ResourceCapability]
    supported_builds: frozenset[str] = frozenset()
    trial_only: bool = False


def provider_allowed_in_deployment(provider_id: str, *, is_trial: bool) -> bool:
    """Apply product deployment policy, independent of resource registration."""
    if provider_id in TRIAL_ONLY_PROVIDERS:
        return is_trial
    return True


def infer_capabilities(
    *,
    resource_type: str,
    provider: str,
    metadata: dict | None = None,
) -> frozenset[ResourceCapability]:
    """Resolve capabilities from governed metadata, then safe built-in identities.

    Explicit metadata is authoritative. Built-in mappings only describe resources
    SIRALOOM already understands; they do not grant execution permission.
    """
    metadata = metadata or {}
    raw = metadata.get("capabilities")
    if isinstance(raw, (list, tuple, set)):
        values = frozenset(
            ResourceCapability(str(item).strip().upper())
            for item in raw
            if str(item).strip().upper() in ResourceCapability.__members__
        )
        if values:
            return values

    p = provider.strip()
    r = resource_type.strip().upper()
    mapping = {
        ("GeneBe", "ANNOTATION"): {
            ResourceCapability.ANNOTATION,
        },
        ("VEP", "ANNOTATION"): {
            ResourceCapability.ANNOTATION,
        },
        ("GeneBe", "POPULATION"): {
            ResourceCapability.POPULATION_FREQUENCY,
        },
        ("gnomAD", "POPULATION"): {
            ResourceCapability.POPULATION_FREQUENCY,
        },
        ("gnomad-graphql", "POPULATION"): {
            ResourceCapability.POPULATION_FREQUENCY,
        },
        ("gnomad-local-tabix", "POPULATION"): {
            ResourceCapability.POPULATION_FREQUENCY,
        },
        ("NCBI ClinVar", "EVIDENCE"): {
            ResourceCapability.CLINICAL_VARIANT,
        },
        ("ClinVar", "EVIDENCE"): {
            ResourceCapability.CLINICAL_VARIANT,
        },
        ("ClinGen Variant Pathogenicity", "EVIDENCE"): {
            ResourceCapability.CLINICAL_VARIANT,
        },
        ("ClinGen Gene-Disease Validity", "EVIDENCE"): {
            ResourceCapability.GENE_DISEASE,
        },
        ("ClinGen CSpec", "ACMG_SPECIFICATION"): {
            ResourceCapability.ACMG_SPECIFICATION,
        },
    }
    return frozenset(mapping.get((p, r), set()))


def requirements_for_workflow(
    *,
    phenotype_requested: bool,
    family_data_present: bool,
) -> tuple[CapabilityRequirement, ...]:
    requirements = [
        CapabilityRequirement(ResourceCapability.REFERENCE, required=True),
        CapabilityRequirement(ResourceCapability.NORMALIZATION, required=True),
        CapabilityRequirement(ResourceCapability.ANNOTATION, required=True),
        CapabilityRequirement(ResourceCapability.POPULATION_FREQUENCY),
        CapabilityRequirement(ResourceCapability.CLINICAL_VARIANT),
        CapabilityRequirement(ResourceCapability.GENE_DISEASE),
        CapabilityRequirement(
            ResourceCapability.PHENOTYPE,
            required=phenotype_requested,
            execution_when="PHENOTYPE_PRESENT",
        ),
        CapabilityRequirement(ResourceCapability.COMPUTATIONAL),
        CapabilityRequirement(ResourceCapability.SPLICING),
        CapabilityRequirement(ResourceCapability.LITERATURE),
        CapabilityRequirement(ResourceCapability.FUNCTIONAL),
        CapabilityRequirement(
            ResourceCapability.FAMILY_SEGREGATION,
            required=False,
            execution_when="FAMILY_DATA_PRESENT" if family_data_present else "NOT_APPLICABLE",
        ),
        CapabilityRequirement(ResourceCapability.ACMG_SPECIFICATION),
    ]
    return tuple(requirements)


# Stable resource-profile vocabulary. These identifiers are intentionally kept
# separate from the older ResourceCapability enum above so existing workflow
# capability checks remain backward-compatible while profile resolution can
# express concrete scientific resource classes.
REFERENCE_PACKAGE = "REFERENCE_PACKAGE"
ANNOTATION_ENGINE = "ANNOTATION_ENGINE"
ANNOTATION_CACHE = "ANNOTATION_CACHE"
POPULATION = "POPULATION"
POPULATION_SECONDARY = "POPULATION_SECONDARY"
CLINICAL_DATABASE = "CLINICAL_DATABASE"
PHENOTYPE_ONTOLOGY = "PHENOTYPE_ONTOLOGY"
COMPUTATIONAL_PREDICTOR = "COMPUTATIONAL_PREDICTOR"
SPLICING_PREDICTOR = "SPLICING_PREDICTOR"
FUNCTIONAL_EVIDENCE = "FUNCTIONAL_EVIDENCE"
LITERATURE_PROVIDER = "LITERATURE_PROVIDER"
ACMG_RULE_SPECIFICATION = "ACMG_RULE_SPECIFICATION"
VARIANT_IDENTITY = "VARIANT_IDENTITY"
INTERNAL_LAB_EVIDENCE = "INTERNAL_LAB_EVIDENCE"
DISEASE_ONTOLOGY = "DISEASE_ONTOLOGY"
GENE_PANEL = "GENE_PANEL"
DOSAGE_SENSITIVITY = "DOSAGE_SENSITIVITY"


@dataclass(frozen=True)
class ScientificProvider:
    provider_id: str
    resource_type: str
    access_methods: tuple[str, ...] = ()
    requires_organization_license: bool = False
    description: str = ""


_SCIENTIFIC_PROVIDERS = {
    "VEP": ScientificProvider("VEP", ANNOTATION_ENGINE, ("LOCAL", "API", "HTTPS")),
    "GENEBE": ScientificProvider("GENEBE", ANNOTATION_ENGINE, ("API", "HTTPS")),
    "CLINVAR": ScientificProvider("CLINVAR", CLINICAL_DATABASE, ("LOCAL", "API", "HTTPS")),
    "NCBI CLINVAR": ScientificProvider("NCBI CLINVAR", CLINICAL_DATABASE, ("LOCAL", "API", "HTTPS")),
    "GNOMAD": ScientificProvider("GNOMAD", POPULATION, ("LOCAL", "API", "HTTPS")),
    "GNOMAD-GRAPHL": ScientificProvider("GNOMAD-GRAPHL", POPULATION, ("LOCAL", "API", "HTTPS")),
    "CLINGEN": ScientificProvider("CLINGEN", ACMG_RULE_SPECIFICATION, ("LOCAL", "API", "HTTPS")),
    "HPO": ScientificProvider("HPO", PHENOTYPE_ONTOLOGY, ("LOCAL", "API", "HTTPS")),
    "PUBMED": ScientificProvider("PUBMED", LITERATURE_PROVIDER, ("API", "HTTPS")),
    "PMC": ScientificProvider("PMC", LITERATURE_PROVIDER, ("API", "HTTPS")),
    "OMIM": ScientificProvider("OMIM", GENE_DISEASE, ("LOCAL", "API", "HTTPS"), True),
    "SPLICEAI": ScientificProvider("SPLICEAI", SPLICING_PREDICTOR, ("LOCAL", "API", "HTTPS"), True),
    "DBNSFP": ScientificProvider("DBNSFP", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE")),
    "CADD": ScientificProvider("CADD", COMPUTATIONAL_PREDICTOR, ("LOCAL", "API", "HTTPS")),
    "REVEL": ScientificProvider("REVEL", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE")),
    "ALPHAMISSENSE": ScientificProvider("ALPHAMISSENSE", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE", "API", "HTTPS")),
}


def get_scientific_provider(provider_id: str) -> ScientificProvider:
    key = str(provider_id or "").strip().upper()
    try:
        return _SCIENTIFIC_PROVIDERS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported scientific provider: {provider_id!r}") from exc


def supported_scientific_providers() -> tuple[str, ...]:
    return tuple(sorted(_SCIENTIFIC_PROVIDERS))


def get_resource_capability(resource_type: str) -> object:
    key = str(resource_type or "").strip().upper()
    if key in {
        REFERENCE_PACKAGE, ANNOTATION_ENGINE, ANNOTATION_CACHE, POPULATION,
        POPULATION_SECONDARY, CLINICAL_DATABASE, GENE_DISEASE, PHENOTYPE_ONTOLOGY,
        COMPUTATIONAL_PREDICTOR, SPLICING_PREDICTOR, FUNCTIONAL_EVIDENCE,
        LITERATURE_PROVIDER, ACMG_RULE_SPECIFICATION, VARIANT_IDENTITY,
        INTERNAL_LAB_EVIDENCE, DISEASE_ONTOLOGY, GENE_PANEL, DOSAGE_SENSITIVITY,
    }:
        return key
    raise ValueError(f"unsupported resource type: {resource_type!r}")


def supported_resource_types() -> tuple[str, ...]:
    return tuple(sorted({
        REFERENCE_PACKAGE, ANNOTATION_ENGINE, ANNOTATION_CACHE, POPULATION,
        POPULATION_SECONDARY, CLINICAL_DATABASE, GENE_DISEASE, PHENOTYPE_ONTOLOGY,
        COMPUTATIONAL_PREDICTOR, SPLICING_PREDICTOR, FUNCTIONAL_EVIDENCE,
        LITERATURE_PROVIDER, ACMG_RULE_SPECIFICATION, VARIANT_IDENTITY,
        INTERNAL_LAB_EVIDENCE, DISEASE_ONTOLOGY, GENE_PANEL, DOSAGE_SENSITIVITY,
    }))
