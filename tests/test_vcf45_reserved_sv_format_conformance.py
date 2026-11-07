from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_vcf(path: Path, format_lines: str, format_keys: str, sample: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f"{format_lines}"
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\tC\t.\tPASS\t.\tGT:{format_keys}\t0/1:{sample}\n",
        encoding="utf-8",
    )


def test_vcf45_reserved_structural_variant_format_definitions_accept_spec_types(
    tmp_path: Path,
):
    definitions = (
        '##FORMAT=<ID=CN,Number=1,Type=Float,Description="Copy number">\n'
        '##FORMAT=<ID=CICN,Number=2,Type=Float,Description="Copy number confidence interval">\n'
        '##FORMAT=<ID=CNQ,Number=1,Type=Float,Description="Copy number genotype quality">\n'
        '##FORMAT=<ID=CNL,Number=G,Type=Float,Description="Copy number genotype likelihood">\n'
        '##FORMAT=<ID=CNP,Number=G,Type=Float,Description="Copy number posterior probabilities">\n'
        '##FORMAT=<ID=NQ,Number=1,Type=Integer,Description="Novelty quality">\n'
        '##FORMAT=<ID=HAP,Number=1,Type=Integer,Description="Haplotype identifier">\n'
        '##FORMAT=<ID=AHAP,Number=1,Type=Integer,Description="Ancestral haplotype identifier">\n'
    )
    path = tmp_path / "vcf45-reserved-sv-format.vcf"
    _write_vcf(
        path,
        definitions,
        "CN:CICN:CNQ:CNL:CNP:NQ:HAP:AHAP",
        "2.0:1.5,2.5:30.0:-2.0,-1.0,0.0:0.1,0.2,0.7:5:12:13",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("field_id", "number", "field_type"),
    [
        ("CN", "1", "Integer"),
        ("CICN", "1", "Float"),
        ("CNQ", "1", "Integer"),
        ("CNL", "1", "Float"),
        ("CNP", "G", "Integer"),
        ("NQ", "1", "Float"),
        ("HAP", "1", "String"),
        ("AHAP", "2", "Integer"),
    ],
)
def test_vcf45_reserved_sv_format_rejects_wrong_header_number_or_type(
    tmp_path: Path, field_id: str, number: str, field_type: str
):
    definition = (
        f'##FORMAT=<ID={field_id},Number={number},Type={field_type},'
        'Description="Intentionally incorrect">\n'
    )
    path = tmp_path / f"vcf45-{field_id}-wrong-definition.vcf"
    _write_vcf(path, definition, field_id, "1")
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_HEADER_DEFINITION_INVALID"


@pytest.mark.parametrize(
    ("field_id", "field_type", "values"),
    [
        ("MXaoN", "Float", "0.2,0.3"),
        ("MxaoN", "Float", "0.2,0.3"),
        ("DPMXaoN", "Integer", "10,11"),
        ("DPMxaoN", "Integer", "10,11"),
        ("ADMXaoN", "Integer", "4,5"),
        ("ADMxaoN", "Integer", "4,5"),
    ],
)
def test_vcf45_xanthosine_alias_spellings_remain_recognized_pending_source_adjudication(
    tmp_path: Path, field_id: str, field_type: str, values: str
):
    path = tmp_path / f"vcf45-{field_id}-xanthosine-alias.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        f'##FORMAT=<ID={field_id},Number=M,Type={field_type},Description="Xanthosine alias">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t2\t.\tA\t.\t.\tPASS\t.\tGT:{field_id}\t0:{values}\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1
