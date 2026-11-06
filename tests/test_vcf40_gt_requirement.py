from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def test_vcf40_requires_gt_when_sample_genotype_columns_are_present(tmp_path: Path):
    path = tmp_path / "vcf40-format-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tDP\t10\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FORMAT_INVALID"
