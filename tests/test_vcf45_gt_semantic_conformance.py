from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_gt_vcf(
    path: Path,
    *,
    genotype: str,
    format_id: str,
    number: str,
    field_type: str,
    values: str,
):
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f'##FORMAT=<ID={format_id},Number={number},Type={field_type},Description="GT-indexed values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:{format_id}\t{genotype}:{values}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("genotype", "values", "expected_count"),
    [
        ("1", "0,1,2", 3),
        ("0/1", "0,1,2,3,4,5", 6),
        ("/0/1", "0,1,2,3,4,5", 6),
        ("0/1/2", "0,1,2,3,4,5,6,7,8,9", 10),
        ("0/1/2/2", "0,1,2,3,4,5,6,7,8,9,10,11,12,13,14", 15),
        ("./.", "0,1,2,3,4,5", 6),
        ("././.", "0,1,2,3,4,5,6,7,8,9", 10),
    ],
)
def test_vcf45_number_g_uses_gt_ploidy_including_missing_alleles(
    tmp_path: Path, genotype: str, values: str, expected_count: int
):
    path = tmp_path / "vcf45-number-g-ploidy.vcf"
    _write_gt_vcf(
        path,
        genotype=genotype,
        format_id="PL",
        number="G",
        field_type="Integer",
        values=values,
    )
    assert validate_vcf_strict(path)["records"] == 1
    assert len(values.split(",")) == expected_count


@pytest.mark.parametrize(
    ("genotype", "values", "expected_count"),
    [
        ("1", "10", 1),
        ("0/1", "10,20", 2),
        ("0/1/2", "10,20,30", 3),
        ("././.", ".,.,.", 3),
    ],
)
def test_vcf45_number_p_has_one_value_per_gt_allele_value(
    tmp_path: Path, genotype: str, values: str, expected_count: int
):
    path = tmp_path / "vcf45-number-p-ploidy.vcf"
    _write_gt_vcf(
        path,
        genotype=genotype,
        format_id="CUSTOM_P",
        number="P",
        field_type="String",
        values=values,
    )
    assert validate_vcf_strict(path)["records"] == 1
    assert len(values.split(",")) == expected_count


@pytest.mark.parametrize(
    ("genotype", "expected_values"),
    [
        ("|0/0", "0.2,0.3"),
        ("/0/0", "0.2"),
        ("0|0/0", "0.2,0.3"),
    ],
)
def test_vcf45_first_and_mixed_phasing_separators_control_allele_aggregation(
    tmp_path: Path, genotype: str, expected_values: str
):
    path = tmp_path / "vcf45-leading-and-mixed-phasing.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tC\t.\t.\tPASS\t.\tGT:M5mC\t{genotype}:{expected_values}\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize("genotype", ["0/", "0||1", "|/0", "0/1/", "//0"])
def test_vcf45_malformed_gt_separator_structures_are_rejected(
    tmp_path: Path, genotype: str
):
    path = tmp_path / "vcf45-malformed-gt.vcf"
    _write_gt_vcf(
        path,
        genotype=genotype,
        format_id="PL",
        number="G",
        field_type="Integer",
        values="0,1,2,3,4,5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_GENOTYPE_INVALID"
