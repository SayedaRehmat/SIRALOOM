"""Explicit implementation-qualification matrix for VCF feature families.

This registry reports what SIRALOOM's native validator currently qualifies.
It is deliberately not a substitute for the normative HTS specification and
does not infer support merely because a parser accepts a fileformat label.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VCFFeatureQualification:
    feature_id: str
    specification_scope: str
    status: str
    implementation: str
    evidence: str
    limitation: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "feature_id": self.feature_id,
            "specification_scope": self.specification_scope,
            "status": self.status,
            "implementation": self.implementation,
            "evidence": self.evidence,
            "limitation": self.limitation,
        }


VCF45_FEATURES = (
    (
        "local_allele_encoding",
        "VCFv4.5",
        "Native VCFv4.5 local-allele field validation and equivalence checks.",
        "tests/test_vcf_validation.py: VCFv4.5 local-allele cardinality and projection tests",
    ),
    (
        "base_modification_format_fields",
        "VCFv4.5",
        "Native validation of reserved base-modification FORMAT keys, types and value domains.",
        "tests/test_vcf_validation.py: VCFv4.5 base-modification FORMAT tests",
    ),
    (
        "reserved_info_format_definitions",
        "VCFv4.5",
        "Native validation of reserved INFO/FORMAT Number and Type definitions.",
        "tests/test_vcf_validation.py: VCFv4.5 reserved INFO/FORMAT definition tests",
    ),
    (
        "structured_meta_headers",
        "VCFv4.5",
        "Native parsing and validation of structured metadata attributes and identifiers.",
        "tests/test_vcf_validation.py: VCFv4.5 structured-header tests",
    ),
)


def feature_compatibility_for_version(version: str) -> list[dict[str, str | None]]:
    """Return conservative, auditable feature qualifications for one VCF version."""
    if version not in {f"VCFv4.{minor}" for minor in range(0, 6)}:
        raise ValueError(f"Unsupported VCF specification version: {version!r}")

    qualifications: list[VCFFeatureQualification] = []
    for feature_id, scope, implementation, evidence in VCF45_FEATURES:
        if version == "VCFv4.5":
            qualifications.append(
                VCFFeatureQualification(
                    feature_id=feature_id,
                    specification_scope=scope,
                    status="NATIVE_VALIDATED",
                    implementation=implementation,
                    evidence=evidence,
                )
            )
        else:
            qualifications.append(
                VCFFeatureQualification(
                    feature_id=feature_id,
                    specification_scope=scope,
                    status="NOT_APPLICABLE_TO_DECLARED_VERSION",
                    implementation="Not enabled by the declared-version compatibility profile.",
                    evidence="HTS specifications version registry",
                    limitation="Do not interpret this status as evidence that an older-version file may use this feature.",
                )
            )

    if version in {"VCFv4.3", "VCFv4.4", "VCFv4.5"}:
        qualifications.append(
            VCFFeatureQualification(
                feature_id="external_assembly_contig_references",
                specification_scope="VCFv4.3+",
                status="UNSUPPORTED",
                implementation="The native validator rejects angle-bracketed external-assembly contig references.",
                evidence="tests/test_vcf_validation.py: test_vcf43_plus_external_assembly_contig_is_explicitly_unsupported",
                limitation="Files requiring ##assembly external contig resolution must not proceed through this native validation path.",
            )
        )
    else:
        qualifications.append(
            VCFFeatureQualification(
                feature_id="external_assembly_contig_references",
                specification_scope="VCFv4.3+",
                status="NOT_APPLICABLE_TO_DECLARED_VERSION",
                implementation="Not applicable to this declared specification version.",
                evidence="HTS specifications version registry",
            )
        )

    return [item.as_dict() for item in qualifications]
