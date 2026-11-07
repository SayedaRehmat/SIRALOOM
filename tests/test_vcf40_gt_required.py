from pathlib import Path

import pytest

# Source context: the rendered IGSR VCFv4.0 page, lines 23-26, 43-58 and 108-120.

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


def test_vcf40_explicit_reserved_format_definitions_accept_versioned_types(tmp_path: Path):
    path = tmp_path / "vcf40-reserved-format-explicit.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\n'
        '##FORMAT=<ID=HQ,Number=2,Type=Integer,Description="Haplotype quality">\n'
        '##FORMAT=<ID=GL,Number=3,Type=Float,Description="Genotype likelihoods">\n'
        '##FORMAT=<ID=FT,Number=1,Type=String,Description="Genotype filter">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:GQ:DP:HQ:GL:FT\t0/1:20:20:21,22:-1,-2,-3:PASS\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1
