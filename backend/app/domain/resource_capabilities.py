"""Machine-readable scientific resource capability catalog.

This module defines what SIRALOOM knows about a resource *type*. It does not
register a laboratory's concrete installation. Concrete resources remain
versioned records in the resource registry and must be qualified before use.

The catalog deliberately describes capabilities and dependencies rather than
hard-coding filesystem paths or assuming that every laboratory owns every
resource.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


class ResourceCapabilityError(ValueError):
    """Raised when an unknown or internally inconsistent resource type is used."""


# Canonical resource-type identifiers. These are stable application vocabulary;
# concrete providers/releases are registered separately.
REFERENCE_PACKAGE: Final = "REFERENCE_PACKAGE"
ANNOTATION_ENGINE: Final = "ANNOTATION_ENGINE"
ANNOTATION_CACHE: Final = "ANNOTATION_CACHE"
POPULATION: Final = "POPULATION"
POPULATION_SECONDARY: Final = "POPULATION_SECONDARY"
CLINICAL_DATABASE: Final = "CLINICAL_DATABASE"
GENE_DISEASE: Final = "GENE_DISEASE"
PHENOTYPE_ONTOLOGY: Final = "PHENOTYPE_ONTOLOGY"
COMPUTATIONAL_PREDICTOR: Final = "COMPUTATIONAL_PREDICTOR"
SPLICING_PREDICTOR: Final = "SPLICING_PREDICTOR"
FUNCTIONAL_EVIDENCE: Final = "FUNCTIONAL_EVIDENCE"
LITERATURE_PROVIDER: Final = "LITERATURE_PROVIDER"
ACMG_RULE_SPECIFICATION: Final = "ACMG_RULE_SPECIFICATION"
VARIANT_IDENTITY: Final = "VARIANT_IDENTITY"
INTERNAL_LAB_EVIDENCE: Final = "INTERNAL_LAB_EVIDENCE"
DISEASE_ONTOLOGY: Final = "DISEASE_ONTOLOGY"
GENE_PANEL: Final = "GENE_PANEL"
DOSAGE_SENSITIVITY: Final = "DOSAGE_SENSITIVITY"


@dataclass(frozen=True)
class ResourceCapability:
    """Scientific execution contract for one resource class."""

    resource_type: str
    role: str
    required_inputs: tuple[str, ...]
    produced_outputs: tuple[str, ...]
    preferred_access_methods: tuple[str, ...]
    supported_execution_modes: tuple[str, ...]
    requires_genome_build: bool
    requires_version: bool
    requires_checksum_for_local_artifact: bool
    required_dependency_types: tuple[str, ...]
    optional_dependency_types: tuple[str, ...]
    evidence_types: tuple[str, ...]
    clinical_interpretation: bool
    bulk_local_preferred: bool
    online_service_supported: bool


_RESOURCE_CAPABILITIES: Final[dict[str, ResourceCapability]] = {
    REFERENCE_PACKAGE: ResourceCapability(
        REFERENCE_PACKAGE,
        "Authoritative reference assembly for representation and normalization.",
        ("input_variant",),
        ("reference_sequence", "contig_manifest", "reference_identity"),
        ("LOCAL", "FILE", "LOCAL_ONLY"),
        ("LOCAL",),
        True, True, True, (), (),
        ("REFERENCE_CONTEXT",), False, True, False,
    ),
    ANNOTATION_ENGINE: ResourceCapability(
        ANNOTATION_ENGINE,
        "Produces standardized consequence, transcript and variant annotation.",
        ("normalized_variant", "reference_package"),
        ("gene", "transcript", "consequence", "hgvs", "protein_change"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (REFERENCE_PACKAGE,), (ANNOTATION_CACHE,),
        ("CONSEQUENCE",), False, True, True,
    ),
    ANNOTATION_CACHE: ResourceCapability(
        ANNOTATION_CACHE,
        "Versioned offline data required by an annotation engine.",
        ("annotation_engine", "reference_package"),
        ("annotation_cache",),
        ("LOCAL", "FILE", "LOCAL_ONLY"),
        ("LOCAL",),
        True, True, True, (ANNOTATION_ENGINE, REFERENCE_PACKAGE), (),
        (), False, True, False,
    ),
    POPULATION: ResourceCapability(
        POPULATION,
        "Population allele-frequency and count evidence.",
        ("normalized_variant",),
        ("allele_frequency", "allele_count", "allele_number", "population_context"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (REFERENCE_PACKAGE,), (),
        ("POPULATION",), False, True, True,
    ),
    POPULATION_SECONDARY: ResourceCapability(
        POPULATION_SECONDARY,
        "Secondary population-frequency context used to refine interpretation; never replaces the primary gnomAD population resource.",
        ("normalized_variant",),
        ("allele_frequency", "allele_count", "allele_number", "population_context"),
        ("LOCAL", "FILE", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, True, (REFERENCE_PACKAGE,), (),
        ("POPULATION_SECONDARY",), False, True, True,
    ),
    CLINICAL_DATABASE: ResourceCapability(
        CLINICAL_DATABASE,
        "Structured clinical variant assertions and submissions.",
        ("normalized_variant",),
        ("clinical_assertion", "condition", "review_status", "submitter"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (), (),
        ("CLINICAL_DATABASE",), True, True, True,
    ),
    GENE_DISEASE: ResourceCapability(
        GENE_DISEASE,
        "Curated gene-disease validity and related knowledge.",
        ("gene", "disease"),
        ("gene_disease_validity", "curation_metadata"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, False, (), (DISEASE_ONTOLOGY,),
        ("GENE_DISEASE",), True, True, True,
    ),
    PHENOTYPE_ONTOLOGY: ResourceCapability(
        PHENOTYPE_ONTOLOGY,
        "Controlled phenotype vocabulary and phenotype relationships.",
        ("phenotype_term",),
        ("phenotype_identity", "phenotype_relationship"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, False, (), (DISEASE_ONTOLOGY,),
        ("PHENOTYPE",), False, True, True,
    ),
    COMPUTATIONAL_PREDICTOR: ResourceCapability(
        COMPUTATIONAL_PREDICTOR,
        "Calibrated computational evidence used under an applicable rule specification.",
        ("normalized_variant", "annotation"),
        ("prediction_score", "prediction_metadata"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (REFERENCE_PACKAGE,), (ANNOTATION_ENGINE,),
        ("COMPUTATIONAL",), True, True, True,
    ),
    SPLICING_PREDICTOR: ResourceCapability(
        SPLICING_PREDICTOR,
        "Splicing-impact prediction; output requires criterion-specific interpretation.",
        ("normalized_variant", "reference_package"),
        ("splicing_score", "splicing_metadata"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (REFERENCE_PACKAGE,), (ANNOTATION_ENGINE,),
        ("SPLICING",), True, True, True,
    ),
    FUNCTIONAL_EVIDENCE: ResourceCapability(
        FUNCTIONAL_EVIDENCE,
        "Structured functional observations from validated assays or curated sources.",
        ("variant",),
        ("functional_observation", "assay_metadata"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, False, (), (),
        ("FUNCTIONAL",), True, True, True,
    ),
    LITERATURE_PROVIDER: ResourceCapability(
        LITERATURE_PROVIDER,
        "Searches permitted scientific publication metadata/content for candidate evidence.",
        ("variant", "gene", "disease"),
        ("publication", "literature_evidence_candidate", "citation"),
        ("API", "HTTPS", "LOCAL"),
        ("REMOTE_API", "LOCAL"),
        False, True, False, (), (),
        ("LITERATURE",), True, False, True,
    ),
    ACMG_RULE_SPECIFICATION: ResourceCapability(
        ACMG_RULE_SPECIFICATION,
        "Versioned ACMG/AMP and ClinGen criterion-specific rule specifications.",
        ("evidence_set", "gene", "disease"),
        ("criterion_assessment", "classification"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, True, (), (GENE_DISEASE,),
        ("ACMG_CRITERION",), True, True, True,
    ),
    VARIANT_IDENTITY: ResourceCapability(
        VARIANT_IDENTITY,
        "Stable variant identity/cross-reference representation.",
        ("normalized_variant",),
        ("variant_identifier", "cross_reference"),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        True, True, False, (REFERENCE_PACKAGE,), (),
        ("VARIANT_IDENTITY",), False, True, True,
    ),
    INTERNAL_LAB_EVIDENCE: ResourceCapability(
        INTERNAL_LAB_EVIDENCE,
        "Organization-controlled prior observations and curated evidence.",
        ("variant",),
        ("internal_observation", "internal_classification", "internal_frequency"),
        ("LOCAL", "API"),
        ("LOCAL", "REMOTE_API"),
        False, True, True, (), (),
        ("INTERNAL_LAB",), True, True, True,
    ),
    DISEASE_ONTOLOGY: ResourceCapability(
        DISEASE_ONTOLOGY,
        "Controlled disease identifiers used to align evidence and rules.",
        ("disease_term",),
        ("disease_identity",),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, False, (), (),
        ("DISEASE",), False, True, True,
    ),
    GENE_PANEL: ResourceCapability(
        GENE_PANEL,
        "Versioned laboratory test scope defining genes/regions under review.",
        ("analysis_profile",),
        ("gene_scope",),
        ("LOCAL", "FILE"),
        ("LOCAL",),
        False, True, True, (), (),
        ("TEST_SCOPE",), False, True, False,
    ),
    DOSAGE_SENSITIVITY: ResourceCapability(
        DOSAGE_SENSITIVITY,
        "Curated dosage sensitivity evidence for applicable genes/regions.",
        ("gene_or_region",),
        ("dosage_assertion",),
        ("LOCAL", "API", "HTTPS"),
        ("LOCAL", "REMOTE_API"),
        False, True, False, (), (),
        ("DOSAGE",), True, True, True,
    ),
}


@dataclass(frozen=True)
class ScientificProvider:
    """Known provider identity and its canonical SIRALOOM resource class."""

    provider_id: str
    resource_type: str
    access_methods: tuple[str, ...]
    requires_organization_license: bool
    description: str


_SCIENTIFIC_PROVIDERS: Final[dict[str, ScientificProvider]] = {
    "VEP": ScientificProvider(
        "VEP", ANNOTATION_ENGINE, ("LOCAL", "API", "HTTPS"), False,
        "Ensembl Variant Effect Predictor; consequence/transcript annotation.",
    ),
    "GENEBE": ScientificProvider(
        "GENEBE", ANNOTATION_ENGINE, ("API", "HTTPS"), False,
        "GeneBe annotation/evidence service; provider-specific output must be normalized into SIRALOOM evidence.",
    ),
    "CLINVAR": ScientificProvider(
        "CLINVAR", CLINICAL_DATABASE, ("LOCAL", "API", "HTTPS"), False,
        "NCBI ClinVar clinical variant assertions and submissions.",
    ),
    "GNOMAD": ScientificProvider(
        "GNOMAD", POPULATION, ("LOCAL", "API", "HTTPS"), False,
        "gnomAD population allele-frequency data; local indexed or approved query execution.",
    ),
    "CLINGEN": ScientificProvider(
        "CLINGEN", ACMG_RULE_SPECIFICATION, ("LOCAL", "API", "HTTPS"), False,
        "ClinGen curated gene/disease and variant-classification specifications.",
    ),
    "HPO": ScientificProvider(
        "HPO", PHENOTYPE_ONTOLOGY, ("LOCAL", "API", "HTTPS"), False,
        "Human Phenotype Ontology terminology and phenotype relationships.",
    ),
    "PUBMED": ScientificProvider(
        "PUBMED", LITERATURE_PROVIDER, ("API", "HTTPS"), False,
        "NCBI PubMed literature search/retrieval provider.",
    ),
    "PMC": ScientificProvider(
        "PMC", LITERATURE_PROVIDER, ("API", "HTTPS"), False,
        "NCBI PubMed Central content provider; access and reuse remain source/license controlled.",
    ),
    "OMIM": ScientificProvider(
        "OMIM", GENE_DISEASE, ("LOCAL", "API", "HTTPS"), True,
        "OMIM gene/phenotype knowledge; use only under the laboratory's licensed access terms.",
    ),
    "SPLICEAI": ScientificProvider(
        "SPLICEAI", SPLICING_PREDICTOR, ("LOCAL", "API", "HTTPS"), True,
        "SpliceAI splice-impact prediction; deployment/license terms must be qualified.",
    ),
    "DBNSFP": ScientificProvider(
        "DBNSFP", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE"), False,
        "dbNSFP aggregated functional-prediction annotations.",
    ),
    "CADD": ScientificProvider(
        "CADD", COMPUTATIONAL_PREDICTOR, ("LOCAL", "API", "HTTPS"), False,
        "CADD deleteriousness prediction; score provenance and release are retained.",
    ),
    "REVEL": ScientificProvider(
        "REVEL", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE"), False,
        "REVEL ensemble missense prediction.",
    ),
    "ALPHAMISSENSE": ScientificProvider(
        "ALPHAMISSENSE", COMPUTATIONAL_PREDICTOR, ("LOCAL", "FILE", "API", "HTTPS"), False,
        "AlphaMissense missense prediction resource; score/model release is retained.",
    ),
}


def get_scientific_provider(provider_id: str) -> ScientificProvider:
    key = str(provider_id or "").strip().upper()
    try:
        return _SCIENTIFIC_PROVIDERS[key]
    except KeyError as exc:
        raise ResourceCapabilityError(f"unsupported scientific provider: {provider_id!r}") from exc


def supported_scientific_providers() -> tuple[str, ...]:
    return tuple(sorted(_SCIENTIFIC_PROVIDERS))


def get_resource_capability(resource_type: str) -> ResourceCapability:
    key = str(resource_type or "").strip().upper()
    try:
        return _RESOURCE_CAPABILITIES[key]
    except KeyError as exc:
        raise ResourceCapabilityError(f"unsupported resource type: {resource_type!r}") from exc


def supported_resource_types() -> tuple[str, ...]:
    return tuple(sorted(_RESOURCE_CAPABILITIES))


def validate_capability_dependencies(capability: ResourceCapability) -> None:
    if capability.resource_type in capability.required_dependency_types:
        raise ResourceCapabilityError(
            f"resource type {capability.resource_type!r} cannot require itself"
        )
    if capability.resource_type in capability.optional_dependency_types:
        raise ResourceCapabilityError(
            f"resource type {capability.resource_type!r} cannot optionally depend on itself"
        )
    if set(capability.required_dependency_types) & set(capability.optional_dependency_types):
        raise ResourceCapabilityError(
            f"resource type {capability.resource_type!r} has overlapping required and optional dependencies"
        )


for _capability in _RESOURCE_CAPABILITIES.values():
    validate_capability_dependencies(_capability)
