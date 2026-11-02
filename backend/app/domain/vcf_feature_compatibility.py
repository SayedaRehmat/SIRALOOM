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


VCF_CORE_FEATURES = (
    (
        "breakend_replacement_and_mate_links",
        "VCFv4.1+",
        "Native breakend ALT grammar, reciprocal remote-locus and MATEID relationship validation.",
        "tests/test_vcf_conformance_fixtures.py: four_breakend_orientations_valid, reciprocal_breakend_pair_valid, breakend_mate_coordinate_mismatch_invalid, breakend_mate_id_missing_invalid, breakend_mate_not_reciprocal_invalid, breakend_mate_without_record_id_invalid, and breakend_duplicate_record_id_invalid",
    ),
    (
        "genotype_ploidy_number_g_cardinality",
        "VCFv4.1+",
        "Native Number=G cardinality validation derived from observed sample ploidy and allele count.",
        "tests/test_vcf_conformance_fixtures.py: triploid_number_g_cardinality_valid and triploid_number_g_cardinality_invalid",
    ),
    (
        "symbolic_structural_variant_span",
        "VCFv4.1+",
        "Native symbolic structural allele span validation, including END/SVLEN consistency constraints.",
        "tests/test_vcf_conformance_fixtures.py: symbolic_deletion_valid, symbolic_deletion_missing_span_invalid, symbolic_svlen_end_computed_span_valid, and symbolic_svlen_end_computed_span_mismatch_invalid",
    ),
)

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
        "unspecified_allele_reference_block_len",
        "VCFv4.5",
        "Native validation of per-sample FORMAT/LEN spans for the VCFv4.5 <*> unspecified allele.",
        "tests/test_vcf_conformance_fixtures.py: unspecified_allele_len_reference_block_valid and unspecified_allele_len_end_mismatch_invalid",
    ),
    (
        "structured_meta_headers",
        "VCFv4.5",
        "Native parsing and validation of structured metadata attributes and identifiers.",
        "tests/test_vcf_validation.py: VCFv4.5 structured-header tests",
    ),
    (
        "symbolic_sv_confidence_intervals",
        "VCFv4.5",
        "Native validation of per-ALT CIPOS/CIEND cardinality and interval rules, CILEN confidence bounds, and missing-value placeholders for non-structural alleles, with the VCFv4.5 IMPRECISE exception for precise sequence alleles.",
        "tests/test_vcf_conformance_fixtures.py: symbolic_sv_confidence_intervals_with_nonstructural_alt_valid, symbolic_cipos_cardinality_invalid, symbolic_cipos_interval_invalid, nonstructural_cipos_values_invalid, nonstructural_ciend_values_invalid, symbolic_cilen_cardinality_invalid, symbolic_cilen_bounds_reversed_invalid, nonstructural_cilen_values_invalid",
    ),
)


def feature_compatibility_for_version(version: str) -> list[dict[str, str | None]]:
    """Return conservative, auditable feature qualifications for one VCF version."""
    if version not in {f"VCFv4.{minor}" for minor in range(0, 6)}:
        raise ValueError(f"Unsupported VCF specification version: {version!r}")

    qualifications: list[VCFFeatureQualification] = []
    for feature_id, scope, implementation, evidence in VCF_CORE_FEATURES:
        if version == "VCFv4.0":
            qualifications.append(
                VCFFeatureQualification(
                    feature_id=feature_id,
                    specification_scope=scope,
                    status="NOT_APPLICABLE_TO_DECLARED_VERSION",
                    implementation="This feature qualification is scoped to VCFv4.1 and later.",
                    evidence="HTS specifications version registry",
                    limitation="VCFv4.0 is retained as a legacy parser smoke profile, not a normative conformance target.",
                )
            )
        else:
            qualifications.append(
                VCFFeatureQualification(
                    feature_id=feature_id,
                    specification_scope=scope,
                    status="NATIVE_VALIDATED",
                    implementation=implementation,
                    evidence=evidence,
                )
            )

    qualifications.append(
        VCFFeatureQualification(
            feature_id="gatk_gvcf_non_ref_end_interoperability",
            specification_scope="GATK producer interoperability; not a normative VCF feature",
            status="PRODUCER_INTEROPERABILITY_VALIDATED" if version == "VCFv4.3" else "NOT_QUALIFIED",
            implementation="Validates the GATK <NON_REF> plus INFO/END reference-block dialect only in the explicitly tested VCFv4.3 profile." if version == "VCFv4.3" else "No producer-dialect interoperability fixture is qualified for this declared-version profile.",
            evidence="tests/test_vcf_conformance_fixtures.py: gatk_gvcf_nonvariant_reference_block_valid and gatk_gvcf_nonvariant_reference_block_missing_end_invalid" if version == "VCFv4.3" else "No version-specific GATK gVCF interoperability fixture.",
            limitation="This status is not normative VCF specification conformance and does not imply GATK gVCF import support throughout the pipeline.",
        )
    )
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
