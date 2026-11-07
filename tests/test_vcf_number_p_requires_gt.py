from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def test_vcf45_populated_number_p_requires_gt(tmp_path: Path):
    path = tmp_path / "number-p-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=CUSTOM_P,Number=P,Type=Integer,Description="Per-allele values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tCUSTOM_P\t10,20\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


def test_vcf45_missing_number_p_can_remain_unresolved_without_gt(tmp_path: Path):
    path = tmp_path / "number-p-missing-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=CUSTOM_P,Number=P,Type=Integer,Description="Per-allele values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tCUSTOM_P\t.\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1

def test_vcf45_populated_number_p_with_gt_uses_sample_ploidy(tmp_path: Path):
    path = tmp_path / "number-p-with-diploid-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=CUSTOM_P,Number=P,Type=Integer,Description="Per-allele values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:CUSTOM_P\t0/1:10,20\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1
