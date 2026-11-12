from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import settings
from backend.app.domain import ingestion
from backend.app.domain.artifact_validation import _validation_payload
from backend.app.domain.vcf import parse_vcf
from backend.app.domain.vcf_validation import StrictVCFValidationError, validate_vcf_strict

FIXTURES = Path(__file__).parent / "fixtures" / "vcf" / "callers"


@pytest.mark.parametrize(
    ("filename", "profile_id", "version", "semantic_status"),
    [
        ("gatk_haplotypecaller_v4_2_6_1_doc_example.vcf", "gatk_haplotypecaller", "4.2.6.1", "DOCUMENTED_HEADER_CONVENTIONS_MATCH_RELEASE_NOT_QUALIFIED"),
        ("deepvariant_1_10_0_golden.vcf", "deepvariant_germline", "1.10.0", "DOCUMENTED_HEADER_CONVENTIONS_MATCH_RELEASE_NOT_QUALIFIED"),
        ("dragen_snv_v4_3_doc_example.vcf", "dragen_snv_germline", "4.3.0", "CALLER_SPEC_SEMANTIC_DEVIATION"),
    ],
)
def test_documented_caller_outputs_are_structurally_valid_and_profiled(
    filename: str, profile_id: str, version: str, semantic_status: str
) -> None:
    result = validate_vcf_strict(FIXTURES / filename)
    provenance = result["caller_provenance"]

    assert result["records"] > 0
    assert provenance["identity_status"] == "DECLARED"
    assert provenance["caller_profile_id"] == profile_id
    assert provenance["caller_version"] == version
    assert provenance["version_status"] == "DECLARED"
    assert provenance["profile_match_status"] == "METADATA_MATCH_ONLY"
    assert provenance["caller_profile_version"] == "1.0.0"
    assert provenance["field_declaration_mismatches"] == []
    assert provenance["caller_semantic_compatibility_status"] == semantic_status
    if profile_id == "dragen_snv_germline":
        assert provenance["field_semantic_deviations"] == [{
            "namespace": "FORMAT",
            "field_id": "GP",
            "status": "CALLER_SPECIFIC_SCALE_DIFFERS_FROM_VCF_RESERVED_SEMANTICS",
            "description": "DRAGEN documents FORMAT/GP in Phred scale; VCF reserves FORMAT/GP for posterior probabilities in [0, 1].",
        }]
        assert provenance["caller_semantic_compatibility_review_required"] is True
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
    assert "Unfiltered allele depth" in provenance["documented_format_semantics_for_present_fields"]["AD"]
    assert "sample-level" in provenance["documented_format_semantics_for_present_fields"]["DP"]
    assert "site-level" in provenance["documented_info_semantics_for_present_fields"]["DP"]


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
    assert provenance["caller_semantic_compatibility_status"] == "NOT_ASSESSED"


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
    assert provenance["caller_semantic_compatibility_status"] == "CONFLICTED_CALLER_METADATA"


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


def test_caller_provenance_is_included_in_persisted_validation_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = FIXTURES / "gatk_haplotypecaller_v4_2_6_1_doc_example.vcf"
    monkeypatch.setattr(
        ingestion,
        "_bcftools_validate",
        lambda _path: (None, settings.bcftools_version, settings.htslib_version),
    )

    result = ingestion.validate_vcf(fixture)
    payload = _validation_payload(result)

    assert result.status == "VALID"
    assert payload["caller_provenance"]["caller_profile_id"] == "gatk_haplotypecaller"
    assert payload["caller_provenance"]["caller_version"] == "4.2.6.1"


def test_deepvariant_vaf_and_likelihood_fields_are_preserved_verbatim() -> None:
    record = next(
        parse_vcf(
            str(FIXTURES / "deepvariant_1_10_0_golden.vcf"),
            allow_unselected_multisample=True,
        )
    )
    values = record.sample_calls["NA12878"]["format_values"]

    assert values["AD"] == "25,30"
    assert values["VAF"] == "0.545455"
    assert values["PL"] == "37,0,42"


def test_dragen_caller_specific_evidence_fields_are_preserved_verbatim() -> None:
    record = next(
        parse_vcf(
            str(FIXTURES / "dragen_snv_v4_3_doc_example.vcf"),
            allow_unselected_multisample=True,
        )
    )
    values = record.sample_calls["SAMPLE1"]["format_values"]

    assert values["AD"] == "0,5,4"
    assert values["AF"] == "0.556,0.444"
    assert values["DP"] == "9"
    assert values["PL"] == "177,144,46,122,0,72"
    assert values["GL"] == "-17.704,-14.420,-4.626,-12.220,0.000,-7.244"
    assert values["GP"] == "107.6,109.6,14.65,87.58,0.152,40.82"


def test_known_caller_field_declaration_mismatch_is_flagged_without_rejecting_valid_vcf(
    tmp_path: Path,
) -> None:
    path = tmp_path / "deepvariant-vaf-number-r-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##DeepVariant_version=1.10.0\n"
        '##FILTER=<ID=PASS,Description="All filters passed">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">\n'
        '##FORMAT=<ID=VAF,Number=R,Type=Float,Description="Allele fractions">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tGT:GQ:DP:AD:VAF:PL\t0/1:30:20:10,10:0.5,0.5:50,0,50\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    provenance = result["caller_provenance"]

    assert result["records"] == 1
    assert provenance["identity_status"] == "DECLARED"
    assert provenance["caller_semantic_compatibility_status"] == "DECLARATION_MISMATCH"
    assert provenance["field_declaration_mismatches"] == [
        {
            "namespace": "FORMAT",
            "field_id": "VAF",
            "observed_number": "R",
            "observed_type": "Float",
            "expected_number": "A",
            "expected_type": "Float",
            "status": "MISMATCH",
        }
    ]


def test_known_caller_sample_record_without_gt_is_flagged_without_rejecting_vcf(
    tmp_path: Path,
) -> None:
    path = tmp_path / "deepvariant-record-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##DeepVariant_version=1.10.0\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tDP\t20\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    provenance = result["caller_provenance"]

    assert result["records"] == 1
    assert provenance["identity_status"] == "DECLARED"
    assert provenance["sample_count"] == 1
    assert provenance["sample_record_count"] == 1
    assert provenance["sample_records_without_gt"] == 1
    assert provenance["caller_semantic_compatibility_status"] == "MISSING_REQUIRED_FORMAT_FIELD"
    assert provenance["caller_semantic_compatibility_review_required"] is True
    assert {
        "field_id": "GT",
        "reason": "MISSING_FROM_SAMPLE_RECORD_FORMAT",
        "record_count": 1,
    } in provenance["required_format_field_violations"]


def test_generic_vcf_gp_retains_vcf_probability_range_validation(tmp_path: Path) -> None:
    path = tmp_path / "generic-gp-out-of-range.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior probabilities">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tGT:GP\t0/1:10,0,10\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError, match="FORMAT sample 1/GP") as exc_info:
        validate_vcf_strict(path)
    assert exc_info.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize(
    ("version_headers", "expected_override"),
    [
        ("##DRAGENVersion=4.3.0\n", True),
        ("##DRAGENVersion=4.3.1\n", False),
        ("", False),
        ("##DRAGENVersion=4.3.0\n##DRAGENVersion=4.4.0\n", False),
    ],
)
def test_dragen_gp_phred_scale_override_requires_exact_unambiguous_release(
    tmp_path: Path, version_headers: str, expected_override: bool
) -> None:
    path = tmp_path / "dragen-gp-release-gate.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##source=DRAGEN_SNV\n"
        + version_headers
        + '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        + '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior values">\n'
        + "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        + "1\t10\t.\tA\tC\t50\tPASS\t.\tGT:GP\t0/1:107.6,0.152,40.82\n",
        encoding="utf-8",
    )

    if expected_override:
        provenance = validate_vcf_strict(path)["caller_provenance"]
        assert provenance["dragen_gp_phred_semantics_applicable"] is True
        assert provenance["caller_semantic_compatibility_status"] == "CALLER_SPEC_SEMANTIC_DEVIATION"
    else:
        with pytest.raises(StrictVCFValidationError) as exc_info:
            validate_vcf_strict(path)
        assert exc_info.value.code == "VCF_FIELD_TYPE_INVALID"


def test_deepvariant_model_metadata_alone_identifies_partial_caller_provenance(
    tmp_path: Path,
) -> None:
    path = tmp_path / "deepvariant-model-without-release.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "##DeepVariant_model_type=WGS\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\n",
        encoding="utf-8",
    )

    provenance = validate_vcf_strict(path)["caller_provenance"]

    assert provenance["caller_profile_id"] == "deepvariant_germline"
    assert provenance["identity_status"] == "PARTIAL"
    assert provenance["caller_version"] is None
    assert provenance["deepvariant_model_type"] == "WGS"
    assert provenance["deepvariant_model_type_status"] == "DECLARED"


def test_conflicting_dragen_pipeline_source_markers_do_not_enable_gp_override(
    tmp_path: Path,
) -> None:
    path = tmp_path / "conflicting-dragen-source-markers.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##source=DRAGEN_SNV\n"
        "##source=DRAGEN_CNV\n"
        "##DRAGENVersion=4.3.0\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t50\tPASS\t.\tGT:GP\t0/1:107.6,0.152,40.82\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc_info:
        validate_vcf_strict(path)

    assert exc_info.value.code == "VCF_FIELD_TYPE_INVALID"


@pytest.mark.parametrize("gp_values", ["-1,0,2", "NaN,0,2"])
def test_dragen_phred_scaled_gp_values_must_remain_nonnegative(
    tmp_path: Path, gp_values: str
) -> None:
    path = tmp_path / "dragen-gp-negative-or-nan.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "##source=DRAGEN_SNV\n"
        "##DRAGENVersion=4.3.0\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GP,Number=G,Type=Float,Description="Genotype posterior values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\t.\tA\tC\t50\tPASS\t.\tGT:GP\t0/1:{gp_values}\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc_info:
        validate_vcf_strict(path)

    assert exc_info.value.code == "VCF_FIELD_TYPE_INVALID"
