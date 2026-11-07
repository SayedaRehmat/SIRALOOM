from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def test_vcf40_reserved_format_fields_validate_implicit_definitions(tmp_path: Path):
    path = tmp_path / "vcf40-reserved-format-implicit.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:DP:FT:GL:GQ:HQ\t0/1:20:PASS:-1,-2,-3:20.5:20.5,21.5\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf40_gl_is_not_defined_for_multiallelic_records(tmp_path: Path):
    path = tmp_path / "vcf40-gl-multiallelic.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:GL\t1/2:-1,-2,-3\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


@pytest.mark.parametrize(
    "definition",
    [
        '##FORMAT=<ID=GL,Number=G,Type=Float,Description="Genotype likelihoods">',
        '##FORMAT=<ID=GL,Number=3,Type=Integer,Description="Genotype likelihoods">',
        '##FORMAT=<ID=DP,Number=2,Type=Integer,Description="Read depth">',
        '##FORMAT=<ID=FT,Number=1,Type=Integer,Description="Genotype filter">',
    ],
)
def test_vcf40_reserved_format_header_definitions_are_version_pinned(
    tmp_path: Path, definition: str
):
    path = tmp_path / "vcf40-reserved-format-header-invalid.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\n"
        f"{definition}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tA\tC\t.\tPASS\t.\tGT\t0/1\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"

def test_vcf40_reserved_format_header_definitions_use_v40_cardinality_and_types(tmp_path: Path):
    path = tmp_path / "vcf40-reserved-format-valid.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\\n'
        '##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Read depth">\\n'
        '##FORMAT=<ID=FT,Number=1,Type=String,Description="Genotype filter">\\n'
        '##FORMAT=<ID=GL,Number=3,Type=Float,Description="Genotype likelihoods">\\n'
        '##FORMAT=<ID=GQ,Number=1,Type=Float,Description="Genotype quality">\\n'
        '##FORMAT=<ID=HQ,Number=2,Type=Float,Description="Haplotype qualities">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        "1\\t2\\t.\\tA\\tC\\t.\\tPASS\\t.\\tGT:DP:FT:GL:GQ:HQ\\t0/1:20:PASS:-1,-2,-3:20.5:20.5,21.5\\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1
