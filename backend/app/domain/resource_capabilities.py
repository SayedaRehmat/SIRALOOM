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
        ("ClinGen", "EVIDENCE"): {
            ResourceCapability.CLINICAL_VARIANT,
            ResourceCapability.GENE_DISEASE,
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
