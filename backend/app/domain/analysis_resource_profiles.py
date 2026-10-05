"""Machine-readable analysis profiles.

Profiles describe the scientific capability envelope of an analysis. They do not
register, activate, or silently download resources. Concrete resources are
resolved from the governed registry at analysis preflight time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from backend.app.domain.resource_capabilities import (
    ACMG_RULE_SPECIFICATION,
    ANNOTATION_ENGINE,
    CLINICAL_DATABASE,
    COMPUTATIONAL_PREDICTOR,
    GENE_DISEASE,
    INTERNAL_LAB_EVIDENCE,
    LITERATURE_PROVIDER,
    PHENOTYPE_ONTOLOGY,
    POPULATION,
    POPULATION_SECONDARY,
    REFERENCE_PACKAGE,
    SPLICING_PREDICTOR,
)


@dataclass(frozen=True)
class ProfileResourceRequirement:
    capability: str
    required: bool
    preferred_providers: tuple[str, ...] = ()
    genome_build_required: bool = True
    license_required: bool = False


@dataclass(frozen=True)
class AnalysisResourceProfile:
    profile_id: str
    version: str
    assay_scope: str
    genome_build: str
    requirements: tuple[ProfileResourceRequirement, ...]
    description: str

    @property
    def required_capabilities(self) -> tuple[str, ...]:
        return tuple(r.capability for r in self.requirements if r.required)

    @property
    def optional_capabilities(self) -> tuple[str, ...]:
        return tuple(r.capability for r in self.requirements if not r.required)


_COMMON_OPTIONAL = (
    ProfileResourceRequirement(CLINICAL_DATABASE, False, ("CLINVAR",)),
    ProfileResourceRequirement(GENE_DISEASE, False, ("OMIM",), genome_build_required=False, license_required=True),
    ProfileResourceRequirement(PHENOTYPE_ONTOLOGY, False, ("HPO",), genome_build_required=False),
    ProfileResourceRequirement(COMPUTATIONAL_PREDICTOR, False, ("CADD", "REVEL", "DBNSFP", "ALPHAMISSENSE")),
    ProfileResourceRequirement(SPLICING_PREDICTOR, False, ("SPLICEAI",), license_required=True),
    ProfileResourceRequirement(LITERATURE_PROVIDER, False, ("PUBMED", "PMC"), genome_build_required=False),
    ProfileResourceRequirement(INTERNAL_LAB_EVIDENCE, False, (), genome_build_required=False, license_required=True),
)


ANALYSIS_RESOURCE_PROFILES: Final[dict[str, AnalysisResourceProfile]] = {
    "WES_GRCh38_STANDARD": AnalysisResourceProfile(
        profile_id="WES_GRCh38_STANDARD",
        version="1",
        assay_scope="WES",
        genome_build="GRCh38",
        requirements=(
            ProfileResourceRequirement(REFERENCE_PACKAGE, True, (), True),
            ProfileResourceRequirement(ANNOTATION_ENGINE, True, ("VEP",), True),
            ProfileResourceRequirement(POPULATION, True, ("GNOMAD",), True),
            ProfileResourceRequirement(
                POPULATION_SECONDARY,
                False,
                ("1000GENOMES", "TOPMED", "MIDDLE_EAST", "INTERNAL_LAB_POPULATION"),
                True,
            ),
            ProfileResourceRequirement(ACMG_RULE_SPECIFICATION, True, ("CLINGEN",), False),
            *_COMMON_OPTIONAL,
        ),
        description="Standard germline exome interpretation profile for GRCh38.",
    ),
    "WGS_GRCh38_STANDARD": AnalysisResourceProfile(
        profile_id="WGS_GRCh38_STANDARD",
        version="1",
        assay_scope="WGS",
        genome_build="GRCh38",
        requirements=(
            ProfileResourceRequirement(REFERENCE_PACKAGE, True, (), True),
            ProfileResourceRequirement(ANNOTATION_ENGINE, True, ("VEP",), True),
            ProfileResourceRequirement(POPULATION, True, ("GNOMAD",), True),
            ProfileResourceRequirement("POPULATION_SECONDARY", False, ("1000GENOMES", "TOPMED", "MIDDLE_EAST", "INTERNAL_LAB_POPULATION"), True),
            ProfileResourceRequirement(ACMG_RULE_SPECIFICATION, True, ("CLINGEN",), False),
            *_COMMON_OPTIONAL,
        ),
        description="Standard germline genome interpretation profile for GRCh38.",
    ),
    "WES_GRCh37_STANDARD": AnalysisResourceProfile(
        profile_id="WES_GRCh37_STANDARD",
        version="1",
        assay_scope="WES",
        genome_build="GRCh37",
        requirements=(
            ProfileResourceRequirement(REFERENCE_PACKAGE, True, (), True),
            ProfileResourceRequirement(ANNOTATION_ENGINE, True, ("VEP",), True),
            ProfileResourceRequirement(POPULATION, True, ("GNOMAD",), True),
            ProfileResourceRequirement(
                POPULATION_SECONDARY,
                False,
                ("1000GENOMES", "TOPMED", "MIDDLE_EAST", "INTERNAL_LAB_POPULATION"),
                True,
            ),
            ProfileResourceRequirement(ACMG_RULE_SPECIFICATION, True, ("CLINGEN",), False),
            *_COMMON_OPTIONAL,
        ),
        description="Standard germline exome interpretation profile for GRCh37.",
    ),
}


def get_analysis_resource_profile(profile_id: str) -> AnalysisResourceProfile:
    key = str(profile_id or "").strip()
    try:
        return ANALYSIS_RESOURCE_PROFILES[key]
    except KeyError as exc:
        normalized = key.casefold()
        for profile_key, profile in ANALYSIS_RESOURCE_PROFILES.items():
            if profile_key.casefold() == normalized:
                return profile
        raise KeyError(f"unknown analysis resource profile: {profile_id!r}") from exc
def supported_analysis_resource_profiles() -> tuple[str, ...]:
    return tuple(sorted(ANALYSIS_RESOURCE_PROFILES))
