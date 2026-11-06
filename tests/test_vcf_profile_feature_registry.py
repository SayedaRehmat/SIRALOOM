from __future__ import annotations

from backend.app.domain.vcf_feature_compatibility import feature_compatibility_for_version
from backend.app.domain.vcf_spec_registry import (
    VCF_CORE_FEATURE_IDS,
    VCF45_FEATURE_IDS,
    VCFSpecificationProfile,
    VCF_SPECIFICATION_PROFILES,
)


def _matrix(version: str) -> dict[str, dict[str, str | None]]:
    return {
        item["feature_id"]: item
        for item in feature_compatibility_for_version(version)
    }


def test_builtin_feature_dispositions_are_declared_by_their_version_profiles():
    legacy = _matrix("VCFv4.0")
    assert legacy["breakend_replacement_and_mate_links"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"

    v41 = _matrix("VCFv4.1")
    assert v41["breakend_replacement_and_mate_links"]["status"] == "NATIVE_VALIDATED"
    assert v41["local_allele_encoding"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"

    v43 = _matrix("VCFv4.3")
    assert v43["gatk_gvcf_non_ref_end_interoperability"]["status"] == "PRODUCER_INTEROPERABILITY_VALIDATED"
    assert v43["external_assembly_contig_references"]["status"] == "UNSUPPORTED"

    v45 = _matrix("VCFv4.5")
    assert v45["local_allele_encoding"]["status"] == "NATIVE_VALIDATED"
    assert v45["base_modification_format_fields"]["status"] == "NATIVE_VALIDATED"
    assert "xanthosine aliases" in v45["base_modification_format_fields"]["limitation"]
    assert v45["external_assembly_contig_references"]["status"] == "UNSUPPORTED"


def test_new_minor_version_does_not_inherit_implementation_qualification(monkeypatch):
    candidate = VCFSpecificationProfile(
        version="VCFv4.6",
        support_status="CANDIDATE",
        validation_mode="NOT_QUALIFIED",
        specification_repository="https://github.com/samtools/hts-specs",
        specification_document="https://samtools.github.io/hts-specs/VCFv4.6.pdf",
        notes="Synthetic test profile; no parser qualification is claimed.",
    )
    monkeypatch.setitem(VCF_SPECIFICATION_PROFILES, "VCFv4.6", candidate)

    matrix = _matrix("VCFv4.6")

    # A feature introduced by an earlier minor release is in scope, but the
    # new profile must explicitly claim qualification before SIRALOOM does.
    assert matrix["breakend_replacement_and_mate_links"]["status"] == "NOT_QUALIFIED"
    assert matrix["local_allele_encoding"]["status"] == "NOT_QUALIFIED"
    assert matrix["external_assembly_contig_references"]["status"] == "NOT_QUALIFIED"
    assert matrix["gatk_gvcf_non_ref_end_interoperability"]["status"] == "NOT_QUALIFIED"


def test_new_profile_can_qualify_only_explicitly_declared_features(monkeypatch):
    candidate = VCFSpecificationProfile(
        version="VCFv4.6",
        support_status="PARTIAL_FEATURE_QUALIFICATION",
        validation_mode="VERSION_AWARE_PARTIAL",
        specification_repository="https://github.com/samtools/hts-specs",
        specification_document="https://samtools.github.io/hts-specs/VCFv4.6.pdf",
        notes="Synthetic test profile with explicit feature qualification.",
        qualified_feature_ids=VCF_CORE_FEATURE_IDS | VCF45_FEATURE_IDS,
    )
    monkeypatch.setitem(VCF_SPECIFICATION_PROFILES, "VCFv4.6", candidate)

    matrix = _matrix("VCFv4.6")

    assert matrix["breakend_replacement_and_mate_links"]["status"] == "NATIVE_VALIDATED"
    assert matrix["local_allele_encoding"]["status"] == "NATIVE_VALIDATED"
    assert matrix["external_assembly_contig_references"]["status"] == "NOT_QUALIFIED"
    assert matrix["gatk_gvcf_non_ref_end_interoperability"]["status"] == "NOT_QUALIFIED"


def test_new_major_version_does_not_implicitly_inherit_old_major_feature_scope(monkeypatch):
    candidate = VCFSpecificationProfile(
        version="VCFv5.0",
        support_status="CANDIDATE",
        validation_mode="NOT_QUALIFIED",
        specification_repository="https://example.invalid/specifications",
        specification_document=None,
        notes="Synthetic major-version boundary test.",
    )
    monkeypatch.setitem(VCF_SPECIFICATION_PROFILES, "VCFv5.0", candidate)

    matrix = _matrix("VCFv5.0")

    assert matrix["breakend_replacement_and_mate_links"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"
    assert matrix["local_allele_encoding"]["status"] == "NOT_APPLICABLE_TO_DECLARED_VERSION"
