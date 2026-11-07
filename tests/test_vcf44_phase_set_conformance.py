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
