"""Version-aware VCF specification compatibility metadata.

The validator remains the normative implementation of record-level checks.
This registry exposes specification identity and provenance; it does not
claim support for unqualified future or legacy major versions.
"""
from __future__ import annotations

from dataclasses import dataclass

HTS_SPECIFICATIONS_REPOSITORY = "https://github.com/samtools/hts-specs"
VCF_45_SPECIFICATION_URL = "https://samtools.github.io/hts-specs/VCFv4.5.pdf"

@dataclass(frozen=True)
class VCFSpecificationProfile:
    version: str
    support_status: str
    validation_mode: str
    specification_repository: str
    specification_document: str | None
    notes: str

VCF_SPECIFICATION_PROFILES: dict[str, VCFSpecificationProfile] = {
    "VCFv4.0": VCFSpecificationProfile(
        version="VCFv4.0",
        support_status="LEGACY_COMPATIBILITY_ONLY",
        validation_mode="LEGACY_PARSER_SMOKE_ONLY",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document=None,
        notes="Retained for parser compatibility only; not a normative conformance target.",
    ),
    "VCFv4.1": VCFSpecificationProfile(
        version="VCFv4.1",
        support_status="SUPPORTED",
        validation_mode="VERSION_AWARE_NATIVE",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.1.pdf",
        notes="Native validation is feature-qualified; consult the feature compatibility matrix for the exact qualified scope.",
    ),
    "VCFv4.2": VCFSpecificationProfile(
        version="VCFv4.2",
        support_status="SUPPORTED",
        validation_mode="VERSION_AWARE_NATIVE",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.2.pdf",
        notes="Native validation is feature-qualified; consult the feature compatibility matrix for the exact qualified scope.",
    ),
    "VCFv4.3": VCFSpecificationProfile(
        version="VCFv4.3",
        support_status="SUPPORTED",
        validation_mode="VERSION_AWARE_NATIVE",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.3.pdf",
        notes="Native validation is feature-qualified; consult the feature compatibility matrix for the exact qualified scope.",
    ),
    "VCFv4.4": VCFSpecificationProfile(
        version="VCFv4.4",
        support_status="SUPPORTED",
        validation_mode="VERSION_AWARE_NATIVE",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document="https://samtools.github.io/hts-specs/VCFv4.4.pdf",
        notes="Native validation is feature-qualified; consult the feature compatibility matrix for the exact qualified scope.",
    ),
    "VCFv4.5": VCFSpecificationProfile(
        version="VCFv4.5",
        support_status="SUPPORTED",
        validation_mode="VERSION_AWARE_NATIVE",
        specification_repository=HTS_SPECIFICATIONS_REPOSITORY,
        specification_document=VCF_45_SPECIFICATION_URL,
        notes="Native validation is feature-qualified; consult the feature compatibility matrix for the exact qualified scope.",
    ),
}

def get_vcf_specification_profile(version: str) -> VCFSpecificationProfile:
    """Return the exact supported profile; unknown versions fail closed."""
    try:
        return VCF_SPECIFICATION_PROFILES[str(version)]
    except KeyError as exc:
        raise ValueError(f"Unsupported VCF specification version: {version!r}") from exc

SUPPORTED_VCF_VERSIONS = frozenset(VCF_SPECIFICATION_PROFILES)