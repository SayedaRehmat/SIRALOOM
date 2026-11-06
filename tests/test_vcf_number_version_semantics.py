from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


@pytest.mark.parametrize("number", ["A", "G", "R"])
@pytest.mark.parametrize("kind", ["INFO", "FORMAT"])
def test_vcf40_rejects_post_v40_special_number_tokens(
    tmp_path: Path, kind: str, number: str
):
    path = tmp_path / f"vcf40-{kind.lower()}-{number}.vcf"
    if kind == "INFO":
        definition = f'##INFO=<ID=CUSTOM,Number={number},Type=Integer,Description="Custom">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
        record = "1\t2\t.\tA\tC\t.\tPASS\tCUSTOM=1"
    else:
        definition = f'##FORMAT=<ID=CUSTOM,Number={number},Type=Integer,Description="Custom">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1"
        record = "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:CUSTOM\t0/1:1"
    path.write_text(
        f"##fileformat=VCFv4.0\n{definition}\n{columns}\n{record}\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("kind", ["INFO", "FORMAT"])
def test_vcf41_rejects_number_r(
    tmp_path: Path, kind: str
):
    path = tmp_path / f"vcf41-number-r-{kind.lower()}.vcf"
    if kind == "INFO":
        definition = '##INFO=<ID=CUSTOM,Number=R,Type=Integer,Description="Per-allele">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
        record = "1\t2\t.\tA\tC\t.\tPASS\tCUSTOM=10,5"
    else:
        definition = '##FORMAT=<ID=CUSTOM,Number=R,Type=Integer,Description="Per-allele">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1"
        record = "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:CUSTOM\t0/1:10,5"
    path.write_text(
        f"##fileformat=VCFv4.1\n{definition}\n{columns}\n{record}\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize("kind", ["INFO", "FORMAT"])
def test_vcf42_accepts_number_r_for_reference_plus_alternates(
    tmp_path: Path, kind: str
):
    path = tmp_path / f"vcf42-number-r-{kind.lower()}.vcf"
    if kind == "INFO":
        definition = '##INFO=<ID=CUSTOM,Number=R,Type=Integer,Description="Per-allele">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
        record = "1\t2\t.\tA\tC\t.\tPASS\tCUSTOM=10,5"
    else:
        definition = '##FORMAT=<ID=CUSTOM,Number=R,Type=Integer,Description="Per-allele">'
        columns = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1"
        record = "1\t2\t.\tA\tC\t.\tPASS\t.\tGT:CUSTOM\t0/1:10,5"
    path.write_text(
        f"##fileformat=VCFv4.2\n{definition}\n{columns}\n{record}\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("number", "alt", "gt", "value"),
    [
        ("A", "C,G", "0/1", "10,20"),
        ("G", "C", "0/1", "10,20,30"),
    ],
)
def test_vcf41_accepts_number_a_and_g(
    tmp_path: Path, number: str, alt: str, gt: str, value: str
):
    path = tmp_path / f"vcf41-number-{number}.vcf"
    path.write_text(
        "##fileformat=VCFv4.1\\n"
        f'##FORMAT=<ID=CUSTOM,Number={number},Type=Integer,Description="Custom">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        f"1\\t2\\t.\\tA\\t{alt}\\t.\\tPASS\\t.\\tGT:CUSTOM\\t{gt}:{value}\\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("number", ["P", "M", "LA", "LR", "LG"])
def test_vcf44_rejects_vcf45_only_format_cardinalities(
    tmp_path: Path, number: str
):
    path = tmp_path / f"vcf44-number-{number}.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\\n"
        f'##FORMAT=<ID=CUSTOM,Number={number},Type=Float,Description="Custom">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        "1\\t2\\t.\\tA\\tC\\t.\\tPASS\\t.\\tGT:CUSTOM\\t0/1:0.5\\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"
