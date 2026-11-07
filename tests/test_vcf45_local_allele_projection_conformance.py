from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_local_likelihood_vcf(
    path: Path,
    *,
    gt: str,
    laa: str,
    standard_values: str,
    local_values: str,
    standard_key: str = "PL",
    local_key: str = "LPL",
    field_type: str = "Integer",
) -> None:
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\n'
        f'##FORMAT=<ID={standard_key},Number=G,Type={field_type},Description="Standard genotype values">\n'
        f'##FORMAT=<ID={local_key},Number=LG,Type={field_type},Description="Local genotype values">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC,G\t.\tPASS\t.\tGT:LAA:{standard_key}:{local_key}\t{gt}:{laa}:{standard_values}:{local_values}\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("gt", "standard_values", "local_values"),
    [
        # GT is all-REF so this tests ploidy/order without resolving GT/LAA index semantics.
        # Haploid local order 0,2 maps to global Number=G indexes 0,2.
        ("0", "0,1,2", "0,2"),
        # Diploid local order 00,02,22 maps to global indexes 0,3,5.
        ("0/0", "0,1,2,3,4,5", "0,3,5"),
        # Triploid local order 000,002,022,222 maps to global indexes 0,4,7,9.
        ("0/0/0", "0,1,2,3,4,5,6,7,8,9", "0,4,7,9"),
    ],
)
def test_local_pl_projection_uses_vcf_genotype_order_for_haploid_diploid_and_triploid(
    tmp_path: Path, gt: str, standard_values: str, local_values: str
):
    path = tmp_path / "local-pl-projection.vcf"
    _write_local_likelihood_vcf(
        path,
        gt=gt,
        laa="2",
        standard_values=standard_values,
        local_values=local_values,
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_local_pl_projection_preserves_laa_order_instead_of_sorting_alt_indices(tmp_path: Path):
    path = tmp_path / "local-pl-reversed-laa-order.vcf"
    _write_local_likelihood_vcf(
        path,
        gt="0/0",
        laa="2,1",
        standard_values="0,1,2,3,4,5",
        # Local order maps to global indexes 0,3,5,1,4,2.
        local_values="0,3,5,1,4,2",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_local_pl_projection_preserves_missing_value_positions(tmp_path: Path):
    valid = tmp_path / "local-pl-missing-position-valid.vcf"
    _write_local_likelihood_vcf(
        valid,
        gt="0/0",
        laa="2",
        standard_values="0,1,2,.,4,5",
        local_values="0,.,5",
    )
    assert validate_vcf_strict(valid)["records"] == 1

    invalid = tmp_path / "local-pl-missing-position-mismatch.vcf"
    _write_local_likelihood_vcf(
        invalid,
        gt="0/0",
        laa="2",
        standard_values="0,1,2,.,4,5",
        local_values="0,3,5",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(invalid)
    assert exc.value.code == "VCF_LOCAL_FIELD_EQUIVALENCE_INVALID"


@pytest.mark.parametrize(
    ("standard_values", "local_values"),
    [
        (".", "0,3,5"),
        ("0,1,2,3,4,5", "."),
    ],
)
def test_missing_whole_standard_or_local_likelihood_field_is_permitted(
    tmp_path: Path, standard_values: str, local_values: str
):
    path = tmp_path / "local-pl-whole-field-missing.vcf"
    _write_local_likelihood_vcf(
        path,
        gt="0/0",
        laa="2",
        standard_values=standard_values,
        local_values=local_values,
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_local_gl_projection_uses_vcf_genotype_order_and_float_values(tmp_path: Path):
    path = tmp_path / "local-gl-projection.vcf"
    _write_local_likelihood_vcf(
        path,
        gt="0/0",
        laa="2",
        standard_key="GL",
        local_key="LGL",
        field_type="Float",
        standard_values="-0.1,-0.2,-0.3,-0.4,-0.5,-0.6",
        local_values="-0.1,-0.4,-0.6",
    )
    assert validate_vcf_strict(path)["records"] == 1



@pytest.mark.parametrize(
    ("standard_key", "local_key", "number", "field_type", "standard_values", "local_values"),
    [
        ("AD", "LAD", "R", "Integer", "10,20,30", "10,30,20"),
        ("ADF", "LADF", "R", "Integer", "1,2,3", "1,3,2"),
        ("ADR", "LADR", "R", "Integer", "4,5,6", "4,6,5"),
        ("EC", "LEC", "A", "Integer", "20,30", "30,20"),
        ("GP", "LGP", "G", "Float", "0.01,0.02,0.03,0.04,0.05,0.06", "0.01,0.04,0.06,0.02,0.05,0.03"),
        ("PP", "LPP", "G", "Integer", "1,2,3,4,5,6", "1,4,6,2,5,3"),
    ],
)
def test_all_reserved_local_allele_pairs_project_in_laa_order(
    tmp_path: Path,
    standard_key: str,
    local_key: str,
    number: str,
    field_type: str,
    standard_values: str,
    local_values: str,
):
    local_number = {"A": "LA", "R": "LR", "G": "LG"}[number]
    path = tmp_path / f"{standard_key.lower()}-local-projection.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\\n'
        f'##FORMAT=<ID={standard_key},Number={number},Type={field_type},Description="Standard values">\\n'
        f'##FORMAT=<ID={local_key},Number={local_number},Type={field_type},Description="Local values">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        f"1\\t2\\t.\\tA\\tC,G\\t.\\tPASS\\t.\\tGT:LAA:{standard_key}:{local_key}\\t0/0:2,1:{standard_values}:{local_values}\\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("standard_key", "local_key", "number", "field_type", "standard_values", "local_values"),
    [
        ("AD", "LAD", "R", "Integer", "10,20,30", "10,20"),
        ("EC", "LEC", "A", "Integer", "20,30", "20"),
        ("PL", "LPL", "G", "Integer", "0,1,2,3,4,5", "0,3"),
        ("GL", "LGL", "G", "Float", "-0.1,-0.2,-0.3,-0.4,-0.5,-0.6", "-0.1,-0.4"),
    ],
)
def test_local_allele_projection_rejects_cardinality_mismatch(
    tmp_path: Path,
    standard_key: str,
    local_key: str,
    number: str,
    field_type: str,
    standard_values: str,
    local_values: str,
):
    local_number = {"A": "LA", "R": "LR", "G": "LG"}[number]
    path = tmp_path / f"{standard_key.lower()}-local-projection-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indices">\\n'
        f'##FORMAT=<ID={standard_key},Number={number},Type={field_type},Description="Standard values">\\n'
        f'##FORMAT=<ID={local_key},Number={local_number},Type={field_type},Description="Local values">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        f"1\\t2\\t.\\tA\\tC,G\\t.\\tPASS\\t.\\tGT:LAA:{standard_key}:{local_key}\\t0/0:2:{standard_values}:{local_values}\\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"
