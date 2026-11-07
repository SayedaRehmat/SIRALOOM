from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_local_vcf(path: Path, *, format_lines: str, format_keys: str, sample: str):
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f"{format_lines}"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\t{format_keys}\t{sample}\n",
        encoding="utf-8",
    )


def test_vcf45_local_format_field_requires_laa_key(tmp_path: Path):
    path = tmp_path / "local-field-without-laa.vcf"
    _write_local_vcf(
        path,
        format_lines='##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local depths">\n',
        format_keys="GT:LAD",
        sample="0/0:10",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


def test_vcf45_laa_must_precede_every_format_key_except_gt(tmp_path: Path):
    path = tmp_path / "laa-not-second.vcf"
    _write_local_vcf(
        path,
        format_lines=(
            '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">\n'
            '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local depths">\n'
        ),
        format_keys="GT:DP:LAA:LAD",
        sample="0/0:10:2:10",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


def test_vcf45_custom_local_cardinality_field_also_requires_laa(tmp_path: Path):
    path = tmp_path / "custom-local-field-without-laa.vcf"
    _write_local_vcf(
        path,
        format_lines='##FORMAT=<ID=CUSTOM_LG,Number=LG,Type=Integer,Description="Custom local genotype values">\n',
        format_keys="GT:CUSTOM_LG",
        sample="0/0:1,2,3",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_LOCAL_ALLELE_INVALID"


def test_vcf45_missing_laa_value_is_ref_only_when_local_field_is_populated(
    tmp_path: Path,
):
    path = tmp_path / "laa-empty-ref-only.vcf"
    _write_local_vcf(
        path,
        format_lines='##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local depths">\n',
        format_keys="GT:LAA:LAD",
        sample="0/0:.:10",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_local_field_and_missing_laa_values_can_both_be_missing(
    tmp_path: Path,
):
    path = tmp_path / "laa-and-local-field-missing.vcf"
    _write_local_vcf(
        path,
        format_lines='##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local depths">\n',
        format_keys="GT:LAA:LAD",
        sample="0/0:.:.",
    )
    assert validate_vcf_strict(path)["records"] == 1
