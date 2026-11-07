from pathlib import Path

import pytest

from backend.app.domain.vcf_validation import (
    StrictVCFValidationError,
    validate_vcf_strict,
)


def _write(path: Path, *, format_keys: str, sample: str) -> None:
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        f"1\t10\t.\tA\tC,G\t.\tPASS\t.\t{format_keys}\t{sample}\n",
        encoding="utf-8",
    )


def test_vcf45_source_psl_pso_tandem_duplication_example_is_positionally_aligned(
    tmp_path: Path,
):
    # Source example: GT /0/0|1; the three PSL and PSO values align to the
    # three GT allele positions, including MISSING values for unphased alleles.
    path = tmp_path / "psl-pso-source-example.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSO",
        sample="/0/0|1:.,.,chr1*10*3:.,.,3",
    )
    assert validate_vcf_strict(path)["records"] == 1


def test_vcf45_psq_has_one_entry_per_psl_gt_position_even_for_repeated_set_name(
    tmp_path: Path,
):
    path = tmp_path / "psl-psq-repeated-phase-set.vcf"
    _write(
        path,
        format_keys="GT:PSL:PSQ",
        sample="|0|1:chr1*10*1,chr1*10*1:20,20",
    )
    assert validate_vcf_strict(path)["records"] == 1


@pytest.mark.parametrize(
    ("format_keys", "sample"),
    [
        ("GT:PSL:PSO", "0/1|2:.,set,set:.,5,6"),
        ("GT:PSL:PSQ", "0/1|2:.,set,set:.,5,6"),
    ],
)
def test_vcf45_pso_and_psq_missing_values_align_with_missing_psl_positions(
    tmp_path: Path, format_keys: str, sample: str
):
    path = tmp_path / "psl-dependent-missing-alignment.vcf"
    _write(path, format_keys=format_keys, sample=sample)
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_INVALID"


def test_vcf45_local_gt_uses_global_alt_indexes_and_matches_local_projection(
    tmp_path: Path,
):
    path = tmp_path / "local-gt-global-alt-indexes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indexes">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tG\tA,C,T,<*>\t.\tPASS\t.\tGT:LAA:LAD:LPL:AD:PL\t"
        "2/2:2,4:20,30,10:90,80,0,100,110,120:20,.,30,.,10:"
        "90,.,.,80,.,0,.,.,.,.,100,.,110,.,120\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1

def test_vcf45_pso_is_required_on_every_occurrence_of_phase_set_with_sv_allele(
    tmp_path: Path,
):
    path = tmp_path / "pso-required-across-phase-set.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:set,set:.,3\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:.,.\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_PHASE_SET_PSO_REQUIRED"


def test_vcf45_pso_is_accepted_when_defined_across_entire_sv_phase_set(
    tmp_path: Path,
):
    path = tmp_path / "pso-defined-across-phase-set.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tdel1\tA\t<DEL>\t.\tPASS\tEND=8\tGT:PSL:PSO\t0|1:set,set:.,3\n"
        "1\t9\tsnv1\tA\tC\t.\tPASS\t.\tGT:PSL:PSO\t0|1:set,set:.,4\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 2


def test_vcf45_breakend_mates_require_identical_sample_psl_and_pso(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-mismatch.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:set,set:3,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:set,set:3,4\n",
        encoding="utf-8",
    )
    with pytest.raises(StrictVCFValidationError) as exc:
        validate_vcf_strict(path)
    assert exc.value.code == "VCF_BREAKEND_PHASE_SET_MISMATCH"


def test_vcf45_breakend_mates_accept_identical_sample_psl_and_pso(
    tmp_path: Path,
):
    path = tmp_path / "breakend-phase-matched.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=PSL,Number=P,Type=String,Description="Phase set list">\n'
        '##FORMAT=<ID=PSO,Number=P,Type=Integer,Description="Phase set ordinals">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t5\tbnd1\tA\tA]2:10]\t.\tPASS\tSVTYPE=BND;MATEID=bnd2\tGT:PSL:PSO\t0|1:set,set:3,3\n"
        "2\t10\tbnd2\tA\tA]1:5]\t.\tPASS\tSVTYPE=BND;MATEID=bnd1\tGT:PSL:PSO\t0|1:set,set:3,3\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 2


def test_vcf45_local_gt_2_4_remains_global_alt_indexes_not_local_indexes(
    tmp_path: Path,
):
    # This preserves the literal source-row GT while independently checking
    # that LAA=2,4 projects local likelihood vectors using global ALT indexes.
    # The source example's PL/LPL most-likely genotype discrepancy is retained
    # as a source ambiguity; the validator must not rewrite GT or equate GT to argmin(PL).
    path = tmp_path / "local-gt-source-row-global-indexes.vcf"
    path.write_text(
        "##fileformat=VCFv4.5\n"
        '##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n'
        '##FORMAT=<ID=LAA,Number=.,Type=Integer,Description="Local ALT indexes">\n'
        '##FORMAT=<ID=LAD,Number=LR,Type=Integer,Description="Local allele depths">\n'
        '##FORMAT=<ID=LPL,Number=LG,Type=Integer,Description="Local genotype likelihoods">\n'
        '##FORMAT=<ID=AD,Number=R,Type=Integer,Description="Allele depths">\n'
        '##FORMAT=<ID=PL,Number=G,Type=Integer,Description="Genotype likelihoods">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE1\n"
        "1\t10\t.\tG\tA,C,T,<*>\t.\tPASS\t.\tGT:LAA:LAD:LPL:AD:PL\t"
        "2/4:2,4:20,30,10:90,80,0,100,110,120:20,.,30,.,10:"
        "90,.,.,80,.,0,.,.,.,.,100,.,110,.,120\n",
        encoding="utf-8",
    )
    assert validate_vcf_strict(path)["records"] == 1
