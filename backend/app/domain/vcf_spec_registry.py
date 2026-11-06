"""Version-aware VCF specification compatibility metadata.

A profile is an explicit, immutable statement of the specification identity
and the feature families SIRALOOM has or has not qualified for that version.
Discovering a specification document never creates a parser profile or grants
feature support. New profiles must be added only with implementation and
qualification evidence.
"""
from __future__ import annotations

from dataclasses import dataclass

HTS_SPECIFICATIONS_REPOSITORY = "https://github.com/samtools/hts-specs"
VCF_45_SPECIFICATION_URL = "https://samtools.github.io/hts-specs/VCFv4.5.pdf"
VCF_40_LEGACY_SPECIFICATION_URL = "https://www.internationalgenome.org/wiki/Analysis/vcf4.0/"

VCF_CORE_FEATURE_IDS = frozenset({
    "breakend_replacement_and_mate_links",
    "genotype_ploidy_number_g_cardinality",
    "symbolic_structural_variant_span",
})
VCF45_FEATURE_IDS = frozenset({
    "local_allele_encoding",
    "base_modification_format_fields",
    "reserved_info_format_definitions",
    "unspecified_allele_reference_block_len",
    "structured_meta_headers",
    "symbolic_sv_confidence_intervals",
})
VCF_EXTERNAL_ASSEMBLY_CONTIG_FEATURE_ID = "external_assembly_contig_references"
GATK_GVCF_INTEROPERABILITY_FEATURE_ID = "gatk_gvcf_non_ref_end_interoperability"


@dataclass(frozen=True)
class VCFSpecificationProfile:
    version: str
    support_status: str
    validation_mode: str
    specification_repository: str
    specification_document: str | None
    notes: str
    qualified_feature_ids: frozenset[str] = frozenset()
    unsupported_feature_ids: frozenset[str] = frozenset()
    producer_qualified_feature_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        groups = (
            self.qualified_feature_ids,
            self.unsupported_feature_ids,
            self.producer_qualified_feature_ids,
        )
        if any(not isinstance(group, frozenset) for group in groups):
            raise TypeError("VCF profile feature declarations must be immutable frozensets")
        if any(not feature_id.strip() for group in groups for feature_id in group):
            raise ValueError("VCF profile feature identifiers must be non-empty")
        if (
            self.qualified_feature_ids & self.unsupported_feature_ids
            or self.qualified_feature_ids & self.producer_qualified_feature_ids
            or self.unsupported_feature_ids & self.producer_qualified_feature_ids
        ):
            raise ValueError("A VCF feature cannot have conflicting profile dispositions")


VCF_SPECIFICATION_PROFILES: dict[str, VCFSpecificationProfile] = {
    "VCFv4.0": VCFSpecificationProfile(
        version="VCFv4.0",
        support_status="PARTIAL_LEGACY_SPECIFICATION_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=VCF_40_LEGACY_SPECIFICATION_URL,
        specification_document=VCF_40_LEGACY_SPECIFICATION_URL,
        notes="Historical 1000 Genomes VCFv4.0 profile with version-specific regression vectors; legacy specification qualification remains partial pending atomic clause review, source-byte preservation, complete traceability, and independent real-file qualification.",
    ),
    "VCFv4.1": VCFSpecificationProfile(
        version="VCFv4.1",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.1.pdf",
        notes="The declared version is recognized and a subset of its features is validated. This is not complete normative conformance; consult the requirement traceability matrix and block unqualified features.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS,
    ),
    "VCFv4.2": VCFSpecificationProfile(
        version="VCFv4.2",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.2.pdf",
        notes="The declared version is recognized and a subset of its features is validated. This is not complete normative conformance; consult the requirement traceability matrix and block unqualified features.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS,
    ),
    "VCFv4.3": VCFSpecificationProfile(
        version="VCFv4.3",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.3.pdf",
        notes="The declared version is recognized and a subset of its features is validated. This is not complete normative conformance; consult the requirement traceability matrix and block unqualified features.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS,
        unsupported_feature_ids=frozenset({VCF_EXTERNAL_ASSEMBLY_CONTIG_FEATURE_ID}),
        producer_qualified_feature_ids=frozenset({GATK_GVCF_INTEROPERABILITY_FEATURE_ID}),
    ),
    "VCFv4.4": VCFSpecificationProfile(
        version="VCFv4.4",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.4.pdf",
        notes="The declared version is recognized and a subset of its features is validated. This is not complete normative conformance; consult the requirement traceability matrix and block unqualified features.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS,
        unsupported_feature_ids=frozenset({VCF_EXTERNAL_ASSEMBLY_CONTIG_FEATURE_ID}),
    ),
    "VCFv4.5": VCFSpecificationProfile(
        version="VCFv4.5",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document=VCF_45_SPECIFICATION_URL,
        notes="The declared version is recognized and a subset of its features is validated. This is not complete normative conformance; consult the requirement traceability matrix and block unqualified features.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS | VCF45_FEATURE_IDS,
        unsupported_feature_ids=frozenset({VCF_EXTERNAL_ASSEMBLY_CONTIG_FEATURE_ID}),
    ),
}


def get_vcf_specification_profile(version: str) -> VCFSpecificationProfile:
    """Return the exact registered profile; unknown versions fail closed."""
    try:
        profile = VCF_SPECIFICATION_PROFILES[str(version)]
    except KeyError as exc:
        raise ValueError(f"Unsupported VCF specification version: {version!r}") from exc
    if profile.version != version:
        raise ValueError(f"VCF specification registry key/profile mismatch: {version!r}")
    return profile


SUPPORTED_VCF_VERSIONS = frozenset(VCF_SPECIFICATION_PROFILES)
BUILTIN_VCF_SPECIFICATION_VERSIONS = SUPPORTED_VCF_VERSIONS
