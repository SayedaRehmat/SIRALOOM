from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def test_vcf40_sample_genotypes_require_gt_field(tmp_path: Path):
    path = tmp_path / "vcf40-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tDP\t20\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FORMAT_INVALID"


def test_vcf40_missing_gt_alleles_are_explicitly_represented(tmp_path: Path):
    path = tmp_path / "vcf40-missing-gt-alleles.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:DP\t./.:20\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1
