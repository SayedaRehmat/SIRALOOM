from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


@pytest.mark.parametrize("version", ["VCFv4.0", "VCFv4.1"])
def test_pre_vcf42_rejects_spanning_deletion_star_allele(
    tmp_path: Path, version: str
):
    path = tmp_path / f"star-alt-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\t*\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ALT_INVALID"


def test_vcf42_accepts_spanning_deletion_star_allele(tmp_path: Path):
    path = tmp_path / "star-alt-vcf42.vcf"
    path.write_text(
        "##fileformat=VCFv4.2\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\t*\t.\tPASS\t.\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("version", ["VCFv4.0", "VCFv4.1", "VCFv4.2"])
def test_pre_vcf43_rejects_unspecified_star_allele(
    tmp_path: Path, version: str
):
    path = tmp_path / f"unspecified-alt-{version}.vcf"
    path.write_text(
        f"##fileformat={version}\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\t<*>\t.\tPASS\tEND=2\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ALT_INVALID"


def test_vcf43_accepts_unspecified_star_allele_with_end(tmp_path: Path):
    path = tmp_path / "unspecified-alt-vcf43.vcf"
    path.write_text(
        "##fileformat=VCFv4.3\n"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t2\t.\tA\t<*>\t.\tPASS\tEND=2\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf40_rejects_breakend_replacement_notation(tmp_path: Path):
    path = tmp_path / "breakend-alt-vcf40.vcf"
    path.write_text(
        "##fileformat=VCFv4.0\\n"
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\n"
        "1\\t2\\tBND1\\tA\\tA[2:20[\\t.\\tPASS\\tSVTYPE=BND\\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_ALT_INVALID"
