from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_number_m_vcf(
    path: Path,
    *,
    reference: str,
    alternate: str,
    genotype: str,
    field_id: str,
    values: str,
    field_type: str = "Float",
) -> None:
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f'##FORMAT=<ID={field_id},Number=M,Type={field_type},Description="Base modification value">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\t{reference}\t{alternate}\t.\tPASS\t.\tGT:{field_id}\t{genotype}:{values}\n",
        encoding="utf-8",
    )


def test_number_m_counts_complementary_strand_sites_in_allele_sequence(tmp_path: Path):
    # For M5mC, C on the forward strand and G representing C on the reverse
    # strand are both modifiable positions in the allele sequence CGA.
    path = tmp_path / "number-m-complementary-strands.vcf"
    _write_number_m_vcf(
        path,
        reference="CGA",
        alternate=".",
        genotype="0/0",
        field_id="M5mC",
        values="0.25,0.75",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_number_m_N_has_positive_and_negative_strand_value_per_base(tmp_path: Path):
    # Number=M for N contains two values per base: positive then negative strand.
    path = tmp_path / "number-m-unknown-base-both-strands.vcf"
    _write_number_m_vcf(
        path,
        reference="AC",
        alternate=".",
        genotype="0",
        field_id="M18107N",
        values="0.1,0.2,0.3,0.4",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("genotype", "values", "expected_valid"),
    [
        ("0/0", "0.4", True),       # repeated unphased allele is aggregated once
        ("0|0", "0.4,0.6", True),   # phased copies remain separate
        ("0/0", "0.4,0.6", False),  # aggregation must not be skipped
        ("0|0", "0.4", False),      # phased copies must not be collapsed
    ],
)
def test_number_m_repeated_allele_aggregation_depends_on_phasing(
    tmp_path: Path, genotype: str, values: str, expected_valid: bool
):
    path = tmp_path / "number-m-repeated-alleles.vcf"
    _write_number_m_vcf(
        path,
        reference="C",
        alternate=".",
        genotype=genotype,
        field_id="M5mC",
        values=values,
    )
    if expected_valid:
        assert validate_vcf_strict(path)["records"] == 1
    else:
        with pytest.raises(StrictVCFValidationError) as exc:
            validate_vcf_strict(path)
        assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


def test_number_m_repeated_unphased_alternate_alleles_are_aggregated(tmp_path: Path):
    path = tmp_path / "number-m-repeated-unphased-alt.vcf"
    _write_number_m_vcf(
        path,
        reference="A",
        alternate="CG",
        genotype="1/1",
        field_id="M5mC",
        values="0.3,0.4",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_number_m_missing_gt_allele_contributes_no_values(tmp_path: Path):
    path = tmp_path / "number-m-missing-gt-allele.vcf"
    _write_number_m_vcf(
        path,
        reference="A",
        alternate="CG",
        genotype="./1",
        field_id="M5mC",
        values="0.8,0.9",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("genotype", "values"),
    [
        ("0/1", "0.5"),  # only the concrete REF allele contributes
        ("1/1", "."),    # symbolic-only genotype contributes zero values
    ],
)
def test_number_m_symbolic_alleles_contribute_no_modifiable_bases(
    tmp_path: Path, genotype: str, values: str
):
    path = tmp_path / "number-m-symbolic-alleles.vcf"
    _write_number_m_vcf(
        path,
        reference="C",
        alternate="<*>",
        genotype=genotype,
        field_id="M5mC",
        values=values,
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_number_m_U_is_synonymous_with_T(tmp_path: Path):
    path = tmp_path / "number-m-uracil-synonymous-with-thymine.vcf"
    _write_number_m_vcf(
        path,
        reference="TCC",
        alternate=".",
        genotype="0",
        field_id="M16964U",
        values="0.7",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_number_m_all_missing_gt_alleles_require_no_values(tmp_path: Path):
    path = tmp_path / "number-m-all-missing-gt.vcf"
    _write_number_m_vcf(
        path,
        reference="CGA",
        alternate=".",
        genotype="./.",
        field_id="M5mC",
        values=".",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("field_id", "field_type", "values"),
    [
        ("M5mC", "Float", "1.1,0.2"),
        ("M5mC", "Float", "-0.1,0.2"),
        ("DPM5mC", "Integer", "-1,2"),
        ("ADM5mC", "Integer", "1,-2"),
    ],
)
def test_number_m_fraction_and_depth_values_enforce_specified_ranges(
    tmp_path: Path, field_id: str, field_type: str, values: str
):
    path = tmp_path / f"number-m-invalid-values-{field_id}.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f'##FORMAT=<ID={field_id},Number=M,Type={field_type},Description="Base modification value">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tCGA\t.\t.\tPASS\t.\tGT:{field_id}\t0/0:{values}\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_TYPE_INVALID"


def test_number_m_requires_gt_format_key(tmp_path: Path):
    path = tmp_path / "number-m-without-gt-key.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="Base modification fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t2\t.\tC\t.\t.\tPASS\t.\tM5mC\t0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BASE_MODIFICATION_GT_MISSING"

def test_production_validator_maps_each_number_m_value_to_its_biological_slot(
    tmp_path: Path,
):
    path = tmp_path / "number-m-biological-slot-mapping.vcf"
    _write_number_m_vcf(
        path,
        reference="CGA",
        alternate=".",
        genotype="0/0",
        field_id="M5mC",
        values="0.25,0.75",
    )
    result = validate_vcf_strict(
        path, include_base_modification_slot_assignments=True
    )
    assert result["base_modification_slot_assignment_count"] == 2
    assert result["base_modification_slot_assignments"] == [
        {
            "record_index": 1,
            "line_number": 5,
            "chrom": "1",
            "pos": 2,
            "sample_index": 1,
            "sample_name": "SAMPLE1",
            "field_id": "M5mC",
            "value_index": 0,
            "allele_index": 0,
            "allele_sequence_position": 0,
            "sequence_base": "C",
            "strand": "+",
            "value": "0.25",
        },
        {
            "record_index": 1,
            "line_number": 4,
            "chrom": "1",
            "pos": 2,
            "sample_index": 1,
            "sample_name": "SAMPLE1",
            "field_id": "M5mC",
            "value_index": 1,
            "allele_index": 0,
            "allele_sequence_position": 1,
            "sequence_base": "G",
            "strand": "-",
            "value": "0.75",
        },
    ]


def test_production_validator_maps_number_m_slots_in_gt_allele_order(
    tmp_path: Path,
):
    path = tmp_path / "number-m-gt-order-mapping.vcf"
    _write_number_m_vcf(
        path,
        reference="C",
        alternate="G",
        genotype="1|0",
        field_id="M5mC",
        values="0.2,0.8",
    )
    result = validate_vcf_strict(
        path, include_base_modification_slot_assignments=True
    )
    slots = result["base_modification_slot_assignments"]
    assert [(slot["allele_index"], slot["sequence_base"], slot["strand"], slot["value"])
            for slot in slots] == [
        (1, "G", "-", "0.2"),
        (0, "C", "+", "0.8"),
    ]


def test_production_validator_maps_missing_vector_entries_to_slots(
    tmp_path: Path,
):
    path = tmp_path / "number-m-slot-missing-entry.vcf"
    _write_number_m_vcf(
        path,
        reference="CGA",
        alternate=".",
        genotype="0",
        field_id="M5mC",
        values=".,0.75",
    )
    result = validate_vcf_strict(
        path, include_base_modification_slot_assignments=True
    )
    assert [slot["value"] for slot in result["base_modification_slot_assignments"]] == [
        None,
        "0.75",
    ]

