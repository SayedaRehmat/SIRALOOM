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
            "line_number": 5,
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

@pytest.mark.parametrize(
    ("field_id", "field_type", "values"),
    [
        ("MXaoN", "Float", "0.1,0.2"),
        ("MxaoN", "Float", "0.1,0.2"),
        ("DPMXaoN", "Integer", "10,20"),
        ("DPMxaoN", "Integer", "10,20"),
        ("ADMXaoN", "Integer", "4,8"),
        ("ADMxaoN", "Integer", "4,8"),
    ],
)
def test_xanthosine_alias_capitalization_variants_remain_accepted_without_normalization(
    tmp_path: Path, field_id: str, field_type: str, values: str
):
    path = tmp_path / f"xanthosine-alias-{field_id}.vcf"
    _write_number_m_vcf(
        path,
        reference="A",
        alternate=".",
        genotype="0",
        field_id=field_id,
        values=values,
        field_type=field_type,
    )
    result = validate_vcf_strict(path, include_base_modification_slot_assignments=True)
    assert result["records"] == 1
    assert result["base_modification_slot_assignment_count"] == 2
    assert [
        (slot["field_id"], slot["value"], slot["strand"])
        for slot in result["base_modification_slot_assignments"]
    ] == [
        (field_id, values.split(",")[0], "+"),
        (field_id, values.split(",")[1], "-"),
    ]

def _write_unstranded_cpg_vcf(path: Path, *, second_value: str, reverse: bool = False) -> None:
    first_ref, second_ref = ("G", "C") if reverse else ("C", "G")
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\t.\t{first_ref}\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:set,.:0.5\n"
        f"1\t11\t.\t{second_ref}\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:set,.:{second_value}\n",
        encoding="utf-8",
    )


def test_number_m_unstranded_policy_rejects_populated_higher_position_cpg_slot(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-invalid.vcf"
    _write_unstranded_cpg_vcf(path, second_value="0.2")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path, base_modification_strandedness="unstranded")
    assert exc.value.code == "VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT"


def test_number_m_unstranded_policy_accepts_missing_higher_position_cpg_slot(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-valid.vcf"
    _write_unstranded_cpg_vcf(path, second_value=".")
    result = validate_vcf_strict(path, base_modification_strandedness="unstranded")
    assert result["records"] == 2
    assert result["base_modification_strandedness_policy"] == "unstranded"


def test_number_m_stranded_policy_does_not_apply_unstranded_cpg_omission_rule(
    tmp_path: Path,
):
    path = tmp_path / "stranded-cpg-valid.vcf"
    _write_unstranded_cpg_vcf(path, second_value="0.2")
    assert validate_vcf_strict(path, base_modification_strandedness="stranded")["records"] == 2


def test_number_m_default_policy_does_not_infer_unstranded_assay(
    tmp_path: Path,
):
    path = tmp_path / "default-cpg-stranded-or-unspecified.vcf"
    _write_unstranded_cpg_vcf(path, second_value="0.2")
    result = validate_vcf_strict(path)
    assert result["base_modification_strandedness_policy"] is None


def test_number_m_unstranded_policy_handles_reverse_complement_cpg_orientation(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-reverse-orientation.vcf"
    _write_unstranded_cpg_vcf(path, second_value="0.2", reverse=True)
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path, base_modification_strandedness="unstranded")
    assert exc.value.code == "VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT"


def test_number_m_unstranded_policy_checks_cpg_slots_within_one_record(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-same-record.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tCG\t.\t.\tPASS\t.\tGT:M5mC\t0|0:0.5,.,0.6,.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path, base_modification_strandedness="unstranded")["records"] == 1


def test_number_m_unstranded_policy_rejects_length_changing_allele_coordinate_mapping(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-indel-unsupported.vcf"
    _write_number_m_vcf(
        path,
        reference="C",
        alternate="CG",
        genotype="1|.",
        field_id="M5mC",
        values="0.5,0.6",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path, base_modification_strandedness="unstranded")
    assert exc.value.code == "VCF_BASE_MODIFICATION_UNSTRANDED_UNSUPPORTED"

def test_number_m_unstranded_cross_record_validation_is_sample_scoped(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-two-samples.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\tSAMPLE2\n"
        "1\t10\t.\tC\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:alpha,.:0.5\t0|.:beta,.:0.4\n"
        "1\t11\t.\tG\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:alpha,.:.\t0|.:beta,.:0.2\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path, base_modification_strandedness="unstranded")
    assert exc.value.code == "VCF_BASE_MODIFICATION_UNSTRANDED_PLACEMENT"


def test_number_m_unstranded_cross_record_validation_respects_distinct_phase_sets(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-distinct-phase-sets.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tC\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:alpha,.:0.5\n"
        "1\t11\t.\tG\t.\t.\tPASS\t.\tGT:PSL:M5mC\t0|.:beta,.:0.2\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path, base_modification_strandedness="unstranded")["records"] == 2


def test_number_m_unstranded_cross_record_validation_supports_called_multiallelic_slots(
    tmp_path: Path,
):
    path = tmp_path / "unstranded-cpg-multiallelic.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=M5mC,Number=M,Type=Float,Description="5-methylcytosine fraction">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC,T\t.\tPASS\t.\tGT:PSL:M5mC\t1|.:alpha,.:0.5\n"
        "1\t11\t.\tA\tG,T\t.\tPASS\t.\tGT:PSL:M5mC\t1|.:alpha,.:.\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path, base_modification_strandedness="unstranded")["records"] == 2
