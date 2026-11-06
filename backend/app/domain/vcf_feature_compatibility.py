"""Explicit implementation-qualification matrix for VCF feature families.

Specification scope and implementation qualification are separate:
a feature can exist in a normative version while SIRALOOM has not qualified
its implementation. The selected immutable VCF specification profile supplies
the per-version disposition; this module does not infer support from version
string ranges or from parser acceptance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.app.domain.vcf_spec_registry import get_vcf_specification_profile


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


@dataclass(frozen=True)
class VCFFeatureDefinition:
    feature_id: str
    specification_scope: str | None
    implementation: str
    evidence: str
    limitation: str | None = None


VCF_FEATURE_DEFINITIONS = (
    VCFFeatureDefinition(
        "breakend_replacement_and_mate_links",
        "VCFv4.1+",
        "Native breakend ALT grammar and reciprocal remote-locus/MATEID validation. VCFv4.1-v4.3 retain Number=. unordered MATEID behavior; VCFv4.4-v4.5 validate Number=A positional ALT-to-mate correspondence, including missing placeholders for non-breakend ALTs.",
        "tests/test_vcf_conformance_fixtures.py: four_breakend_orientations_valid, reciprocal_breakend_pair_valid, breakend_mate_coordinate_mismatch_invalid, breakend_mate_id_missing_invalid, breakend_mate_not_reciprocal_invalid, breakend_mate_without_record_id_invalid, breakend_duplicate_record_id_invalid, breakend_legacy_mateid_unordered_mixed_alt_valid, breakend_mixed_alt_mateid_alignment_valid, breakend_multi_alt_mateid_alignment_valid, breakend_multi_alt_mateid_swapped_invalid, breakend_reciprocal_mateid_wrong_alt_index_invalid, breakend_mixed_alt_mateid_cardinality_invalid, and mateid_reserved_header_definition_invalid",
    ),
    VCFFeatureDefinition(
        "genotype_ploidy_number_g_cardinality",
        "VCFv4.1+",
        "Native Number=G cardinality validation derived from observed sample ploidy and allele count.",
        "tests/test_vcf_conformance_fixtures.py: triploid_number_g_cardinality_valid and triploid_number_g_cardinality_invalid",
    ),
    VCFFeatureDefinition(
        "symbolic_structural_variant_span",
        "VCFv4.1+",
        "Native symbolic structural allele span validation, including END/SVLEN consistency constraints.",
        "tests/test_vcf_conformance_fixtures.py: symbolic_deletion_valid, symbolic_deletion_missing_span_invalid, symbolic_svlen_end_computed_span_valid, and symbolic_svlen_end_computed_span_mismatch_invalid",
    ),
    VCFFeatureDefinition(
        "gatk_gvcf_non_ref_end_interoperability",
        None,
        "Validates the GATK <NON_REF> plus INFO/END reference-block dialect only for the explicitly qualified producer/version combination.",
        "tests/test_vcf_conformance_fixtures.py: gatk_gvcf_nonvariant_reference_block_valid and gatk_gvcf_nonvariant_reference_block_missing_end_invalid",
        "This is producer-dialect interoperability, not normative VCF conformance and not blanket GATK gVCF pipeline support.",
    ),
    VCFFeatureDefinition(
        "local_allele_encoding",
        "VCFv4.5+",
        "Native VCFv4.5 local-allele field validation and equivalence checks.",
        "tests/test_vcf_validation.py: VCFv4.5 local-allele cardinality and projection tests",
    ),
    VCFFeatureDefinition(
        "base_modification_format_fields",
        "VCFv4.5+",
        "Native validation of reserved base-modification FORMAT keys, types and value domains.",
        "tests/test_vcf_validation.py: VCFv4.5 base-modification FORMAT tests",
        "The six case-inconsistent xanthosine aliases (MXaoN/MxaoN, DPMXaoN/DPMxaoN, ADMXaoN/ADMxaoN) are explicitly blocked until the upstream specification maintainers clarify the canonical identifiers.",
    ),
    VCFFeatureDefinition(
        "reserved_info_format_definitions",
        "VCFv4.5+",
        "Native validation of reserved INFO/FORMAT Number and Type definitions.",
        "tests/test_vcf_validation.py: VCFv4.5 reserved INFO/FORMAT definition tests",
    ),
    VCFFeatureDefinition(
        "unspecified_allele_reference_block_len",
        "VCFv4.5+",
        "Native validation of per-sample FORMAT/LEN spans for the VCFv4.5 <*> unspecified allele.",
        "tests/test_vcf_conformance_fixtures.py: unspecified_allele_len_reference_block_valid and unspecified_allele_len_end_mismatch_invalid",
    ),
    VCFFeatureDefinition(
        "structured_meta_headers",
        "VCFv4.5+",
        "Native parsing and validation of structured metadata attributes and identifiers.",
        "tests/test_vcf_validation.py: VCFv4.5 structured-header tests",
    ),
    VCFFeatureDefinition(
        "symbolic_sv_confidence_intervals",
        "VCFv4.5+",
        "Native validation of per-ALT CIPOS/CIEND cardinality and interval rules, CILEN confidence bounds, and missing-value placeholders for non-structural alleles, with the VCFv4.5 IMPRECISE exception for precise sequence alleles.",
        "tests/test_vcf_conformance_fixtures.py: symbolic_sv_confidence_intervals_with_nonstructural_alt_valid, symbolic_cipos_cardinality_invalid, symbolic_cipos_interval_invalid, nonstructural_cipos_values_invalid, nonstructural_ciend_values_invalid, symbolic_cilen_cardinality_invalid, symbolic_cilen_bounds_reversed_invalid, nonstructural_cilen_values_invalid",
    ),
    VCFFeatureDefinition(
        "external_assembly_contig_references",
        "VCFv4.3+",
        "The native validator currently does not resolve external-assembly contig references to a verified sequence resource.",
        "tests/test_vcf_validation.py: test_vcf43_plus_external_assembly_contig_is_explicitly_unsupported",
        "Resolve the exact assembly/sequence resource and qualify reference-aware processing before enabling this capability.",
    ),
)


_VERSION_SCOPE_RE = re.compile(r"^VCFv(?P<major>[0-9]+)\.(?P<minor>[0-9]+)(?P<plus>\+)?$")


def _version_tuple(version: str) -> tuple[int, int]:
    match = _VERSION_SCOPE_RE.fullmatch(version)
    if match is None:
        raise ValueError(f"Invalid VCF specification version scope: {version!r}")
    return int(match.group("major")), int(match.group("minor"))


def _scope_applies(scope: str | None, version: str) -> bool:
    if scope is None:
        return True
    match = _VERSION_SCOPE_RE.fullmatch(scope)
    if match is None:
        raise ValueError(f"Invalid VCF feature specification scope: {scope!r}")
    declared = _version_tuple(version)
    boundary = (int(match.group("major")), int(match.group("minor")))
    if match.group("plus"):
        # A version scope is forward-compatible only within the same major
        # specification family. A new major version requires explicit rules.
        return declared[0] == boundary[0] and declared[1] >= boundary[1]
    return declared == boundary


def feature_compatibility_for_version(version: str) -> list[dict[str, str | None]]:
    """Return the exact registered profile's conservative feature dispositions.

    A newly registered version starts with no qualified features unless its
    immutable profile explicitly lists them. Merely being newer than a known
    version never inherits implementation qualification.
    """
    profile = get_vcf_specification_profile(version)
    qualifications: list[VCFFeatureQualification] = []

    for feature in VCF_FEATURE_DEFINITIONS:
        applies = _scope_applies(feature.specification_scope, profile.version)
        if not applies:
            status = "NOT_APPLICABLE_TO_DECLARED_VERSION"
            implementation = "Not applicable to the declared specification version."
            evidence = "Registered VCF specification profile"
            limitation = None
        elif feature.feature_id in profile.qualified_feature_ids:
            status = "NATIVE_VALIDATED"
            implementation = feature.implementation
            evidence = feature.evidence
            limitation = feature.limitation
        elif feature.feature_id in profile.producer_qualified_feature_ids:
            status = "PRODUCER_INTEROPERABILITY_VALIDATED"
            implementation = feature.implementation
            evidence = feature.evidence
            limitation = feature.limitation
        elif feature.feature_id in profile.unsupported_feature_ids:
            status = "UNSUPPORTED"
            implementation = feature.implementation
            evidence = feature.evidence
            limitation = feature.limitation
        else:
            status = "NOT_QUALIFIED"
            implementation = "No version-specific implementation qualification is registered for this feature."
            evidence = "No approved feature qualification evidence is attached to this specification profile."
            limitation = feature.limitation

        qualifications.append(VCFFeatureQualification(
            feature_id=feature.feature_id,
            specification_scope=feature.specification_scope or "GATK producer interoperability; not a normative VCF feature",
            status=status,
            implementation=implementation,
            evidence=evidence,
            limitation=limitation,
        ))

    return [item.as_dict() for item in qualifications]
