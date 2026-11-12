from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.domain import ingestion
from backend.app.domain.vcf_validation import validate_vcf_strict

FIXTURES = Path(__file__).parent / "fixtures" / "vcf" / "callers"


@pytest.mark.parametrize(
    ("filename", "profile_id", "version"),
    [
        ("gatk_haplotypecaller_v4_2_6_1_doc_example.vcf", "gatk_haplotypecaller", "4.2.6.1"),
        ("deepvariant_1_10_0_golden.vcf", "deepvariant_germline", "1.10.0"),
        ("dragen_snv_v4_3_doc_example.vcf", "dragen_snv_germline", "4.3.0"),
    ],
)
def test_documented_caller_outputs_are_structurally_valid_and_profiled(
    filename: str, profile_id: str, version: str
) -> None:
    result = validate_vcf_strict(FIXTURES / filename)
    provenance = result["caller_provenance"]

    assert result["records"] > 0
    assert provenance["identity_status"] == "DECLARED"
    assert provenance["caller_profile_id"] == profile_id
    assert provenance["caller_version"] == version
    assert provenance["version_status"] == "DECLARED"
    assert provenance["profile_match_status"] == "METADATA_MATCH_ONLY"
    assert provenance["identity_source"] == "VCF_HEADER_DECLARATION_UNVERIFIED"
    assert provenance["release_qualification_status"] == "NOT_ESTABLISHED"
    assert provenance["clinical_qualification_status"] == "NOT_ESTABLISHED"
    assert provenance["assay_mode_status"] == "NOT_ATTESTED_BY_VCF_HEADER"


def test_gatk_haplotypecaller_stage_and_command_line_are_recorded_without_raw_paths() -> None:
    provenance = validate_vcf_strict(
        FIXTURES / "gatk_haplotypecaller_v4_2_6_1_doc_example.vcf"
    )["caller_provenance"]

    assert provenance["producer_stages"] == ["HaplotypeCaller"]
    assert provenance["command_line_header_present"] is True
    assert len(provenance["command_line_header_sha256"]) == 64
    assert "HaplotypeCaller --output fixture.vcf" not in str(provenance)
    assert provenance["documented_format_semantics_for_present_fields"]["AD"]
    assert "unfiltered allele evidence" in provenance["documented_format_semantics_for_present_fields"]["AD"]


def test_deepvariant_profile_captures_its_documented_fields_and_filters() -> None:
    provenance = validate_vcf_strict(
        FIXTURES / "deepvariant_1_10_0_golden.vcf"
    )["caller_provenance"]

    assert {"GT", "GQ", "DP", "AD", "VAF", "PL"} <= set(provenance["declared_format_fields"])
    assert {"RefCall", "LowQual", "NoCall"} <= set(provenance["declared_filter_ids"])
    assert "Variant allele fraction" in provenance["documented_format_semantics_for_present_fields"]["VAF"]


def test_dragen_profile_distinguishes_site_depth_from_informative_sample_depth() -> None:
    provenance = validate_vcf_strict(
        FIXTURES / "dragen_snv_v4_3_doc_example.vcf"
    )["caller_provenance"]

    assert provenance["declared_source_values"] == ["DRAGEN_SNV"]
    assert "DP" in provenance["documented_info_semantics_for_present_fields"]
    assert "DP" in provenance["documented_format_semantics_for_present_fields"]
    assert "Unfiltered site depth" in provenance["documented_info_semantics_for_present_fields"]["DP"]
    assert "Informative sample depth" in provenance["documented_format_semantics_for_present_fields"]["DP"]
    assert "not numerically interchangeable" in provenance["cross_caller_comparison_policy"] or "Never apply GATK" in provenance["cross_caller_comparison_policy"]


def test_common_format_fields_do_not_identify_an_unknown_caller(tmp_path: Path) -> None:
    path = tmp_path / "unknown-caller.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tGT:AD:DP:GQ:PL\t0/1:10,8:18:40:50,0,50\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["identity_status"] == "UNKNOWN"
    assert provenance["caller_profile_id"] is None
    assert provenance["profile_match_status"] == "NO_CALLER_PROFILE_MATCH"
    assert provenance["clinical_qualification_status"] == "NOT_ESTABLISHED"


def test_conflicting_caller_family_markers_are_not_resolved_by_precedence(tmp_path: Path) -> None:
    path = tmp_path / "conflicting-caller-markers.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##DeepVariant_version=1.10.0\n"
        "##source=DRAGEN_SNV\n"
        "##DRAGENVersion=4.3.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["identity_status"] == "CONFLICTED"
    assert provenance["caller_profile_id"] is None
    assert provenance["profile_match_status"] == "CONFLICTED_METADATA"


def test_conflicting_release_markers_make_caller_identity_unresolved(tmp_path: Path) -> None:
    path = tmp_path / "conflicting-deepvariant-releases.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##DeepVariant_version=1.9.0\n"
        "##DeepVariant_version=1.10.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["caller_profile_id"] == "deepvariant_germline"
    assert provenance["caller_version"] is None
    assert provenance["version_status"] == "CONFLICTED"
    assert provenance["identity_status"] == "CONFLICTED"
    assert provenance["profile_match_status"] == "CONFLICTED_METADATA"


def test_gatk_genotype_gvcfs_stage_alone_does_not_claim_haplotypecaller(tmp_path: Path) -> None:
    path = tmp_path / "gatk-genotype-gvcfs-only.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        '##GATKCommandLine=<ID=GenotypeGVCFs,CommandLine="GenotypeGVCFs",Version="4.2.6.1">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["identity_status"] == "PARTIAL"
    assert provenance["caller_family"] == "GATK"
    assert provenance["caller_profile_id"] is None
    assert provenance["producer_stages"] == ["GenotypeGVCFs"]


def test_gvcf_reference_confidence_markers_are_routed_not_mislabelled_as_variant_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "gatk-gvcf.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##source=HaplotypeCaller\n"
        '##GATKCommandLine=<ID=HaplotypeCaller,Version="4.2.6.1">\n'
        '##ALT=<ID=NON_REF,Description="Represents any possible alternative allele at this location">\n'
        '##INFO=<ID=END,Number=1,Type=Integer,Description="End position of the block">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allelic depths">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=MIN_DP,Number=1,Type=Integer,Description="Minimum depth in the block">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\t<NON_REF>\t.\tPASS\tEND=20\tGT:AD:DP:GQ:MIN_DP:PL\t0/0:10,0:10:99:10:0,99,999\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["gvcf_reference_confidence_markers_present"] is True
    assert provenance["gvcf_handling_status"] == "ROUTE_TO_GVCF_WORKFLOW"


def test_caller_provenance_is_persisted_in_ingestion_validation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = FIXTURES / "gatk_haplotypecaller_v4_2_6_1_doc_example.vcf"
    monkeypatch.setattr(
        ingestion,
        "_bcftools_validate",
        lambda _path: (None, settings.bcftools_version, settings.htslib_version),
    )

    result = ingestion.validate_vcf(fixture)

    assert result.status == "VALID"
    assert result.metadata is not None
    assert result.metadata["caller_provenance"]["caller_profile_id"] == "gatk_haplotypecaller"
    assert result.metadata["caller_provenance"]["caller_version"] == "4.2.6.1"
