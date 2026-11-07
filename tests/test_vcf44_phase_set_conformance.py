from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write_vcf44_phase_set_file(path: Path, pso_values: tuple[str, str, str, str]) -> None:
    sv_pso, sv_pso_ref, snv_pso, snv_pso_ref = pso_values
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##INFO=<ID=END,Number=1,Type=Integer,Description="End position">\n'
        '##INFO=<ID=SVTYPE,Number=1,Type=String,Description="Structural variant type">\n'
        '##ALT=<ID=DEL,Description="Deletion">\n'
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\tsv1\tA\t<DEL>\t.\tPASS\tSVTYPE=DEL;END=20\tGT:PSL:PSO\t0|1:phase,phase:{sv_pso_ref},{sv_pso}\n"
        f"1\t30\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:phase,phase:{snv_pso_ref},{snv_pso}\n",
        encoding="utf-8",
    )


def test_vcf44_phase_set_requires_pso_on_every_occurrence_when_set_contains_sv(tmp_path: Path):
    path = tmp_path / "vcf44-phase-set-missing-pso.vcf"
    _write_vcf44_phase_set_file(path, (".", ".", ".", "."))

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf44_phase_set_accepts_complete_pso_across_sv_and_sequence_records(tmp_path: Path):
    path = tmp_path / "vcf44-phase-set-complete-pso.vcf"
    _write_vcf44_phase_set_file(path, ("3", "2", "4", "1"))

    result = validate_vcf_strict(path)
    assert result["records"] == 2


def test_vcf44_mateid_number_a_requires_one_entry_per_alt(tmp_path: Path):
    path = tmp_path / "vcf44-mateid-number-a-cardinality.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##INFO=<ID=MATEID,Number=A,Type=String,Description="ID of mate breakend">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "1\t100\tbnd1\tA\tA]2:200],A]3:300]\t.\tPASS\tMATEID=bnd2\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


def test_vcf44_format_number_p_requires_gt_to_establish_ploidy(tmp_path: Path):
    path = tmp_path / "vcf44-number-p-without-gt.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=ALLELE_PHASE,Number=P,Type=String,Description="Per-allele phase annotation">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t.\tPASS\t.\tALLELE_PHASE\tfirst,second\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_FIELD_CARDINALITY_INVALID"


def test_vcf44_reserved_psl_header_must_match_number_p(tmp_path: Path):
    path = tmp_path / "vcf44-psl-wrong-header-definition.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=1,Type=String,Description="Wrong PSL declaration">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:phase:1,2\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_RESERVED_FORMAT_DEFINITION_MISMATCH"



def test_vcf44_psq_values_remain_positionally_aligned_for_repeated_psl_names(
    tmp_path: Path,
):
    path = tmp_path / "vcf44-psq-repeated-phase-set-positions.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSQ,Number=P,Type=Integer,Description="Phase set list quality">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC,G\t.\tPASS\t.\tGT:PSL:PSQ\t|0|1:shared,shared:12,37\n",
        encoding="utf-8",
    )

    assert validate_vcf_strict(path)["records"] == 1


def test_vcf44_psq_missing_value_must_follow_missing_psl_position(tmp_path: Path):
    path = tmp_path / "vcf44-psq-missing-phase-set-position.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSQ,Number=P,Type=Integer,Description="Phase set list quality">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tA\tC,G\t.\tPASS\t.\tGT:PSL:PSQ\t0/1|2:.,set,set:5,.,7\n",
        encoding="utf-8",
    )

    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)

    assert exc.value.code == "VCF_PHASE_SET_INVALID"


def test_vcf44_pso_ordinal_tie_is_preserved_as_unresolved(
    tmp_path: Path,
):
    path = tmp_path / "vcf44-pso-duplicate-ordinal.vcf"
    _write_vcf44_phase_set_file(path, ("3", "3", "3", "3"))

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "phase"
    )

    assert traversal["traversal_status"] == "UNRESOLVED_ORDINAL_TIES"
    assert traversal["unresolved_ordinal_tie_count"] == 1
    assert traversal["ordered_events"][0]["event_kind"] == "ORDINAL_TIE_UNRESOLVED"
    assert result["phase_set_traversal_unresolved_count"] == 1


def test_vcf44_psl_phase_set_is_global_across_chromosomes(tmp_path: Path):
    path = tmp_path / "vcf44-psl-global-across-chromosomes.vcf"
    path.write_text(
        "##fileformat=VCFv4.4\\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\\n'
        "#CHROM\\tPOS\\tID\\tREF\\tALT\\tQUAL\\tFILTER\\tINFO\\tFORMAT\\tSAMPLE1\\n"
        "1\\t5\\tdel1\\tA\\t<DEL>\\t.\\tPASS\\tEND=8;SVTYPE=DEL\\tGT:PSL:PSO\\t0|1:.,shared:.,3\\n"
        "2\\t10\\tsnv1\\tA\\tC\\t.\\tPASS\\t.\\tGT:PSL:PSO\\t0|1:.,shared:.,4\\n",
        encoding="utf-8",
    )

    result = validate_vcf_strict(path)
    traversal = next(
        item for item in result["phase_set_traversal_orders"]
        if item["sample"] == "SAMPLE1" and item["phase_set"] == "shared"
    )
    assert [event["ordinal"] for event in traversal["ordered_events"]] == [3, 4]
    assert [event["occurrences"][0]["chrom"] for event in traversal["ordered_events"]] == ["1", "2"]
